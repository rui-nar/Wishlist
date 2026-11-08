"""Claim writes at the same moment as the giver leaving, being removed or
deleting their account, or the owner deleting the occasion or the list
(reserving plan D7, D10, D11, envelope Concurrency): the outcome is one of
the serial orders, never a claim held by someone who is no longer a giver,
never a 500, and D2's invariants hold.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial

import pytest
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text

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
    return client.post(
        f"/api/lists/{list_id}/gifts", json={"title": "Bike"}, headers=owner.headers
    ).json()["id"]


def new_occasion(client, owner, list_id):
    """An occasion of the list with a link: (its id, its token)."""
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": FUTURE},
        headers=owner.headers,
    ).json()["id"]
    token = client.post(
        f"/api/occasions/{occasion}/link", headers=owner.headers
    ).json()["join_token"]
    return occasion, token


def join(client, account, token):
    joined = client.post("/api/join", json={"token": token}, headers=account.headers)
    assert joined.status_code == 200, joined.text


def reserve(client, account, occasion, gift):
    return client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )


def pledge(client, account, occasion, gift):
    return client.put(
        f"/api/occasions/{occasion}/gifts/{gift}/pledge",
        json={"amount": None},
        headers=account.headers,
    )


def leave(client, owner, account, occasion):
    return client.delete(
        f"/api/occasions/{occasion}/membership", headers=account.headers
    )


def remove(client, owner, account, occasion):
    return client.delete(
        f"/api/occasions/{occasion}/members/{account.id}", headers=owner.headers
    )


def delete_account(client, owner, account, occasion):
    return client.delete("/api/me", headers=account.headers)


GOING_AWAY = pytest.mark.parametrize(
    "go_away",
    [leave, remove, delete_account],
    ids=["leave", "removal", "account deletion"],
)


def come_back(client, owner, account, occasion, token, go_away, make_account):
    """Ana as an invitee again for the next round: allowed again after a
    removal, a new account after a deletion."""
    if go_away is remove:
        client.delete(
            f"/api/occasions/{occasion}/removals/{account.id}", headers=owner.headers
        )
    if go_away is delete_account:
        account = make_account("Ana")
    join(client, account, token)
    return account


@GOING_AWAY
def test_a_reservation_racing_the_reserver_going_away(
    client, make_account, owner, list_id, gift, rows, engine, go_away
):
    occasion, token = new_occasion(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)

    for _ in range(ROUNDS):
        reserved, gone = together(
            partial(reserve, client, ana, occasion, gift),
            partial(go_away, client, owner, ana, occasion),
        )

        assert gone.status_code == 204, gone.text
        # Reserved first and released, or refused: she is no longer a giver
        # (404), or no longer signed in (401) once her account is gone.
        assert reserved.status_code in (200, 401, 404), reserved.text
        assert rows("gift_claims") == 0
        assert rows("claim_participants") == 0
        ana = come_back(client, owner, ana, occasion, token, go_away, make_account)
    assert_claims_consistent(engine)


def hold_a_reservation(connection, occasion, gift, user, bought=False):
    """A reservation made as the endpoint makes it (D7), left uncommitted."""
    values = {"occasion": occasion, "gift": gift, "user": user}
    connection.execute(
        text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"), values
    )
    connection.execute(
        text("SELECT list_id FROM gifts WHERE id = :gift FOR KEY SHARE"), values
    )
    connection.execute(
        text(
            "INSERT INTO gift_claims (gift_id, occasion_id, kind, bought_at)"
            " VALUES (:gift, :occasion, 'reservation',"
            f" {'now()' if bought else 'NULL'})"
        ),
        values,
    )
    connection.execute(
        text("INSERT INTO claim_participants (gift_id, user_id) VALUES (:gift, :user)"),
        values,
    )


@GOING_AWAY
def test_going_away_waits_for_a_reservation_then_releases_it(
    client, make_account, owner, list_id, gift, rows, engine, go_away
):
    # Deterministic: the reservation is held uncommitted; leaving, removal or
    # account deletion waits on the occasion's lock, then finds and releases
    # it.
    occasion, token = new_occasion(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    with engine.connect() as reserving:
        hold_a_reservation(reserving, occasion, gift, ana.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            going = pool.submit(go_away, client, owner, ana, occasion)
            wait_until_blocked_on_a_lock(engine)
            reserving.commit()
            gone = going.result(timeout=TIMEOUT_SECONDS)

    assert gone.status_code == 204, gone.text
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


@GOING_AWAY
def test_a_reservation_waiting_on_the_reserver_going_away_is_refused(
    client, make_account, owner, list_id, gift, rows, engine, go_away
):
    # Deterministic: the going away is the request held; the reservation is
    # made by the endpoint, waits on the occasion's lock, then is refused.
    occasion, token = new_occasion(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    values = {"occasion": occasion, "user": ana.id}
    with engine.connect() as going:
        going.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        if go_away is delete_account:
            going.execute(text("DELETE FROM users WHERE id = :user"), values)
        else:
            going.execute(
                text(
                    "DELETE FROM occasion_members"
                    " WHERE occasion_id = :occasion AND user_id = :user"
                ),
                values,
            )
        with ThreadPoolExecutor(max_workers=1) as pool:
            reserving = pool.submit(reserve, client, ana, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            going.commit()
            response = reserving.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_joining_a_group_gift_racing_the_removal_of_its_last_participant(
    client, make_account, owner, list_id, gift, rows, engine
):
    occasion, token = new_occasion(client, owner, list_id)
    ana, ben = make_account("Ana"), make_account("Ben")
    join(client, ana, token)
    join(client, ben, token)

    for _ in range(ROUNDS):
        assert pledge(client, ana, occasion, gift).status_code == 200
        joined, removed = together(
            partial(pledge, client, ben, occasion, gift),
            partial(remove, client, owner, ana, occasion),
        )

        assert joined.status_code == 200, joined.text
        assert removed.status_code == 204, removed.text
        # Ben is in a group gift, the old one or a new one, alone.
        assert rows("gift_claims", "kind", "group") == 1
        assert rows("claim_participants") == 1
        assert rows("claim_participants", "user_id", ben.id) == 1
        left = client.delete(
            f"/api/occasions/{occasion}/gifts/{gift}/pledge", headers=ben.headers
        )
        assert left.status_code == 204
        come_back(client, owner, ana, occasion, token, remove, make_account)
    assert_claims_consistent(engine)


def test_an_occasion_deleted_while_a_reservation_is_made_in_it(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana = make_account("Ana")

    for _ in range(ROUNDS):
        occasion, token = new_occasion(client, owner, list_id)
        join(client, ana, token)
        reserved, deleted = together(
            partial(reserve, client, ana, occasion, gift),
            partial(client.delete, f"/api/occasions/{occasion}", headers=owner.headers),
        )

        assert deleted.status_code == 204, deleted.text
        assert reserved.status_code in (200, 404), reserved.text
        assert rows("occasions") == 0
        assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


@pytest.mark.parametrize("bought", [False, True], ids=["unbought", "bought"])
def test_an_occasion_deletion_waits_for_a_reservation_in_it(
    client, make_account, owner, list_id, gift, rows, engine, bought
):
    # Review R1-1: the deletion waits on the reservation, then deletes it if
    # unbought, or keeps it with no occasion if bought; 204 either way.
    occasion, token = new_occasion(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    with engine.connect() as reserving:
        hold_a_reservation(reserving, occasion, gift, ana.id, bought=bought)
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(
                client.delete, f"/api/occasions/{occasion}", headers=owner.headers
            )
            wait_until_blocked_on_a_lock(engine)
            reserving.commit()
            deleted = deleting.result(timeout=TIMEOUT_SECONDS)

    assert deleted.status_code == 204, deleted.text
    assert rows("occasions") == 0
    assert rows("gift_claims") == (1 if bought else 0)
    assert_claims_consistent(engine)


@pytest.mark.parametrize("deletion", ["list", "account"])
def test_a_list_deletion_waits_for_a_reservation_on_it(
    client, make_account, owner, list_id, gift, rows, engine, deletion
):
    # The same for the list, deleted by its owner or with their account:
    # the claim goes explicitly before the cascades (D11).
    occasion, token = new_occasion(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    path = f"/api/lists/{list_id}" if deletion == "list" else "/api/me"
    with engine.connect() as reserving:
        hold_a_reservation(reserving, occasion, gift, ana.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(client.delete, path, headers=owner.headers)
            wait_until_blocked_on_a_lock(engine)
            reserving.commit()
            deleted = deleting.result(timeout=TIMEOUT_SECONDS)

    assert deleted.status_code == 204, deleted.text
    assert rows("lists") == 0
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)
