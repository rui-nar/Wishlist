"""Reserving at the same moment as another giver, an owner's edit or
deletion of the gift, or a removal (reserving plan D1, D7, envelope
Concurrency): the outcome is one of the serial orders, exactly one claim
per gift, never a 500, and D2's invariants hold.
"""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial
from types import SimpleNamespace

import pytest
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.reserving.router import occasion_claims

ROUNDS = 20
FUTURE = (date.today() + timedelta(days=60)).isoformat()


@pytest.fixture
def owner(make_account):
    return make_account("Olga")


@pytest.fixture
def list_id(client, owner):
    return client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=owner.headers,
    ).json()["id"]


@pytest.fixture
def gift(client, owner, list_id):
    return add_gift(client, owner, list_id)


def add_gift(client, owner, list_id):
    return client.post(
        f"/api/lists/{list_id}/gifts", json={"title": "Bike"}, headers=owner.headers
    ).json()["id"]


def share(client, owner, list_id, *invitees):
    """An occasion of the list, joined by each invitee; returns its id."""
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": FUTURE},
        headers=owner.headers,
    ).json()["id"]
    token = client.post(
        f"/api/occasions/{occasion}/link", headers=owner.headers
    ).json()["join_token"]
    for invitee in invitees:
        joined = client.post(
            "/api/join", json={"token": token}, headers=invitee.headers
        )
        assert joined.status_code == 200, joined.text
    return occasion


def reserve(client, account, occasion, gift):
    return client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )


def release(client, account, occasion, gift):
    return client.delete(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )


def statuses(*responses):
    return sorted(response.status_code for response in responses)


def test_two_givers_reserving_together_one_gets_it(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)

    for _ in range(ROUNDS):
        results = together(
            partial(reserve, client, ana, occasion, gift),
            partial(reserve, client, ben, occasion, gift),
        )

        assert statuses(*results) == [200, 409], [r.text for r in results]
        refused = next(r for r in results if r.status_code == 409)
        assert refused.json()["code"] == "taken"
        assert rows("gift_claims") == 1
        assert rows("claim_participants") == 1
        winner = ana if results[0].status_code == 200 else ben
        assert release(client, winner, occasion, gift).status_code == 204
    assert_claims_consistent(engine)


def test_two_occasions_reserving_together_one_gets_it(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, cleo = make_account("Ana"), make_account("Cleo")
    first = share(client, owner, list_id, ana)
    second = share(client, owner, list_id, cleo)

    for _ in range(ROUNDS):
        results = together(
            partial(reserve, client, ana, first, gift),
            partial(reserve, client, cleo, second, gift),
        )

        assert statuses(*results) == [200, 409], [r.text for r in results]
        assert rows("gift_claims") == 1
        assert rows("claim_participants") == 1
        if results[0].status_code == 200:
            release(client, ana, first, gift)
        else:
            release(client, cleo, second, gift)
    assert_claims_consistent(engine)


def test_one_giver_tapping_twice_at_once_holds_one_reservation(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)

    for _ in range(ROUNDS):
        results = together(
            partial(reserve, client, ana, occasion, gift),
            partial(reserve, client, ana, occasion, gift),
        )

        assert statuses(*results) == [200, 200], [r.text for r in results]
        assert rows("claim_participants") == 1
        release(client, ana, occasion, gift)
    assert_claims_consistent(engine)


@pytest.mark.parametrize("outcome, status", [("commit", 409), ("rollback", 200)])
def test_a_reservation_waiting_on_another_follows_its_outcome(
    client, make_account, owner, list_id, gift, engine, rows, outcome, status
):
    # Deterministic: Ana's reservation is made here, as the endpoint makes
    # it, and held uncommitted; Ben's waits on the claim's key, then is
    # refused if Ana's commits and goes through if it rolls back.
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)
    with engine.connect() as holding:
        holding.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind)"
                " VALUES (:gift, :occasion, 'reservation')"
            ),
            {"gift": gift, "occasion": occasion},
        )
        holding.execute(
            text(
                "INSERT INTO claim_participants (gift_id, user_id)"
                " VALUES (:gift, :user)"
            ),
            {"gift": gift, "user": ana.id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            reserving = pool.submit(reserve, client, ben, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            getattr(holding, outcome)()
            response = reserving.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == status, response.text
    assert rows("gift_claims") == 1
    holder = ana if outcome == "commit" else ben
    assert rows("claim_participants", "user_id", holder.id) == 1
    assert_claims_consistent(engine)


def test_a_reservation_racing_the_gifts_deletion(
    client, make_account, owner, list_id, rows, engine
):
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)

    for _ in range(ROUNDS):
        gift = add_gift(client, owner, list_id)
        reserved, deleted = together(
            partial(reserve, client, ana, occasion, gift),
            partial(client.delete, f"/api/gifts/{gift}", headers=owner.headers),
        )

        assert reserved.status_code in (200, 404), reserved.text
        assert deleted.status_code == 204, deleted.text
        assert rows("gifts") == 0
        assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_a_reservation_waiting_on_the_gifts_deletion_is_a_404(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)
    with engine.connect() as deletion:
        deletion.execute(text("DELETE FROM gifts WHERE id = :gift"), {"gift": gift})
        with ThreadPoolExecutor(max_workers=1) as pool:
            reserving = pool.submit(reserve, client, ana, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            deletion.commit()
            response = reserving.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_a_reservation_racing_the_gifts_edit_both_succeed(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)

    for round_ in range(ROUNDS):
        reserved, edited = together(
            partial(reserve, client, ana, occasion, gift),
            partial(
                client.patch,
                f"/api/gifts/{gift}",
                json={"title": f"Bike {round_}"},
                headers=owner.headers,
            ),
        )

        assert reserved.status_code == 200, reserved.text
        assert edited.status_code == 200, edited.text
        assert edited.json()["title"] == f"Bike {round_}"
        assert rows("gift_claims") == 1
        release(client, ana, occasion, gift)
    assert_claims_consistent(engine)


def test_an_owners_edit_is_not_blocked_by_a_reservation_in_progress(
    client, make_account, owner, list_id, gift, engine
):
    # The gift is only locked FOR KEY SHARE (D3, D7 step 2): an edit of it
    # does not wait for a reservation that has not committed.
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)
    with engine.connect() as reserving:
        reserving.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"),
            {"occasion": occasion},
        )
        reserving.execute(
            text("SELECT list_id FROM gifts WHERE id = :gift FOR KEY SHARE"),
            {"gift": gift},
        )
        reserving.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind)"
                " VALUES (:gift, :occasion, 'reservation')"
            ),
            {"gift": gift, "occasion": occasion},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            editing = pool.submit(
                client.patch,
                f"/api/gifts/{gift}",
                json={"title": "Red bike"},
                headers=owner.headers,
            )
            edited = editing.result(timeout=TIMEOUT_SECONDS)
        reserving.rollback()

    assert edited.status_code == 200, edited.text


def test_a_reservation_waiting_on_the_reservers_removal_is_a_404(
    client, make_account, owner, list_id, gift, engine, rows
):
    # Deterministic: the owner's removal is made here, as the endpoint makes
    # it (the occasion FOR UPDATE), and held uncommitted; the reservation
    # waits on the occasion, then finds them no longer a member.
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)
    values = {"occasion": occasion, "user": ana.id}
    with engine.connect() as removal:
        removal.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        removal.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            values,
        )
        removal.execute(
            text(
                "INSERT INTO occasion_removals (occasion_id, user_id)"
                " VALUES (:occasion, :user)"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            reserving = pool.submit(reserve, client, ana, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            removal.commit()
            response = reserving.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_an_owners_occasion_change_does_not_wait_on_a_claims_read(
    client, make_account, owner, list_id, engine
):
    # The claims endpoint itself runs in a transaction held open here, as if
    # its request were still in flight; the recipient's change to the
    # occasion must not wait for it (review round 2): a read takes no lock.
    ana = make_account("Ana")
    occasion = share(client, owner, list_id, ana)
    request = SimpleNamespace(app=client.app)
    with ThreadPoolExecutor(max_workers=1) as pool, Session(engine) as reading:
        reading.begin()
        try:
            reader = reading.get_one(User, uuid.UUID(ana.id))
            read = occasion_claims(uuid.UUID(occasion), request, reader, reading)
            assert read.gifts == []
            patching = pool.submit(
                client.patch,
                f"/api/occasions/{occasion}",
                json={"name": "Renamed", "date": FUTURE},
                headers=owner.headers,
            )
            patched = patching.result(timeout=TIMEOUT_SECONDS)
        finally:
            # Released whatever happened, so a waiting PATCH cannot hang the
            # run.
            reading.rollback()

    assert patched.status_code == 200, patched.text
