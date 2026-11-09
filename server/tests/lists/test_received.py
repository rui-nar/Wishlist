"""Received, put back and keep (hidden gifts plan D5, D6).

An owner marks any gift received and puts it back, or deletes it, and
decides on revealed hidden gifts: received, dismiss (delete) or keep. The
world of `test_reservations.py`: one list whose gifts cost 100 EUR, Ana and
Ben invitees of its first occasion, Cleo of its second. Hidden gifts and
their claims are written directly in the database, as in
`test_hidden_model.py`: no route adds them yet.
"""

import re
import uuid
from datetime import date, timedelta

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent
from sqlalchemy import text
from test_group_gifts import pledge
from test_hidden_model import (
    add_hidden,
    claim_count,
    claim_routes,
    claimed_ids,
    first_on,
    gift_row,
    give,
    noon_after,
    upload,
)
from test_reservations import (
    NOT_FOUND,
    claims,
    held,
    mark_bought,
    move,
    participant,
    reserve,
)

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

NOT_REVEALED = {"detail": "This gift is not revealed", "code": "not_revealed"}
GIFT_OUT_KEYS = {
    "id",
    "list_id",
    "title",
    "description",
    "links",
    "price_amount",
    "price_currency",
    "image",
}


def mark_received(client, account, gift):
    return client.post(f"/api/gifts/{gift}/received", headers=account.headers)


def put_back(client, account, gift):
    return client.delete(f"/api/gifts/{gift}/received", headers=account.headers)


def keep(client, account, gift):
    return client.post(f"/api/gifts/{gift}/keep", headers=account.headers)


def detail(client, world):
    response = client.get(f"/api/lists/{world.list_id}", headers=world.owner.headers)
    assert response.status_code == 200, response.text
    return response.json()


def ids(gifts):
    return [gift["id"] for gift in gifts]


def answer(response):
    # Everything an owner receives but the time it was sent.
    headers = {k: v for k, v in response.headers.items() if k.lower() != "date"}
    return response.status_code, response.content, headers


def updated_at(engine, gift):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT updated_at FROM gifts WHERE id = :gift"), {"gift": gift}
        )


def occasion_gift_ids(client, account, occasion):
    view = client.get(f"/api/occasions/{occasion}", headers=account.headers)
    assert view.status_code == 200, view.text
    return ids(view.json()["gifts"])


def gift_count(client, world):
    return client.get("/api/lists", headers=world.owner.headers).json()[0]["gift_count"]


def revealed_gift(client, world, engine, title="Hidden gift", image=None):
    """A hidden gift of a first occasion dated in two days, bought by Ben,
    and the clock moved to its reveal; returns its id."""
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    gift = add_hidden(engine, world, world.first, world.ana, title, image)
    give(engine, world, gift, "bought")
    client.app.state.clock = lambda: noon_after(day)
    return gift


def every_route(client, world, gift):
    """The status of every owner and claim route on the gift."""
    owner = world.owner
    return [
        client.patch(f"/api/gifts/{gift}", json={}, headers=owner.headers).status_code,
        mark_received(client, owner, gift).status_code,
        put_back(client, owner, gift).status_code,
        keep(client, owner, gift).status_code,
        *claim_routes(client, world.ana, world.first, gift),
        *claim_routes(client, world.cleo, world.second, gift),
        client.delete(f"/api/gifts/{gift}", headers=owner.headers).status_code,
    ]


def assert_no_activity_reachable(client, world, gift):
    """The id answers 404 everywhere, and no occasion's givers see an entry
    for it, `taken` or not."""
    assert every_route(client, world, gift) == [404] * 15
    for account, occasion in ((world.ana, world.first), (world.cleo, world.second)):
        assert gift not in claimed_ids(client, account, occasion)


# Received and put back


def test_received_then_put_back_restores_its_place_and_claim(client, world, engine):
    reserved, bought, free = world.gifts
    assert reserve(client, world.ana, world.first, reserved).status_code == 200
    assert reserve(client, world.ben, world.first, bought).status_code == 200
    assert mark_bought(client, world.ben, world.first, bought).status_code == 200
    before = claims(client, world.ana, world.first).json()

    assert mark_received(client, world.owner, reserved).status_code == 204
    assert mark_received(client, world.owner, bought).status_code == 204

    shown = detail(client, world)
    assert ids(shown["gifts"]) == [free]
    # Newest first.
    assert ids(shown["received"]) == [bought, reserved]
    assert shown["revealed"] == []
    assert claims(client, world.ana, world.first).json()["gifts"] == []
    assert claim_count(engine, reserved) == claim_count(engine, bought) == 1

    assert put_back(client, world.owner, bought).status_code == 204
    assert put_back(client, world.owner, reserved).status_code == 204

    shown = detail(client, world)
    assert ids(shown["gifts"]) == world.gifts
    assert shown["received"] == []
    assert claims(client, world.ana, world.first).json() == before
    assert_claims_consistent(engine)


def test_a_received_gift_leaves_every_view_but_received(client, world, engine):
    gift = world.gifts[0]
    others = world.gifts[1:]

    assert mark_received(client, world.owner, gift).status_code == 204

    assert ids(detail(client, world)["received"]) == [gift]
    assert gift_count(client, world) == 2
    for account in (world.owner, world.ana):
        assert occasion_gift_ids(client, account, world.first) == others
    assert occasion_gift_ids(client, world.cleo, world.second) == others
    response = reserve(client, world.ana, world.first, gift)
    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert claim_routes(client, world.cleo, world.second, gift) == [404] * 5
    assert claim_count(engine, gift) == 0
    assert_claims_consistent(engine)


def test_marking_received_answers_the_same_whatever_the_activity(client, world, engine):
    free, reserved, bought = world.gifts
    group = client.post(
        f"/api/lists/{world.list_id}/gifts",
        json={"title": "Gift 3", "price_amount": 100, "price_currency": "EUR"},
        headers=world.owner.headers,
    ).json()["id"]
    assert reserve(client, world.ana, world.first, reserved).status_code == 200
    assert reserve(client, world.ben, world.first, bought).status_code == 200
    assert mark_bought(client, world.ben, world.first, bought).status_code == 200
    assert pledge(client, world.ana, world.first, group, "30.00").status_code == 200

    answers = [
        answer(mark_received(client, world.owner, gift))
        for gift in (free, reserved, bought, group)
    ]

    assert answers[0][0] == 204
    assert answers == [answers[0]] * 4
    assert_claims_consistent(engine)


def test_received_and_put_back_twice_change_nothing_more(client, world, engine):
    gift = world.gifts[0]

    assert mark_received(client, world.owner, gift).status_code == 204
    first = gift_row(engine, gift).received_at
    assert mark_received(client, world.owner, gift).status_code == 204

    # The first receipt's time kept.
    assert gift_row(engine, gift).received_at == first
    assert ids(detail(client, world)["received"]) == [gift]
    assert put_back(client, world.owner, gift).status_code == 204
    assert put_back(client, world.owner, gift).status_code == 204
    assert ids(detail(client, world)["gifts"]) == world.gifts
    assert_claims_consistent(engine)


def test_received_and_put_back_leave_updated_at_unchanged(client, world, engine):
    gift = world.gifts[0]
    before = updated_at(engine, gift)

    assert mark_received(client, world.owner, gift).status_code == 204
    assert updated_at(engine, gift) == before
    assert put_back(client, world.owner, gift).status_code == 204
    assert updated_at(engine, gift) == before
    assert_claims_consistent(engine)


def test_deleting_a_received_gift(client, world, engine):
    gift = world.gifts[0]
    assert reserve(client, world.ana, world.first, gift).status_code == 200
    assert mark_received(client, world.owner, gift).status_code == 204

    response = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)

    assert response.status_code == 204
    shown = detail(client, world)
    assert shown["received"] == []
    assert ids(shown["gifts"]) == world.gifts[1:]
    assert gift_row(engine, gift) is None
    assert_claims_consistent(engine)


def test_only_its_owners_mark_a_gift_received(client, world, engine):
    gift = world.gifts[0]

    for account in (world.ana, world.cleo):
        for call in (mark_received, put_back, keep):
            response = call(client, account, gift)
            assert (response.status_code, response.json()) == (404, NOT_FOUND)

    assert gift_row(engine, gift).received_at is None
    assert_claims_consistent(engine)


# Revealed gifts


def test_a_revealed_gift_is_shown_alone_by_title(client, world, engine):
    image = upload(client, world.ana)
    second = revealed_gift(client, world, engine, "Watch", image)
    first = add_hidden(engine, world, world.first, world.ana, "Book")
    give(engine, world, first, "bought")
    unbought = add_hidden(engine, world, world.first, world.ben, "Amber")
    give(engine, world, unbought, "reserved")

    shown = detail(client, world)

    assert ids(shown["revealed"]) == [first, second]
    assert ids(shown["gifts"]) == world.gifts
    assert shown["received"] == []
    watch = shown["revealed"][1]
    assert set(watch) == GIFT_OUT_KEYS
    assert watch["list_id"] == world.list_id
    assert watch["image"]["id"] == image
    # Its image through the owners' path.
    path = f"/api/images/{image}/full"
    assert client.get(path, headers=world.owner.headers).status_code == 200
    # Nobody's name, the author's or the buyer's, in anything the owner reads.
    reads = [
        client.get("/api/lists", headers=world.owner.headers),
        client.get(f"/api/lists/{world.list_id}", headers=world.owner.headers),
        client.get(f"/api/occasions/{world.first}", headers=world.owner.headers),
    ]
    for response in reads:
        assert response.status_code == 200, response.text
        # Join tokens are random text, where a name could appear by chance.
        body = re.sub(r'"join_token":"[^"]*"', "", response.text)
        assert not [name for name in ("Ana", "Ben") if name in body]
    assert_claims_consistent(engine)


def test_a_revealed_gift_marked_received_moves_to_received(client, world, engine):
    gift = revealed_gift(client, world, engine)

    assert mark_received(client, world.owner, gift).status_code == 204

    shown = detail(client, world)
    assert shown["revealed"] == []
    assert ids(shown["received"]) == [gift]
    assert put_back(client, world.owner, gift).status_code == 204
    shown = detail(client, world)
    assert (ids(shown["revealed"]), shown["received"]) == ([gift], [])
    assert_claims_consistent(engine)


def received_then_moved_later(client, world, engine):
    """A revealed gift marked received, then its occasion's date moved 30
    days later: its reveal date has not passed any more. Returns the gift and
    the new date."""
    gift = revealed_gift(client, world, engine)
    assert mark_received(client, world.owner, gift).status_code == 204
    later = date.today() + timedelta(days=32)
    move(client, world, world.first, later.isoformat())
    return gift, later


def test_a_received_gift_stays_received_when_its_date_moves_later(
    client, world, engine
):
    gift, later = received_then_moved_later(client, world, engine)

    assert ids(detail(client, world)["received"]) == [gift]
    for call in (put_back, keep):
        response = call(client, world.owner, gift)
        assert (response.status_code, response.json()) == (409, NOT_REVEALED)

    # Nothing changed: still received, with its claim, in its occasion.
    shown = detail(client, world)
    assert (ids(shown["received"]), shown["revealed"]) == ([gift], [])
    row = gift_row(engine, gift)
    assert row.received_at is not None
    assert str(row.hidden_occasion_id) == world.first
    assert claim_count(engine, gift) == 1
    # Put back once the new date has passed.
    client.app.state.clock = lambda: noon_after(later)
    assert put_back(client, world.owner, gift).status_code == 204
    shown = detail(client, world)
    assert (ids(shown["revealed"]), shown["received"]) == ([gift], [])
    assert_claims_consistent(engine)


def test_a_received_gift_whose_date_moved_later_survives_its_occasion(
    client, world, engine
):
    gift, _ = received_then_moved_later(client, world, engine)
    assert put_back(client, world.owner, gift).status_code == 409

    response = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )

    assert response.status_code == 204
    assert ids(detail(client, world)["received"]) == [gift]
    assert_claims_consistent(engine)


def test_dismissing_a_revealed_gift_leaves_no_activity(client, world, engine):
    gift = revealed_gift(client, world, engine)

    response = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)

    assert response.status_code == 204
    assert detail(client, world)["revealed"] == []
    assert gift_row(engine, gift) is None
    assert_no_activity_reachable(client, world, gift)
    assert_claims_consistent(engine)


def test_keeping_a_revealed_gift_puts_a_new_gift_on_the_list(client, world, engine):
    image = upload(client, world.ana)
    gift = revealed_gift(client, world, engine, "Watch", image)
    before = detail(client, world)["revealed"][0]
    path = f"/api/images/{image}/full"
    picture = client.get(path, headers=world.owner.headers).content

    response = keep(client, world.owner, gift)

    assert response.status_code == 200, response.text
    kept = response.json()
    assert kept["id"] != gift
    assert kept == before | {"id": kept["id"]}
    shown = detail(client, world)
    assert ids(shown["gifts"]) == [*world.gifts, kept["id"]]
    assert shown["gifts"][-1] == kept
    assert (shown["revealed"], shown["received"]) == ([], [])
    # The same image, readable by the owner, its bytes unchanged.
    read = client.get(path, headers=world.owner.headers)
    assert (read.status_code, read.content) == (200, picture)
    assert gift_row(engine, gift) is None
    assert claim_count(engine, kept["id"]) == 0
    # Nothing of its past: free for every occasion's givers, the old id
    # nowhere.
    for account, occasion in ((world.ana, world.first), (world.cleo, world.second)):
        assert kept["id"] not in claimed_ids(client, account, occasion)
    assert_no_activity_reachable(client, world, gift)
    reserved = reserve(client, world.cleo, world.second, kept["id"])
    assert reserved.json() == held(
        kept["id"], "reserved", False, participant("Cleo", True)
    )
    assert_claims_consistent(engine)


def test_keeping_a_received_revealed_gift(client, world, engine):
    gift = revealed_gift(client, world, engine)
    assert mark_received(client, world.owner, gift).status_code == 204

    response = keep(client, world.owner, gift)

    assert response.status_code == 200, response.text
    shown = detail(client, world)
    # On the list, not received.
    assert ids(shown["gifts"]) == [*world.gifts, response.json()["id"]]
    assert (shown["revealed"], shown["received"]) == ([], [])
    assert_claims_consistent(engine)


def test_keep_is_refused_on_a_gift_on_the_list(client, world, engine):
    gift = world.gifts[0]
    assert reserve(client, world.ana, world.first, gift).status_code == 200

    for _ in range(2):
        response = keep(client, world.owner, gift)
        assert (response.status_code, response.json()) == (409, NOT_REVEALED)
        assert mark_received(client, world.owner, gift).status_code == 204

    assert ids(detail(client, world)["received"]) == [gift]
    assert claim_count(engine, gift) == 1
    assert_claims_consistent(engine)


@pytest.mark.parametrize("state", ["free", "reserved", "bought"])
def test_an_unrevealed_hidden_gift_is_a_random_id(client, world, engine, state):
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, state)

    for gift in (hidden, uuid.uuid4()):
        for call in (mark_received, put_back, keep):
            response = call(client, world.owner, gift)
            assert (response.status_code, response.json()) == (404, NOT_FOUND)

    shown = detail(client, world)
    assert (shown["received"], shown["revealed"]) == ([], [])
    row = gift_row(engine, hidden)
    assert row.received_at is None
    assert str(row.hidden_occasion_id) == world.first
    assert_claims_consistent(engine)


def test_the_owner_of_a_list_for_someone_else_decides_the_same_way(
    client, make_world, engine
):
    world = make_world("other")
    kept = revealed_gift(client, world, engine, "Book")
    received = add_hidden(engine, world, world.first, world.ana, "Watch")
    give(engine, world, received, "bought")
    dismissed = add_hidden(engine, world, world.first, world.ana, "Yoyo")
    give(engine, world, dismissed, "bought")

    assert ids(detail(client, world)["revealed"]) == [kept, received, dismissed]
    assert mark_received(client, world.owner, received).status_code == 204
    response = keep(client, world.owner, kept)
    assert response.status_code == 200, response.text
    deleted = client.delete(f"/api/gifts/{dismissed}", headers=world.owner.headers)
    assert deleted.status_code == 204

    shown = detail(client, world)
    assert ids(shown["gifts"]) == [*world.gifts, response.json()["id"]]
    assert ids(shown["received"]) == [received]
    assert shown["revealed"] == []
    assert_no_activity_reachable(client, world, kept)
    assert_no_activity_reachable(client, world, dismissed)
    assert_claims_consistent(engine)
