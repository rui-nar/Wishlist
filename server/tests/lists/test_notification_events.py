"""What each cause writes in the outbox, who follows what, and what a deleted
gift leaves (comments plan D4, D9, D10, D13, D14).

The world of `test_reservations.py`: one list whose gifts cost 100 EUR, Ana
and Ben invitees of its first occasion, Cleo of its second. Events are read
from the table: nothing but the worker reads them.
"""

import uuid
from datetime import date, timedelta

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent, assert_unreachable
from sqlalchemy import text
from test_comments import delete as delete_comment
from test_comments import edit as edit_comment
from test_comments import posted, thread
from test_follows import follow, following, unfollow
from test_group_gifts import pledge
from test_hidden_gifts import added, remove
from test_hidden_model import add_hidden, claim_routes, first_on, gift_row, give, upload
from test_received import keep, mark_received, revealed_gift
from test_reservations import PAST, mark_bought, move, reserve, share

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world


def events(engine, kind=None):
    query = (
        "SELECT kind, occasion_id, gift_id, actor_id, payload FROM notification_events"
    )
    if kind is not None:
        query += " WHERE kind = :kind"
    with engine.connect() as connection:
        return [
            {
                "kind": row.kind,
                "occasion": None if row.occasion_id is None else str(row.occasion_id),
                "gift": None if row.gift_id is None else str(row.gift_id),
                "actor": None if row.actor_id is None else str(row.actor_id),
                "payload": row.payload,
            }
            for row in connection.execute(
                text(query + " ORDER BY id"), {"kind": kind}
            ).all()
        ]


def event(kind, payload, occasion=None, gift=None, actor=None):
    return {
        "kind": kind,
        "occasion": occasion,
        "gift": gift,
        "actor": actor,
        "payload": payload,
    }


def edit(client, world, gift, **fields):
    response = client.patch(
        f"/api/gifts/{gift}", json=fields, headers=world.owner.headers
    )
    assert response.status_code == 200, response.text
    return response


def delete_gift(client, world, gift):
    response = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)
    assert response.status_code == 204, response.text


def joined(client, account, occasion, gift, amount=None):
    response = pledge(client, account, occasion, gift, amount)
    assert response.status_code == 200, response.text


def group_gift(client, world, gift, *members):
    for member in members:
        joined(client, member, world.first, gift)


def leave(client, world, account):
    response = client.delete(
        f"/api/occasions/{world.first}/membership", headers=account.headers
    )
    assert response.status_code == 204, response.text


def removed_by_owner(client, world, account):
    response = client.delete(
        f"/api/occasions/{world.first}/members/{account.id}",
        headers=world.owner.headers,
    )
    assert response.status_code == 204, response.text


def account_deleted(client, world, account):
    response = client.delete("/api/me", headers=account.headers)
    assert response.status_code == 204, response.text


DEPARTURES = {
    "leaves": leave,
    "is removed": removed_by_owner,
    "deletes their account": account_deleted,
}


def expected_gifts(*gifts):
    return {
        "gifts": [
            {"gift_id": gift, "occasion_id": occasion} for gift, occasion in gifts
        ]
    }


# The owner's edits


@pytest.mark.parametrize(
    ("fields", "names"),
    [
        ({"title": "New"}, ["title"]),
        ({"description": "Blue"}, ["description"]),
        ({"links": ["https://shop.example.com/n"]}, ["links"]),
        ({"price_amount": 99}, ["price_amount"]),
        ({"price_currency": "USD"}, ["price_currency"]),
        (
            {"title": "New", "price_amount": 99, "price_currency": "USD"},
            ["title", "price_amount", "price_currency"],
        ),
    ],
)
def test_an_owners_edit_writes_one_event_with_the_changed_fields(
    client, world, engine, fields, names
):
    gift = world.gifts[0]

    edit(client, world, gift, **fields)

    assert events(engine) == [
        event("gift_changed", {"fields": names}, gift=gift, actor=world.owner.id)
    ]


def test_an_image_change_is_a_change(client, world, engine):
    gift = world.gifts[0]
    image = upload(client, world.owner)

    edit(client, world, gift, image_id=image)
    edit(client, world, gift, image_id=image)  # The same again: no event.
    edit(client, world, gift, image_id=None)

    assert (
        events(engine, "gift_changed")
        == [
            event(
                "gift_changed",
                {"fields": ["image_id"]},
                gift=gift,
                actor=world.owner.id,
            )
        ]
        * 2
    )


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"title": "Gift 0"},
        {"price_amount": 100, "price_currency": "EUR"},
        {"links": [], "description": ""},
    ],
)
def test_an_edit_that_changes_nothing_writes_nothing(client, world, engine, fields):
    edit(client, world, world.gifts[0], **fields)

    assert events(engine) == []


def test_a_refused_edit_writes_nothing(client, world, engine):
    response = client.patch(
        f"/api/gifts/{world.gifts[0]}",
        json={"price_amount": None},
        headers=world.owner.headers,
    )

    assert response.status_code == 422
    assert events(engine) == []


def test_deleting_a_gift_writes_its_title(client, world, engine):
    gift = world.gifts[0]

    delete_gift(client, world, gift)

    assert events(engine) == [
        event(
            "gift_deleted",
            {"title": "Gift 0", "received": False},
            gift=gift,
            actor=world.owner.id,
        )
    ]


def test_deleting_a_received_gift_says_it_was_received(client, world, engine):
    gift = world.gifts[0]
    assert mark_received(client, world.owner, gift).status_code == 204

    delete_gift(client, world, gift)

    assert [e["payload"] for e in events(engine, "gift_deleted")] == [
        {"title": "Gift 0", "received": True}
    ]


def test_marking_received_and_deleting_an_occasion_or_list_write_nothing(
    client, world, engine
):
    assert mark_received(client, world.owner, world.gifts[0]).status_code == 204
    client.delete(f"/api/occasions/{world.second}", headers=world.owner.headers)
    client.delete(f"/api/lists/{world.list_id}", headers=world.owner.headers)

    assert events(engine) == []


# Comments


def test_a_comment_writes_one_event(client, world, engine):
    gift = world.gifts[0]

    comment = posted(client, world.ana, world.first, gift)

    assert events(engine) == [
        event(
            "comment_added",
            {"comment_id": comment["id"]},
            occasion=world.first,
            gift=gift,
            actor=world.ana.id,
        )
    ]


def test_editing_or_deleting_a_comment_writes_nothing(client, world, engine):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    edit_comment(client, world.ana, world.first, gift, comment["id"])
    delete_comment(client, world.ana, world.first, gift, comment["id"])

    assert len(events(engine)) == 1


# Givers going away


def actor_after(how, account):
    return None if how == "deletes their account" else account.id


@pytest.mark.parametrize("how", DEPARTURES)
def test_a_departure_writes_one_event_listing_the_group_gifts_still_given(
    client, world, engine, how
):
    both, alone, reserved = world.gifts
    group_gift(client, world, both, world.ana, world.ben)
    group_gift(client, world, alone, world.ana)
    reserve(client, world.ana, world.first, reserved)

    DEPARTURES[how](client, world, world.ana)

    assert events(engine, "participants_left") == [
        event(
            "participants_left",
            expected_gifts((both, world.first)),
            actor=actor_after(how, world.ana),
        )
    ]


@pytest.mark.parametrize("how", DEPARTURES)
def test_a_departure_with_no_group_gift_writes_one_empty_event(
    client, world, engine, how
):
    DEPARTURES[how](client, world, world.ana)

    assert events(engine, "participants_left") == [
        event(
            "participants_left",
            expected_gifts(),
            actor=actor_after(how, world.ana),
        )
    ]


def test_a_bought_group_gift_is_listed(client, world, engine):
    gift = world.gifts[0]
    group_gift(client, world, gift, world.ana, world.ben)
    mark_bought(client, world.ana, world.first, gift)

    leave(client, world, world.ana)

    assert events(engine, "participants_left")[0]["payload"] == expected_gifts(
        (gift, world.first)
    )


def test_a_group_gift_of_a_passed_occasion_is_not_listed(client, world, engine):
    gift = world.gifts[0]
    group_gift(client, world, gift, world.ana, world.ben)
    move(client, world, world.first, PAST)

    leave(client, world, world.ana)

    assert events(engine, "participants_left")[0]["payload"] == expected_gifts()


def test_a_deleted_gift_is_not_listed(client, world, engine):
    gift = world.gifts[0]
    group_gift(client, world, gift, world.ana, world.ben)
    delete_gift(client, world, gift)

    leave(client, world, world.ana)

    assert events(engine, "participants_left")[0]["payload"] == expected_gifts()


def test_a_group_gift_of_a_deleted_occasion_is_not_listed(client, world, engine):
    gift = world.gifts[0]
    group_gift(client, world, gift, world.ana, world.ben)
    mark_bought(client, world.ana, world.first, gift)
    response = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )
    assert response.status_code == 204, response.text

    account_deleted(client, world, world.ana)

    assert events(engine, "participants_left")[0]["payload"] == expected_gifts()


def test_a_removal_writes_gifts_removed_with_the_authors_unbought_hidden_gifts(
    client, world, engine
):
    free = added(client, world.ana, world.first, "Free")
    pledged = added(
        client,
        world.ana,
        world.first,
        "Pledged",
        price_amount=100,
        price_currency="EUR",
    )
    joined(client, world.ben, world.first, pledged)
    bought = added(client, world.ana, world.first, "Bought")
    mark_bought(client, world.ben, world.first, bought)

    removed_by_owner(client, world, world.ana)

    expected = sorted(
        [{"gift_id": free, "title": "Free"}, {"gift_id": pledged, "title": "Pledged"}],
        key=lambda gift: uuid.UUID(gift["gift_id"]),
    )
    assert events(engine, "gifts_removed") == [
        event(
            "gifts_removed",
            {"gifts": expected},
            occasion=world.first,
            actor=world.owner.id,
        )
    ]


def test_a_removal_with_no_hidden_gift_writes_an_empty_gifts_removed(
    client, world, engine
):
    removed_by_owner(client, world, world.ana)

    assert events(engine, "gifts_removed") == [
        event(
            "gifts_removed",
            {"gifts": []},
            occasion=world.first,
            actor=world.owner.id,
        )
    ]


def test_leaving_on_ones_own_writes_no_gifts_removed(client, world, engine):
    leave(client, world, world.ana)

    assert events(engine, "gifts_removed") == []


# Following


FOLLOWING_ROUTES = ["reserve", "bought from free", "start a group", "join a group"]


def act(client, world, route, gift):
    if route == "reserve":
        reserve(client, world.ana, world.first, gift)
    elif route == "bought from free":
        mark_bought(client, world.ana, world.first, gift)
    else:
        if route == "join a group":
            joined(client, world.ben, world.first, gift)
        joined(client, world.ana, world.first, gift)


@pytest.mark.parametrize("route", FOLLOWING_ROUTES)
def test_a_claim_route_follows_the_gift(client, world, route):
    gift = world.gifts[0]

    act(client, world, route, gift)

    assert following(client, world.ana, world.first, gift) is True


@pytest.mark.parametrize("route", FOLLOWING_ROUTES)
def test_an_unfollow_stays_after_a_claim(client, world, route):
    gift = world.gifts[0]
    unfollow(client, world.ana, world.first, gift)

    act(client, world, route, gift)

    assert following(client, world.ana, world.first, gift) is False


def test_a_claim_refused_follows_nothing(client, world):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)

    response = client.post(
        f"/api/occasions/{world.first}/gifts/{gift}/reservation",
        headers=world.ben.headers,
    )

    assert response.status_code == 409
    assert following(client, world.ben, world.first, gift) is False


@pytest.mark.parametrize("how", ["leaves", "is removed"])
def test_leaving_or_removal_drops_their_follows_in_that_occasion_only(
    client, world, rows, how
):
    gift = world.gifts[0]
    other = share(client, world.owner, world.list_id, "Third", world.ana)
    follow(client, world.ana, world.first, gift)
    follow(client, world.ben, world.first, gift)
    follow(client, world.ana, other, gift)

    DEPARTURES[how](client, world, world.ana)

    assert rows("gift_follows", "occasion_id", world.first) == 1
    assert following(client, world.ben, world.first, gift) is True
    assert following(client, world.ana, other, gift) is True


def test_account_deletion_drops_every_follow(client, world, rows):
    gift = world.gifts[0]
    follow(client, world.ana, world.first, gift)
    follow(client, world.ben, world.first, gift)

    account_deleted(client, world, world.ana)

    assert rows("gift_follows", "user_id", world.ana.id) == 0
    assert rows("gift_follows", "user_id", world.ben.id) == 1


# What a deleted gift leaves


def test_a_deleted_gift_leaves_its_activity_unreachable(client, world, engine, rows):
    gift = world.gifts[0]
    group_gift(client, world, gift, world.ana, world.ben)
    posted(client, world.ana, world.first, gift)
    follow(client, world.ben, world.first, gift)

    delete_gift(client, world, gift)

    assert rows("gift_claims", "gift_id", gift) == 1
    assert rows("claim_participants", "gift_id", gift) == 2
    assert rows("comments", "gift_id", gift) == 1
    assert rows("gift_follows", "gift_id", gift) == 2
    for account in (world.ana, world.ben):
        assert_unreachable(client, account, world.first, gift)
        assert claim_routes(client, account, world.first, gift) == [404] * 5
    assert_claims_consistent(engine)


def unbought_orphan(client, world, engine):
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    delete_gift(client, world, gift)
    assert_claims_consistent(engine)
    return gift


def test_a_deleted_gift_then_its_list_deleted(client, world, engine, rows):
    unbought_orphan(client, world, engine)

    response = client.delete(f"/api/lists/{world.list_id}", headers=world.owner.headers)

    assert response.status_code == 204, response.text
    assert_claims_consistent(engine)
    # Its claim stays until the sweep, its occasion gone.
    assert rows("gift_claims") == 1


def test_a_deleted_gift_then_its_owners_account_deleted(client, world, engine):
    unbought_orphan(client, world, engine)

    account_deleted(client, world, world.owner)

    assert_claims_consistent(engine)


@pytest.mark.parametrize("thread_on_it", [False, True])
def test_a_revealed_gift_edited_or_dismissed_writes_no_event(
    client, world, engine, thread_on_it
):
    gift = revealed_gift(client, world, engine)
    if thread_on_it:
        posted(client, world.ana, world.first, gift)
        follow(client, world.ben, world.first, gift)
    client.patch(
        f"/api/gifts/{gift}", json={"title": "Renamed"}, headers=world.owner.headers
    )

    delete_gift(client, world, gift)

    assert not events(engine, "gift_changed")
    assert not events(engine, "gift_deleted")


def test_keeping_a_revealed_gift_writes_no_event_and_leaves_the_rows(
    client, world, engine, rows
):
    gift = revealed_gift(client, world, engine)

    response = keep(client, world.owner, gift)

    assert response.status_code == 200, response.text
    assert not events(engine)
    assert rows("gift_claims", "gift_id", gift) == 1
    assert claim_routes(client, world.ana, world.first, gift) == [404] * 5
    assert_unreachable(client, world.ana, world.first, gift)
    assert_claims_consistent(engine)


def test_dismissing_a_revealed_gift_leaves_the_rows_unreachable(
    client, world, engine, rows
):
    gift = revealed_gift(client, world, engine)
    posted(client, world.ana, world.first, gift)

    delete_gift(client, world, gift)

    assert gift_row(engine, gift) is None
    assert rows("gift_claims", "gift_id", gift) == 1
    assert rows("comments", "gift_id", gift) == 1
    assert_unreachable(client, world.ana, world.first, gift)
    assert_claims_consistent(engine)


def test_an_author_deleting_a_hidden_gift_leaves_the_rows_unreachable(
    client, world, engine, rows
):
    gift = added(client, world.ana, world.first)
    reserve(client, world.ben, world.first, gift)
    posted(client, world.ben, world.first, gift)
    before = len(events(engine))

    assert remove(client, world.ana, world.first, gift).status_code == 204

    assert rows("gift_claims", "gift_id", gift) == 1
    assert rows("comments", "gift_id", gift) == 1
    assert_unreachable(client, world.ben, world.first, gift)
    assert_claims_consistent(engine)
    # Nothing but the earlier comment's: an author's deletion notifies nobody.
    assert len(events(engine)) == before


def test_an_author_editing_a_hidden_gift_writes_no_event(client, world, engine):
    gift = added(client, world.ana, world.first)

    response = client.patch(
        f"/api/occasions/{world.first}/hidden-gifts/{gift}",
        json={"title": "Renamed"},
        headers=world.ana.headers,
    )

    assert response.status_code == 200, response.text
    assert events(engine) == []


def test_an_owners_edit_of_a_hidden_gift_is_refused_and_writes_nothing(
    client, world, engine
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    gift = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, gift, "bought")

    response = client.patch(
        f"/api/gifts/{gift}", json={"title": "Renamed"}, headers=world.owner.headers
    )

    assert response.status_code == 404
    assert events(engine) == []


def test_every_comment_of_the_thread_still_reads(client, world):
    gift = world.gifts[0]
    posted(client, world.ana, world.first, gift)

    assert len(thread(client, world.ana, world.first, gift)["comments"]) == 1
