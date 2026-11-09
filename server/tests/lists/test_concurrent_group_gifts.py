"""Group gifts at the same moment as another giver's pledge, a reservation,
a leave or marking bought (reserving plan D7, envelope Concurrency): the
outcome is one of the serial orders, one claim per gift, never a 500, and
D2's invariants hold.
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
    return add_gift(client, owner, list_id)


def add_gift(client, owner, list_id):
    return client.post(
        f"/api/lists/{list_id}/gifts",
        json={"title": "Bike", "price_amount": 480, "price_currency": "EUR"},
        headers=owner.headers,
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


def pledge(client, account, occasion, gift, amount=None):
    return client.put(
        f"/api/occasions/{occasion}/gifts/{gift}/pledge",
        json={"amount": amount},
        headers=account.headers,
    )


def leave(client, account, occasion, gift):
    return client.delete(
        f"/api/occasions/{occasion}/gifts/{gift}/pledge", headers=account.headers
    )


def reserve(client, account, occasion, gift):
    return client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )


def release(client, account, occasion, gift):
    return client.delete(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )


def mark_bought(client, account, occasion, gift):
    return client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/bought", headers=account.headers
    )


def statuses(*responses):
    return sorted(response.status_code for response in responses)


def test_two_givers_pledging_together_end_in_one_group_gift(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)

    for _ in range(ROUNDS):
        results = together(
            partial(pledge, client, ana, occasion, gift, "30.00"),
            partial(pledge, client, ben, occasion, gift),
        )

        assert statuses(*results) == [200, 200], [r.text for r in results]
        assert rows("gift_claims") == 1
        assert rows("gift_claims", "kind", "group") == 1
        assert rows("claim_participants") == 2
        for account in (ana, ben):
            assert leave(client, account, occasion, gift).status_code == 204
        assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_two_occasions_pledging_together_one_gets_it(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, cleo = make_account("Ana"), make_account("Cleo")
    first = share(client, owner, list_id, ana)
    second = share(client, owner, list_id, cleo)

    for _ in range(ROUNDS):
        results = together(
            partial(pledge, client, ana, first, gift, "30.00"),
            partial(pledge, client, cleo, second, gift, "20.00"),
        )

        assert statuses(*results) == [200, 409], [r.text for r in results]
        refused = next(r for r in results if r.status_code == 409)
        assert refused.json()["code"] == "taken"
        assert rows("gift_claims") == 1
        assert rows("claim_participants") == 1
        if results[0].status_code == 200:
            leave(client, ana, first, gift)
        else:
            leave(client, cleo, second, gift)
    assert_claims_consistent(engine)


def test_a_pledge_racing_a_reservation_one_wins(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)

    for _ in range(ROUNDS):
        pledged, reserved = together(
            partial(pledge, client, ana, occasion, gift, "30.00"),
            partial(reserve, client, ben, occasion, gift),
        )

        assert statuses(pledged, reserved) == [200, 409], [
            pledged.text,
            reserved.text,
        ]
        assert rows("gift_claims") == 1
        assert rows("claim_participants") == 1
        if pledged.status_code == 200:
            assert rows("gift_claims", "kind", "group") == 1
            assert reserved.json()["code"] == "taken"
            leave(client, ana, occasion, gift)
        else:
            assert rows("gift_claims", "kind", "reservation") == 1
            assert pledged.json()["code"] == "taken"
            release(client, ben, occasion, gift)
    assert_claims_consistent(engine)


def test_a_join_racing_the_last_participants_leave(
    client, make_account, owner, list_id, gift, rows, engine
):
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)

    for _ in range(ROUNDS):
        assert pledge(client, ana, occasion, gift, "30.00").status_code == 200
        joined, left = together(
            partial(pledge, client, ben, occasion, gift, "20.00"),
            partial(leave, client, ana, occasion, gift),
        )

        # Whichever came first, Ben ends in a group gift, the old one or a
        # new one, and Ana is out of it: never an empty claim.
        assert (joined.status_code, left.status_code) == (200, 204), [
            joined.text,
            left.text,
        ]
        assert rows("gift_claims", "kind", "group") == 1
        assert rows("claim_participants") == 1
        assert rows("claim_participants", "user_id", ben.id) == 1
        assert leave(client, ben, occasion, gift).status_code == 204
    assert_claims_consistent(engine)


def test_a_join_waiting_on_the_last_participants_leave_starts_a_new_group(
    client, make_account, owner, list_id, gift, rows, engine
):
    # Deterministic: Ana's leave is made here, as the endpoint makes it, in
    # two steps. It holds the claim FOR UPDATE; Ben's pledge finds the claim
    # there (its insert does nothing) and waits on that lock. Only then are
    # her row and the emptied claim deleted and committed: Ben's lock finds
    # the claim gone, and `_take` tries once more and starts the group gift
    # afresh (D7 step 4, review R4-1).
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)
    assert pledge(client, ana, occasion, gift, "30.00").status_code == 200
    values = {"gift": gift, "user": ana.id}
    with engine.connect() as leaving:
        leaving.execute(
            text("SELECT gift_id FROM gift_claims WHERE gift_id = :gift FOR UPDATE"),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(pledge, client, ben, occasion, gift, "20.00")
            wait_until_blocked_on_a_lock(engine)
            leaving.execute(
                text(
                    "DELETE FROM claim_participants"
                    " WHERE gift_id = :gift AND user_id = :user"
                ),
                values,
            )
            leaving.execute(
                text("DELETE FROM gift_claims WHERE gift_id = :gift"), values
            )
            leaving.commit()
            response = joining.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 200, response.text
    assert [p["display_name"] for p in response.json()["participants"]] == ["Ben"]
    assert rows("gift_claims", "kind", "group") == 1
    assert rows("claim_participants", "user_id", ben.id) == 1
    assert rows("claim_participants") == 1
    assert_claims_consistent(engine)


def test_a_pledge_racing_mark_bought(
    client, make_account, owner, list_id, rows, engine
):
    ana, ben = make_account("Ana"), make_account("Ben")
    occasion = share(client, owner, list_id, ana, ben)

    for _ in range(ROUNDS):
        gift = add_gift(client, owner, list_id)
        assert pledge(client, ana, occasion, gift, "30.00").status_code == 200
        joined, bought = together(
            partial(pledge, client, ben, occasion, gift, "20.00"),
            partial(mark_bought, client, ana, occasion, gift),
        )

        assert bought.status_code == 200, bought.text
        assert bought.json()["bought"] is True
        in_it = rows("claim_participants", "user_id", ben.id)
        # Either in the group before it was bought, or refused after.
        if joined.status_code == 200:
            assert in_it == 1
        else:
            assert (joined.status_code, joined.json()["code"]) == (409, "bought")
            assert in_it == 0
        participants = [p["display_name"] for p in bought.json()["participants"]]
        assert participants in (["Ana"], ["Ana", "Ben"])
        assert rows("gift_claims", "gift_id", gift) == 1
        assert_claims_consistent(engine)
        # Bought is final: the next round takes a new gift.
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM gifts WHERE id = :gift"), {"gift": gift}
            )
