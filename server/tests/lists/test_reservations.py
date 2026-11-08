"""Reserving, releasing and marking bought, and an occasion's activity
(reserving plan D4, D6, D8).

One list, three gifts and two occasions dated in the future: Ana and Ben
are invitees of the first, Cleo of the second. A gift's activity is
followed through `GET /api/occasions/{id}/claims` as the givers see it.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.reserving.rules import has_passed

# Relative to today: a fixed date would turn into a passed occasion (D8).
FUTURE = (date.today() + timedelta(days=60)).isoformat()
# Passed for good.
PAST = "2001-01-01"
NOT_FOUND = {"detail": "Not found"}
TAKEN = {"detail": "Someone else is giving this gift", "code": "taken"}
BOUGHT = {"detail": "This gift is bought, which is final", "code": "bought"}
PASSED = {"detail": "This occasion has passed", "code": "passed"}


@dataclass
class World:
    owner: object
    # Invitees of the first occasion.
    ana: object
    ben: object
    # Invitee of the second occasion.
    cleo: object
    list_id: str
    gifts: list[str]
    first: str
    second: str


def share(client, owner, list_id, name, *invitees, on=FUTURE):
    """An occasion of the list, joined by each invitee; returns its id."""
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": name, "date": on},
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


@pytest.fixture
def make_world(client, make_account):
    def make(kind: str = "self", gifts: int = 3) -> World:
        owner = make_account("Olga")
        body = {"title": "Birthday", "recipient_kind": kind}
        if kind == "other":
            body["recipient_name"] = "Leo"
        list_id = client.post("/api/lists", json=body, headers=owner.headers).json()[
            "id"
        ]
        gift_ids = [
            client.post(
                f"/api/lists/{list_id}/gifts",
                json={
                    "title": f"Gift {n}",
                    "price_amount": 100,
                    "price_currency": "EUR",
                },
                headers=owner.headers,
            ).json()["id"]
            for n in range(gifts)
        ]
        ana, ben, cleo = (make_account(name) for name in ("Ana", "Ben", "Cleo"))
        return World(
            owner=owner,
            ana=ana,
            ben=ben,
            cleo=cleo,
            list_id=list_id,
            gifts=gift_ids,
            first=share(client, owner, list_id, "Birthday", ana, ben),
            second=share(client, owner, list_id, "Christmas", cleo),
        )

    return make


@pytest.fixture
def world(make_world) -> World:
    return make_world()


def claims(client, account, occasion):
    return client.get(f"/api/occasions/{occasion}/claims", headers=account.headers)


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


def move(client, world, occasion, on):
    moved = client.patch(
        f"/api/occasions/{occasion}", json={"date": on}, headers=world.owner.headers
    )
    assert moved.status_code == 200, moved.text


def participant(name, mine, amount=None, currency=None):
    return {
        "display_name": name,
        "mine": mine,
        "pledge_amount": amount,
        "pledge_currency": currency,
    }


def held(gift, state, bought, *participants):
    return {
        "gift_id": gift,
        "state": state,
        "bought": bought,
        "participants": list(participants),
    }


def taken(gift):
    return held(gift, "taken", False)


def add_group(engine, gift, occasion, *members):
    """A group gift, made directly: the pledge routes are U3's. Each member
    is (account, amount or None); amounts are in euros."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind)"
                " VALUES (:gift, :occasion, 'group')"
            ),
            {"gift": gift, "occasion": occasion},
        )
        for account, amount in members:
            connection.execute(
                text(
                    "INSERT INTO claim_participants"
                    " (gift_id, user_id, pledge_amount, pledge_currency)"
                    " VALUES (:gift, :user, :amount, :currency)"
                ),
                {
                    "gift": gift,
                    "user": account.id,
                    "amount": amount,
                    "currency": None if amount is None else "EUR",
                },
            )


def bought_at(engine, gift):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT bought_at FROM gift_claims WHERE gift_id = :gift"),
            {"gift": gift},
        )


def test_reserving_a_free_gift(client, world):
    gift = world.gifts[0]

    response = reserve(client, world.ana, world.first, gift)

    assert response.status_code == 200, response.text
    assert response.json() == held(gift, "reserved", False, participant("Ana", True))
    assert claims(client, world.ben, world.first).json() == {
        "passed": False,
        "gifts": [held(gift, "reserved", False, participant("Ana", False))],
    }


def test_nothing_reserved_means_no_claims(client, world):
    response = claims(client, world.ana, world.first)

    assert response.status_code == 200
    assert response.json() == {"passed": False, "gifts": []}


def test_reserving_twice_is_one_reservation(client, world, rows):
    gift = world.gifts[0]
    first = reserve(client, world.ana, world.first, gift)

    again = reserve(client, world.ana, world.first, gift)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert rows("gift_claims") == 1
    assert rows("claim_participants") == 1


def test_a_reserved_gift_is_taken_for_another_giver(client, world, rows):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    response = reserve(client, world.ben, world.first, gift)

    assert (response.status_code, response.json()) == (409, TAKEN)
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", False, participant("Ana", True))
    ]
    assert rows("claim_participants") == 1


def test_releasing_frees_the_gift(client, world, rows):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    response = release(client, world.ana, world.first, gift)

    assert response.status_code == 204
    assert response.content == b""
    assert claims(client, world.ben, world.first).json()["gifts"] == []
    assert rows("gift_claims") == 0
    assert rows("claim_participants") == 0
    assert reserve(client, world.ben, world.first, gift).status_code == 200


def test_releasing_what_i_do_not_hold(client, world):
    free, reserved = world.gifts[:2]
    reserve(client, world.ana, world.first, reserved)

    assert release(client, world.ana, world.first, free).status_code == 204
    # Someone else's reservation is not mine to release: it stays.
    assert release(client, world.ben, world.first, reserved).status_code == 204
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(reserved, "reserved", False, participant("Ana", True))
    ]


def test_a_bought_reservation_cannot_be_released(client, world):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    mark_bought(client, world.ana, world.first, gift)

    response = release(client, world.ana, world.first, gift)

    assert (response.status_code, response.json()) == (409, BOUGHT)
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", True, participant("Ana", True))
    ]


def test_marking_a_free_gift_bought_reserves_and_buys_it(client, world, rows):
    gift = world.gifts[0]

    response = mark_bought(client, world.ana, world.first, gift)

    assert response.status_code == 200, response.text
    assert response.json() == held(gift, "reserved", True, participant("Ana", True))
    assert rows("gift_claims") == 1


def test_marking_my_reservation_bought(client, world):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    response = mark_bought(client, world.ana, world.first, gift)

    assert response.status_code == 200
    assert response.json() == held(gift, "reserved", True, participant("Ana", True))
    assert claims(client, world.ben, world.first).json()["gifts"] == [
        held(gift, "reserved", True, participant("Ana", False))
    ]


def test_marking_bought_twice_changes_nothing(client, world, engine):
    gift = world.gifts[0]
    first = mark_bought(client, world.ana, world.first, gift)
    when = bought_at(engine, gift)

    again = mark_bought(client, world.ana, world.first, gift)

    assert again.status_code == 200
    assert again.json() == first.json()
    assert bought_at(engine, gift) == when
    # A double tap on reserve, after it was bought, is no change either.
    assert reserve(client, world.ana, world.first, gift).json() == first.json()


def test_someone_elses_reservation_cannot_be_marked_bought(client, world, engine):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    response = mark_bought(client, world.ben, world.first, gift)

    assert (response.status_code, response.json()) == (409, TAKEN)
    assert bought_at(engine, gift) is None


def test_a_participant_marks_a_group_gift_bought(client, world, engine):
    gift = world.gifts[0]
    add_group(engine, gift, world.first, (world.ana, "50.00"), (world.ben, None))

    response = mark_bought(client, world.ben, world.first, gift)

    assert response.status_code == 200, response.text
    assert response.json() == held(
        gift,
        "group",
        True,
        participant("Ana", False, "50.00", "EUR"),
        participant("Ben", True),
    )


def test_a_group_gift_is_not_a_reservation(client, world, engine, make_account):
    gift = world.gifts[0]
    add_group(engine, gift, world.first, (world.ana, None))
    group = held(gift, "group", False, participant("Ana", True))

    # Reserving a group gift is refused, to its participant too (D6).
    assert (reserve(client, world.ana, world.first, gift).json()) == TAKEN
    # It is not a reservation to release.
    assert release(client, world.ana, world.first, gift).status_code == 204
    # Someone not in it cannot mark it bought.
    response = mark_bought(client, world.ben, world.first, gift)
    assert (response.status_code, response.json()) == (409, TAKEN)
    assert claims(client, world.ana, world.first).json()["gifts"] == [group]


def test_a_gift_of_another_list_is_not_found(client, world, make_world, rows):
    elsewhere = make_world().gifts[0]

    for call in (reserve, release, mark_bought):
        response = call(client, world.ana, world.first, elsewhere)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
        response = call(client, world.ana, world.first, str(uuid.uuid4()))
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert rows("gift_claims") == 0


def test_the_owner_of_a_list_for_someone_else_gives(client, make_world):
    world = make_world(kind="other")
    gift = world.gifts[0]

    response = reserve(client, world.owner, world.first, gift)

    assert response.status_code == 200, response.text
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", False, participant("Olga", False))
    ]
    assert claims(client, world.owner, world.second).json()["gifts"] == [taken(gift)]


def test_another_occasion_sees_only_taken(client, world):
    reserved, bought = world.gifts[:2]
    reserve(client, world.ana, world.first, reserved)
    mark_bought(client, world.ana, world.first, bought)

    response = claims(client, world.cleo, world.second)

    # No name, no bought flag, no occasion.
    assert response.json() == {
        "passed": False,
        "gifts": [taken(reserved), taken(bought)],
    }
    assert world.first not in response.text
    for gift in (reserved, bought):
        for call in (reserve, mark_bought):
            refused = call(client, world.cleo, world.second, gift)
            assert (refused.status_code, refused.json()) == (409, TAKEN)
    # Not hers to release: Ana's reservation stays.
    assert release(client, world.cleo, world.second, reserved).status_code == 204
    assert claims(client, world.ana, world.first).json()["gifts"][0] == held(
        reserved, "reserved", False, participant("Ana", True)
    )


def test_an_invitee_of_both_occasions_sees_their_other_claim_as_taken(client, world):
    # Their reservation belongs to the occasion it was made in (Open
    # decisions: "taken", like for anyone).
    gift = world.gifts[0]
    share_link = client.post(
        f"/api/occasions/{world.second}/link", headers=world.owner.headers
    ).json()["join_token"]
    client.post("/api/join", json={"token": share_link}, headers=world.ana.headers)
    reserve(client, world.ana, world.first, gift)

    assert claims(client, world.ana, world.second).json()["gifts"] == [taken(gift)]
    response = reserve(client, world.ana, world.second, gift)
    assert (response.status_code, response.json()) == (409, TAKEN)


def test_a_passed_occasion(client, world):
    reserved, bought, free = world.gifts
    reserve(client, world.ana, world.first, reserved)
    mark_bought(client, world.ana, world.first, bought)

    move(client, world, world.first, PAST)

    # Its unbought reservation has ended, for its own invitees too; what was
    # bought in it stays, and stays taken elsewhere (D8).
    assert claims(client, world.ana, world.first).json() == {
        "passed": True,
        "gifts": [held(bought, "reserved", True, participant("Ana", True))],
    }
    assert claims(client, world.cleo, world.second).json() == {
        "passed": False,
        "gifts": [taken(bought)],
    }
    # Every other write is refused.
    for call, gift in (
        (reserve, free),
        (reserve, reserved),
        (release, reserved),
        (release, free),
        (mark_bought, free),
    ):
        response = call(client, world.ana, world.first, gift)
        assert (response.status_code, response.json()) == (409, PASSED), call
    refused = mark_bought(client, world.cleo, world.second, bought)
    assert (refused.status_code, refused.json()) == (409, TAKEN)


def test_a_giver_marks_their_claim_of_a_passed_occasion_bought(client, world):
    # A gift handed over on the day is recorded afterwards, while nobody has
    # claimed it since (D8, review round 1).
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    move(client, world, world.first, PAST)

    refused = mark_bought(client, world.ben, world.first, gift)
    response = mark_bought(client, world.ana, world.first, gift)

    assert (refused.status_code, refused.json()) == (409, PASSED)
    assert response.status_code == 200, response.text
    assert response.json() == held(gift, "reserved", True, participant("Ana", True))
    assert claims(client, world.cleo, world.second).json()["gifts"] == [taken(gift)]
    refused = reserve(client, world.cleo, world.second, gift)
    assert (refused.status_code, refused.json()) == (409, TAKEN)


def test_a_group_participant_marks_it_bought_after_the_date(client, world, engine):
    gift = world.gifts[0]
    add_group(engine, gift, world.first, (world.ana, None), (world.ben, "20.00"))
    move(client, world, world.first, PAST)

    response = mark_bought(client, world.ana, world.first, gift)

    assert response.status_code == 200, response.text
    assert response.json()["bought"] is True


def test_claiming_a_gift_of_a_passed_occasion_purges_its_claim(
    client, world, engine, rows
):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    move(client, world, world.first, PAST)
    assert claims(client, world.cleo, world.second).json()["gifts"] == []

    response = reserve(client, world.cleo, world.second, gift)

    assert response.status_code == 200, response.text
    assert rows("gift_claims") == 1
    assert rows("claim_participants", "user_id", world.ana.id) == 0
    assert rows("gift_claims", "occasion_id", world.second) == 1
    # Ana's claim is gone: nothing left of hers to mark bought.
    refused = mark_bought(client, world.ana, world.first, gift)
    assert (refused.status_code, refused.json()) == (409, PASSED)


def test_moving_the_date_back_makes_its_claims_live_again(client, world):
    # Expiry is evaluated, never written: an owner's typo destroys nothing.
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    move(client, world, world.first, PAST)

    move(client, world, world.first, FUTURE)

    assert claims(client, world.ana, world.first).json() == {
        "passed": False,
        "gifts": [held(gift, "reserved", False, participant("Ana", True))],
    }
    assert claims(client, world.cleo, world.second).json()["gifts"] == [taken(gift)]


@pytest.mark.parametrize(
    "now, passed",
    [
        (datetime(2026, 12, 25, 23, 59, 59, tzinfo=UTC), False),
        (datetime(2026, 12, 26, 11, 59, 59, tzinfo=UTC), False),
        (datetime(2026, 12, 26, 12, 0, 0, tzinfo=UTC), True),
        # Instants given in other time zones count by their UTC time: 01:00
        # on the 27th in UTC+14 is 11:00 UTC on the 26th.
        (datetime(2026, 12, 27, 1, 0, 0, tzinfo=timezone(timedelta(hours=14))), False),
        (datetime(2026, 12, 26, 2, 0, 0, tzinfo=timezone(timedelta(hours=-10))), True),
        (datetime(2027, 1, 1, tzinfo=UTC), True),
    ],
)
def test_an_occasion_has_passed_from_noon_utc_the_next_day(now, passed):
    assert has_passed(date(2026, 12, 25), now) is passed


def test_the_server_clock_decides(client, world):
    gift = world.gifts[0]
    on = date.today() + timedelta(days=2)
    move(client, world, world.first, on.isoformat())
    noon = datetime(on.year, on.month, on.day, 12, tzinfo=UTC) + timedelta(days=1)

    client.app.state.clock = lambda: noon - timedelta(seconds=1)
    before = reserve(client, world.ana, world.first, gift)
    client.app.state.clock = lambda: noon
    after = claims(client, world.ana, world.first)

    assert before.status_code == 200
    assert after.json() == {"passed": True, "gifts": []}


def test_no_user_id_in_any_claims_response(client, world, engine):
    reserved, bought, group = world.gifts
    add_group(engine, group, world.first, (world.ana, "10.00"), (world.ben, None))
    responses = [
        reserve(client, world.ana, world.first, reserved),
        mark_bought(client, world.ben, world.first, bought),
        mark_bought(client, world.ana, world.first, group),
    ]
    for account in (world.ana, world.ben):
        responses.append(claims(client, account, world.first))
    responses.append(claims(client, world.cleo, world.second))
    ids = {account.id for account in (world.owner, world.ana, world.ben, world.cleo)}

    for response in responses:
        assert response.status_code == 200, response.text
        assert not any(user_id in response.text for user_id in ids)
        assert "user_id" not in response.text


def test_the_recipient_gets_not_found_whatever_the_state(
    client, make_world, make_account, engine
):
    world = make_world(gifts=6)
    free, reserved, bought, group, elsewhere, expired = world.gifts
    reserve(client, world.ana, world.first, reserved)
    mark_bought(client, world.ana, world.first, bought)
    add_group(engine, group, world.first, (world.ana, "30.00"), (world.ben, None))
    reserve(client, world.cleo, world.second, elsewhere)
    dan = make_account("Dan")
    past = share(client, world.owner, world.list_id, "Last year", dan)
    reserve(client, dan, past, expired)
    move(client, world, past, PAST)

    def answer(response):
        headers = {k: v for k, v in response.headers.items() if k != "date"}
        return response.status_code, response.json(), headers

    def calls(occasion, gift):
        return [
            client.get(
                f"/api/occasions/{occasion}/claims", headers=world.owner.headers
            ),
            reserve(client, world.owner, occasion, gift),
            release(client, world.owner, occasion, gift),
            mark_bought(client, world.owner, occasion, gift),
        ]

    probe = [answer(response) for response in calls(uuid.uuid4(), uuid.uuid4())]
    assert all(status == 404 for status, _, _ in probe)
    for occasion in (world.first, world.second, past):
        for gift in world.gifts:
            assert [answer(r) for r in calls(occasion, gift)] == probe
    # Nothing changed by the refused calls.
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(reserved, "reserved", False, participant("Ana", True)),
        held(bought, "reserved", True, participant("Ana", True)),
        held(
            group,
            "group",
            False,
            participant("Ana", True, "30.00", "EUR"),
            participant("Ben", False),
        ),
        taken(elsewhere),
    ]
