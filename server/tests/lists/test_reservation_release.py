"""What leaving, removal, account deletion and the owner's deletions leave of
the claims (reserving plan D10, D11), with unchanged answers.

One "for me" list whose gifts cost 100 EUR and two occasions dated in the
future: Ana and Ben are invitees of the first, Cleo of the second. A gift's
activity is followed through `GET /api/occasions/{id}/claims` as a giver who
stays sees it.
"""

from dataclasses import dataclass
from datetime import date, timedelta

import pytest
from claims_invariants import assert_claims_consistent

# Relative to today: a fixed date would turn into a passed occasion (D8).
FUTURE = (date.today() + timedelta(days=60)).isoformat()


@dataclass
class World:
    owner: object
    ana: object
    ben: object
    cleo: object
    list_id: str
    gifts: list[str]
    first: str
    second: str


def share(client, owner, list_id, name, *invitees):
    """An occasion of the list, joined by each invitee; returns its id."""
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": name, "date": FUTURE},
        headers=owner.headers,
    ).json()["id"]
    join(client, owner, occasion, *invitees)
    return occasion


def join(client, owner, occasion, *invitees):
    token = client.post(
        f"/api/occasions/{occasion}/link", headers=owner.headers
    ).json()["join_token"]
    for invitee in invitees:
        joined = client.post(
            "/api/join", json={"token": token}, headers=invitee.headers
        )
        assert joined.status_code == 200, joined.text


@pytest.fixture
def world(client, make_account) -> World:
    owner = make_account("Olga")
    list_id = client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=owner.headers,
    ).json()["id"]
    gifts = [
        client.post(
            f"/api/lists/{list_id}/gifts",
            json={"title": f"Gift {n}", "price_amount": 100, "price_currency": "EUR"},
            headers=owner.headers,
        ).json()["id"]
        for n in range(3)
    ]
    ana, ben, cleo = (make_account(name) for name in ("Ana", "Ben", "Cleo"))
    return World(
        owner=owner,
        ana=ana,
        ben=ben,
        cleo=cleo,
        list_id=list_id,
        gifts=gifts,
        first=share(client, owner, list_id, "Birthday", ana, ben),
        second=share(client, owner, list_id, "Christmas", cleo),
    )


def reserve(client, account, occasion, gift):
    response = client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=account.headers
    )
    assert response.status_code == 200, response.text


def mark_bought(client, account, occasion, gift):
    response = client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/bought", headers=account.headers
    )
    assert response.status_code == 200, response.text


def pledge(client, account, occasion, gift, amount="50.00"):
    response = client.put(
        f"/api/occasions/{occasion}/gifts/{gift}/pledge",
        json={"amount": amount},
        headers=account.headers,
    )
    assert response.status_code == 200, response.text


def activity(client, account, occasion):
    """The occasion's claims as the giver sees them: per gift, its state,
    whether bought, and who is in it with what pledge."""
    response = client.get(f"/api/occasions/{occasion}/claims", headers=account.headers)
    assert response.status_code == 200, response.text
    return {
        claim["gift_id"]: (
            claim["state"],
            claim["bought"],
            [(p["display_name"], p["pledge_amount"]) for p in claim["participants"]],
        )
        for claim in response.json()["gifts"]
    }


def leave(client, world, account, occasion):
    return client.delete(
        f"/api/occasions/{occasion}/membership", headers=account.headers
    )


def removal(client, world, account, occasion):
    return client.delete(
        f"/api/occasions/{occasion}/members/{account.id}",
        headers=world.owner.headers,
    )


@pytest.fixture(params=[leave, removal], ids=["leave", "removal"])
def goes_away(request):
    """Ana leaving the occasion, or its owner removing her: the same effects
    on her activity (NEEDS, Access)."""
    return request.param


@pytest.mark.parametrize("busy", [False, True], ids=["idle", "with activity"])
def test_the_answer_is_204_with_or_without_activity(
    client, world, goes_away, busy, engine
):
    if busy:
        reserve(client, world.ana, world.first, world.gifts[0])
        pledge(client, world.ana, world.first, world.gifts[1])

    response = goes_away(client, world, world.ana, world.first)

    assert (response.status_code, response.content) == (204, b"")
    assert_claims_consistent(engine)


def test_an_unbought_reservation_is_freed(client, world, goes_away, rows, engine):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.ben, world.first) == {}
    assert activity(client, world.cleo, world.second) == {}
    assert rows("gift_claims") == 0
    reserve(client, world.ben, world.first, gift)
    assert_claims_consistent(engine)


def test_a_bought_reservation_stays_with_the_name(client, world, goes_away, engine):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    mark_bought(client, world.ana, world.first, gift)

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.ben, world.first) == {
        gift: ("reserved", True, [("Ana", None)])
    }
    assert activity(client, world.cleo, world.second) == {gift: ("taken", False, [])}
    assert_claims_consistent(engine)


def test_a_pledge_goes_and_the_group_gift_keeps_the_others(
    client, world, goes_away, engine
):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift, "30.00")

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.ben, world.first) == {
        gift: ("group", False, [("Ben", "30.00")])
    }
    assert_claims_consistent(engine)


def test_the_last_participant_going_frees_the_gift(
    client, world, goes_away, rows, engine
):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.ben, world.first) == {}
    assert rows("gift_claims") == 0
    assert rows("claim_participants") == 0
    pledge(client, world.cleo, world.second, gift)
    assert_claims_consistent(engine)


def test_a_pledge_on_a_bought_group_gift_goes_and_it_stays_bought(
    client, world, goes_away, engine
):
    gift, alone = world.gifts[0], world.gifts[1]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift, "30.00")
    mark_bought(client, world.ben, world.first, gift)
    # A bought group gift with only her in it: bought, with nobody left.
    pledge(client, world.ana, world.first, alone, "100.00")
    mark_bought(client, world.ana, world.first, alone)

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.ben, world.first) == {
        gift: ("group", True, [("Ben", "30.00")]),
        alone: ("group", True, []),
    }
    assert activity(client, world.cleo, world.second) == {
        gift: ("taken", False, []),
        alone: ("taken", False, []),
    }
    assert_claims_consistent(engine)


def test_claims_in_another_occasion_are_untouched(client, world, goes_away, engine):
    # Ana is also an invitee of the second occasion, where she gives too.
    join(client, world.owner, world.second, world.ana)
    reserved, grouped = world.gifts[0], world.gifts[1]
    reserve(client, world.ana, world.second, reserved)
    pledge(client, world.ana, world.second, grouped, "20.00")
    reserve(client, world.ana, world.first, world.gifts[2])

    goes_away(client, world, world.ana, world.first)

    assert activity(client, world.cleo, world.second) == {
        reserved: ("reserved", False, [("Ana", None)]),
        grouped: ("group", False, [("Ana", "20.00")]),
    }
    assert activity(client, world.ben, world.first) == {
        reserved: ("taken", False, []),
        grouped: ("taken", False, []),
    }
    assert_claims_consistent(engine)


def test_deleting_an_account_releases_in_every_occasion(client, world, rows, engine):
    join(client, world.owner, world.second, world.ana)
    reserved, grouped, bought = world.gifts
    reserve(client, world.ana, world.first, reserved)
    pledge(client, world.ana, world.second, grouped, "50.00")
    pledge(client, world.cleo, world.second, grouped, "20.00")
    reserve(client, world.ana, world.first, bought)
    mark_bought(client, world.ana, world.first, bought)

    response = client.delete("/api/me", headers=world.ana.headers)

    assert (response.status_code, response.content) == (204, b"")
    # The reservation freed, the group gift without her, the bought gift
    # still bought with no name: nothing identifies her.
    assert activity(client, world.ben, world.first) == {
        grouped: ("taken", False, []),
        bought: ("reserved", True, []),
    }
    assert activity(client, world.cleo, world.second) == {
        grouped: ("group", False, [("Cleo", "20.00")]),
        bought: ("taken", False, []),
    }
    assert rows("claim_participants", "user_id", world.ana.id) == 0
    assert_claims_consistent(engine)


def test_deleting_an_occasion_keeps_what_was_bought_in_it_taken(
    client, world, rows, engine
):
    reserved, grouped, bought = world.gifts
    reserve(client, world.ana, world.first, reserved)
    pledge(client, world.ben, world.first, grouped)
    reserve(client, world.ana, world.first, bought)
    mark_bought(client, world.ana, world.first, bought)

    response = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )

    assert (response.status_code, response.content) == (204, b"")
    assert activity(client, world.cleo, world.second) == {bought: ("taken", False, [])}
    taken = client.post(
        f"/api/occasions/{world.second}/gifts/{bought}/reservation",
        headers=world.cleo.headers,
    )
    assert (taken.status_code, taken.json()["code"]) == (409, "taken")
    assert rows("gift_claims") == 1
    reserve(client, world.cleo, world.second, reserved)
    pledge(client, world.cleo, world.second, grouped)
    assert_claims_consistent(engine)


@pytest.mark.parametrize("kind", ["self", "other"])
def test_deleting_the_list_deletes_its_claims(
    client, world, make_account, rows, engine, kind
):
    # On a "for someone else" list, its owner's own claims go with it too.
    owner = make_account("Ola")
    body = {"title": "Party", "recipient_kind": kind}
    if kind == "other":
        body["recipient_name"] = "Leo"
    list_id = client.post("/api/lists", json=body, headers=owner.headers).json()["id"]
    gifts = [
        client.post(
            f"/api/lists/{list_id}/gifts", json={"title": title}, headers=owner.headers
        ).json()["id"]
        for title in ("Book", "Pen", "Hat")
    ]
    first = share(client, owner, list_id, "Party", world.ana, world.ben)
    reserve(client, world.ana, first, gifts[0])
    mark_bought(client, world.ana, first, gifts[0])
    pledge(client, world.ben, first, gifts[1], None)
    if kind == "other":
        reserve(client, owner, first, gifts[2])
    else:
        reserve(client, world.ben, first, gifts[2])
    # The world's own list keeps its claims.
    reserve(client, world.ana, world.first, world.gifts[0])

    response = client.delete(f"/api/lists/{list_id}", headers=owner.headers)

    assert (response.status_code, response.content) == (204, b"")
    assert rows("gift_claims") == 1
    assert rows("claim_participants") == 1
    assert_claims_consistent(engine)


def test_deleting_a_list_owners_account_deletes_its_claims(client, world, rows, engine):
    reserve(client, world.ana, world.first, world.gifts[0])
    mark_bought(client, world.ana, world.first, world.gifts[0])
    pledge(client, world.ben, world.first, world.gifts[1])
    reserve(client, world.cleo, world.second, world.gifts[2])

    response = client.delete("/api/me", headers=world.owner.headers)

    assert (response.status_code, response.content) == (204, b"")
    assert rows("gifts") == 0
    assert rows("gift_claims") == 0
    assert rows("claim_participants") == 0
    assert_claims_consistent(engine)


def test_deleting_a_gift_deletes_its_claim(client, world, rows, engine):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift)
    pledge(client, world.ben, world.first, gift)
    mark_bought(client, world.ana, world.first, gift)

    response = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)

    assert (response.status_code, response.content) == (204, b"")
    assert rows("gift_claims") == 0
    assert rows("claim_participants") == 0
    assert_claims_consistent(engine)
