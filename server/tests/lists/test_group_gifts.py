"""Group gifts: starting, joining, changing a pledge and leaving (reserving
plan D6, D9).

The world of `test_reservations.py`: one list whose gifts cost 100 EUR, Ana
and Ben invitees of its first occasion, Cleo of its second.
"""

import uuid

import pytest
import test_reservations
from test_reservations import (
    BOUGHT,
    NOT_FOUND,
    PASSED,
    PAST,
    TAKEN,
    claims,
    held,
    mark_bought,
    move,
    participant,
    release,
    reserve,
    share,
    taken,
)

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world


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


def test_starting_a_group_gift(client, world, rows):
    gift = world.gifts[0]

    response = pledge(client, world.ana, world.first, gift, "50.00")

    assert response.status_code == 200, response.text
    assert response.json() == held(
        gift, "group", False, participant("Ana", True, "50.00", "EUR")
    )
    assert claims(client, world.ben, world.first).json() == {
        "passed": False,
        "gifts": [
            held(gift, "group", False, participant("Ana", False, "50.00", "EUR"))
        ],
    }
    assert rows("gift_claims", "kind", "group") == 1


def test_joining_a_group_gift(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")

    response = pledge(client, world.ben, world.first, gift, "30")

    assert response.status_code == 200, response.text
    assert response.json() == held(
        gift,
        "group",
        False,
        participant("Ana", False, "50.00", "EUR"),
        participant("Ben", True, "30.00", "EUR"),
    )


def test_joining_without_an_amount(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift)

    response = pledge(client, world.ben, world.first, gift, None)

    assert response.status_code == 200, response.text
    assert response.json() == held(
        gift, "group", False, participant("Ana", False), participant("Ben", True)
    )


def test_changing_my_amount(client, world, rows):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift, "30.00")

    changed = pledge(client, world.ana, world.first, gift, "70.50")
    cleared = pledge(client, world.ben, world.first, gift, None)

    assert changed.status_code == 200, changed.text
    # Changing an amount keeps one's place among the participants.
    assert cleared.json() == held(
        gift,
        "group",
        False,
        participant("Ana", False, "70.50", "EUR"),
        participant("Ben", True),
    )
    assert rows("claim_participants") == 2


def test_pledging_the_same_amount_twice_changes_nothing(client, world, rows):
    gift = world.gifts[0]
    first = pledge(client, world.ana, world.first, gift, "50.00")

    again = pledge(client, world.ana, world.first, gift, "50.00")

    assert again.status_code == 200
    assert again.json() == first.json()
    assert rows("claim_participants") == 1


def test_leaving_a_group_gift(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift, "30.00")

    response = leave(client, world.ana, world.first, gift)

    assert response.status_code == 204
    assert response.content == b""
    # Their pledge goes with them; the group stays.
    assert claims(client, world.ben, world.first).json()["gifts"] == [
        held(gift, "group", False, participant("Ben", True, "30.00", "EUR"))
    ]


def test_the_last_one_out_frees_the_gift(client, world, rows):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift)
    leave(client, world.ana, world.first, gift)

    response = leave(client, world.ben, world.first, gift)

    assert response.status_code == 204
    assert claims(client, world.ana, world.first).json()["gifts"] == []
    assert rows("gift_claims") == 0
    assert rows("claim_participants") == 0
    assert claims(client, world.cleo, world.second).json()["gifts"] == []
    assert reserve(client, world.cleo, world.second, gift).status_code == 200


def test_leaving_what_i_am_not_in(client, world):
    free, group, reserved = world.gifts
    pledge(client, world.ana, world.first, group, "50.00")
    reserve(client, world.ana, world.first, reserved)

    for gift in (free, group, reserved):
        assert leave(client, world.ben, world.first, gift).status_code == 204
    # Ana's reservation is not a group gift to leave: it stays, as does her
    # group gift.
    assert leave(client, world.ana, world.first, reserved).status_code == 204
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(group, "group", False, participant("Ana", True, "50.00", "EUR")),
        held(reserved, "reserved", False, participant("Ana", True)),
    ]


def test_a_reserved_gift_cannot_be_pledged_on(client, world):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    # Mine included: release it first (D6).
    for account in (world.ana, world.ben):
        response = pledge(client, account, world.first, gift, "20.00")
        assert (response.status_code, response.json()) == (409, TAKEN)
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", False, participant("Ana", True))
    ]


def test_a_gift_held_in_another_occasion_cannot_be_pledged_on(client, world):
    reserved, group, bought = world.gifts
    reserve(client, world.ana, world.first, reserved)
    pledge(client, world.ana, world.first, group, "20.00")
    mark_bought(client, world.ana, world.first, bought)

    for gift in world.gifts:
        response = pledge(client, world.cleo, world.second, gift, "10.00")
        assert (response.status_code, response.json()) == (409, TAKEN)
        # Not hers to leave: nothing changes.
        assert leave(client, world.cleo, world.second, gift).status_code == 204
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(reserved, "reserved", False, participant("Ana", True)),
        held(group, "group", False, participant("Ana", True, "20.00", "EUR")),
        held(bought, "reserved", True, participant("Ana", True)),
    ]


def test_a_participant_marks_it_bought(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift)

    response = mark_bought(client, world.ben, world.first, gift)

    assert response.status_code == 200, response.text
    assert response.json() == held(
        gift,
        "group",
        True,
        participant("Ana", False, "50.00", "EUR"),
        participant("Ben", True),
    )
    assert claims(client, world.cleo, world.second).json()["gifts"] == [taken(gift)]


def test_a_bought_group_gift_is_frozen(client, world, make_account, rows):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    mark_bought(client, world.ana, world.first, gift)
    bought = held(gift, "group", True, participant("Ana", True, "50.00", "EUR"))

    for amount in ("50.00", "60.00", None):
        response = pledge(client, world.ana, world.first, gift, amount)
        assert (response.status_code, response.json()) == (409, BOUGHT)
    joined = pledge(client, world.ben, world.first, gift, "10.00")
    left = leave(client, world.ana, world.first, gift)

    assert (joined.status_code, joined.json()) == (409, BOUGHT)
    assert (left.status_code, left.json()) == (409, BOUGHT)
    assert claims(client, world.ana, world.first).json()["gifts"] == [bought]
    # Someone who is not in it has nothing to leave.
    assert leave(client, world.ben, world.first, gift).status_code == 204
    assert rows("claim_participants") == 1


def test_a_group_gift_cannot_be_released_as_a_reservation(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")

    assert release(client, world.ana, world.first, gift).status_code == 204
    refused = reserve(client, world.ana, world.first, gift)

    assert (refused.status_code, refused.json()) == (409, TAKEN)
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "group", False, participant("Ana", True, "50.00", "EUR"))
    ]


@pytest.mark.parametrize(
    "amount", ["0", "0.00", "-5", "19.999", "10000000000", "abc", 0, -1]
)
def test_an_amount_out_of_bounds_is_refused(client, world, rows, amount):
    gift = world.gifts[0]

    response = pledge(client, world.ana, world.first, gift, amount)

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", "amount"]
    assert rows("gift_claims") == 0


def test_the_largest_amount_is_accepted(client, world):
    gift = world.gifts[0]

    response = pledge(client, world.ana, world.first, gift, "9999999999.99")

    assert response.status_code == 200, response.text
    assert response.json()["participants"][0]["pledge_amount"] == "9999999999.99"


def test_an_unknown_field_is_refused(client, world, rows):
    response = client.put(
        f"/api/occasions/{world.first}/gifts/{world.gifts[0]}/pledge",
        json={"amount": "10.00", "currency": "USD"},
        headers=world.ana.headers,
    )

    assert response.status_code == 422
    assert rows("gift_claims") == 0


def test_a_gift_without_a_price_takes_no_amount(client, world, rows):
    gift = client.post(
        f"/api/lists/{world.list_id}/gifts",
        json={"title": "A surprise"},
        headers=world.owner.headers,
    ).json()["id"]

    refused = pledge(client, world.ana, world.first, gift, "10.00")
    joined = pledge(client, world.ana, world.first, gift, None)

    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"][0]["loc"] == ["body", "amount"]
    assert joined.status_code == 200, joined.text
    assert joined.json() == held(gift, "group", False, participant("Ana", True))
    # Nor does a group gift already started on it.
    refused = pledge(client, world.ben, world.first, gift, "10.00")
    assert refused.status_code == 422
    assert rows("claim_participants") == 1


def test_a_pledge_keeps_the_currency_it_was_made_in(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")

    edited = client.patch(
        f"/api/gifts/{gift}",
        json={"price_currency": "USD"},
        headers=world.owner.headers,
    )
    assert edited.status_code == 200, edited.text
    pledge(client, world.ben, world.first, gift, "30.00")

    # Each in its own currency: the owner's edit reinterprets nothing (D9).
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(
            gift,
            "group",
            False,
            participant("Ana", True, "50.00", "EUR"),
            participant("Ben", False, "30.00", "USD"),
        )
    ]
    # Changing one's amount pledges it in the gift's currency of the moment.
    changed = pledge(client, world.ana, world.first, gift, "55.00")
    assert changed.json()["participants"][0] == participant("Ana", True, "55.00", "USD")


def test_another_occasion_sees_only_taken(client, world):
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "50.00")
    pledge(client, world.ben, world.first, gift)

    response = claims(client, world.cleo, world.second)

    # No names, no amounts, no occasion.
    assert response.json() == {"passed": False, "gifts": [taken(gift)]}
    assert "50.00" not in response.text
    assert world.first not in response.text


def test_the_owner_of_a_list_for_someone_else_pledges(client, make_world):
    world = make_world(kind="other")
    gift = world.gifts[0]
    pledge(client, world.ana, world.first, gift, "40.00")

    response = pledge(client, world.owner, world.first, gift, "60.00")

    assert response.status_code == 200, response.text
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(
            gift,
            "group",
            False,
            participant("Ana", True, "40.00", "EUR"),
            participant("Olga", False, "60.00", "EUR"),
        )
    ]
    assert leave(client, world.owner, world.first, gift).status_code == 204
    assert claims(client, world.owner, world.second).json()["gifts"] == [taken(gift)]


def test_a_passed_occasion_refuses_pledges(client, world):
    group, free = world.gifts[:2]
    pledge(client, world.ana, world.first, group, "50.00")
    move(client, world, world.first, PAST)

    for call, gift in (
        (pledge, free),
        (pledge, group),
        (leave, group),
        (leave, free),
    ):
        response = call(client, world.ana, world.first, gift)
        assert (response.status_code, response.json()) == (409, PASSED)
    # Its unbought group gift has ended: the gift is free elsewhere, and
    # starting a group gift there purges it.
    response = pledge(client, world.cleo, world.second, group, "20.00")
    assert response.status_code == 200, response.text
    assert response.json() == held(
        group, "group", False, participant("Cleo", True, "20.00", "EUR")
    )


def test_a_gift_of_another_list_is_not_found(client, world, make_world, rows):
    elsewhere = make_world().gifts[0]

    for gift in (elsewhere, str(uuid.uuid4())):
        for call in (pledge, leave):
            response = call(client, world.ana, world.first, gift)
            assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert rows("gift_claims") == 0


def test_the_recipient_gets_not_found_whatever_the_state(
    client, world, make_account, rows
):
    expired, group, bought = world.gifts
    pledge(client, world.ana, world.first, group, "30.00")
    pledge(client, world.ben, world.first, group)
    pledge(client, world.ana, world.first, bought, "10.00")
    mark_bought(client, world.ana, world.first, bought)
    dan = make_account("Dan")
    past = share(client, world.owner, world.list_id, "Last year", dan)
    pledge(client, dan, past, expired, "40.00")
    move(client, world, past, PAST)
    # Its participant still sees the expired one (review R3-1); the
    # recipient does not, below.
    assert claims(client, dan, past).json()["gifts"][0] == held(
        expired, "group", False, participant("Dan", True, "40.00", "EUR"), expired=True
    )

    def answer(response):
        headers = {k: v for k, v in response.headers.items() if k != "date"}
        return response.status_code, response.json(), headers

    def calls(occasion, gift):
        return [
            pledge(client, world.owner, occasion, gift, amount)
            for amount in ("20.00", None)
        ] + [leave(client, world.owner, occasion, gift)]

    probe = [answer(response) for response in calls(uuid.uuid4(), uuid.uuid4())]
    assert all(status == 404 for status, _, _ in probe)
    for occasion in (world.first, world.second, past):
        for gift in world.gifts:
            assert [answer(r) for r in calls(occasion, gift)] == probe
    # Nothing changed by the refused calls.
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(
            group,
            "group",
            False,
            participant("Ana", True, "30.00", "EUR"),
            participant("Ben", False),
        ),
        held(bought, "group", True, participant("Ana", True, "10.00", "EUR")),
    ]
    assert rows("claim_participants") == 4
