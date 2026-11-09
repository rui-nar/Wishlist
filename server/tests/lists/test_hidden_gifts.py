"""Hidden gifts: what an occasion's givers add for its list (hidden gifts plan
D7, D8).

The world of `test_reservations.py`: one list whose gifts cost 100 EUR, Ana
and Ben invitees of its first occasion, Cleo of its second. What the recipient
sees of hidden gifts is also in `test_roles.py` and `test_surprise.py`.
"""

import uuid
from datetime import date, timedelta

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent
from test_group_gifts import pledge
from test_hidden_model import (
    add_claim,
    add_hidden,
    claim_count,
    claim_routes,
    claimed_ids,
    first_on,
    gift_row,
    noon_after,
    upload,
)
from test_reservations import (
    BOUGHT,
    NOT_FOUND,
    PASSED,
    PAST,
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
from test_roles import png, walk

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

NOT_AUTHOR = {
    "detail": "Only the person who added this gift can change it",
    "code": "not_author",
}
HIDDEN_GIFT_KEYS = {
    "id",
    "title",
    "description",
    "links",
    "price_amount",
    "price_currency",
    "image",
    "author",
    "mine",
}


def path(occasion, gift=None):
    base = f"/api/occasions/{occasion}/hidden-gifts"
    return base if gift is None else f"{base}/{gift}"


def listed(client, account, occasion):
    return client.get(path(occasion), headers=account.headers)


def add(client, account, occasion, title="Drone", **fields):
    return client.post(
        path(occasion), json={"title": title, **fields}, headers=account.headers
    )


def added(client, account, occasion, title="Drone", **fields):
    """Adds a hidden gift; returns its id."""
    response = add(client, account, occasion, title, **fields)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def edit(client, account, occasion, gift, **fields):
    return client.patch(path(occasion, gift), json=fields, headers=account.headers)


def remove(client, account, occasion, gift):
    return client.delete(path(occasion, gift), headers=account.headers)


def every_route(client, account, occasion, gift):
    """The four routes on the gift, as `account`: status and body."""
    responses = [
        listed(client, account, occasion),
        add(client, account, occasion),
        edit(client, account, occasion, gift, title="Changed"),
        remove(client, account, occasion, gift),
    ]
    return [(response.status_code, response.json()) for response in responses]


REFUSED_EVERYWHERE = [(404, NOT_FOUND)] * 4


def titles(client, account, occasion):
    return [gift["title"] for gift in listed(client, account, occasion).json()]


def remove_member(client, world, occasion, account):
    response = client.delete(
        f"/api/occasions/{occasion}/members/{account.id}",
        headers=world.owner.headers,
    )
    assert response.status_code == 204, response.text


# Adding and reading


def test_adding_with_every_property_and_an_uploaded_image(client, world):
    image = upload(client, world.ana)

    response = add(
        client,
        world.ana,
        world.first,
        "Drone",
        description="The small one",
        links=["https://shop.example.com/d"],
        price_amount=149,
        price_currency="EUR",
        image_id=image,
    )

    assert response.status_code == 201, response.text
    shown = f"/api/occasions/{world.first}/images/{image}"
    gift = response.json()
    assert gift == {
        "id": gift["id"],
        "title": "Drone",
        "description": "The small one",
        "links": ["https://shop.example.com/d"],
        "price_amount": "149.00",
        "price_currency": "EUR",
        "image": {
            "id": image,
            "width": gift["image"]["width"],
            "height": gift["image"]["height"],
            "url": f"{shown}/full",
            "thumb_url": f"{shown}/thumb",
        },
        "author": "Ana",
        "mine": True,
    }
    assert listed(client, world.ana, world.first).json() == [gift]
    # Another giver: the same gift, with who added it.
    assert listed(client, world.ben, world.first).json() == [gift | {"mine": False}]


def test_adding_with_an_image_url(client, world, url_fetcher):
    url_fetcher.result = (png(), "image/png")
    image = client.post(
        "/api/images/from-url",
        json={"url": "https://shop.example.com/d.png"},
        headers=world.ana.headers,
    ).json()["id"]

    gift = add(client, world.ana, world.first, image_id=image).json()

    assert gift["image"]["id"] == image
    assert (
        client.get(gift["image"]["url"], headers=world.ben.headers).status_code == 200
    )


def test_a_hidden_image_is_read_by_the_occasions_givers_only(client, world):
    image = upload(client, world.ana)
    gift = add(client, world.ana, world.first, image_id=image).json()
    url = gift["image"]["url"]

    for giver in (world.ana, world.ben):
        assert client.get(url, headers=giver.headers).status_code == 200
    for other in (world.cleo, world.owner):
        assert client.get(url, headers=other.headers).status_code == 404
    # Attached, not through an owner's path, for its uploader either.
    for account in (world.ana, world.owner):
        read = client.get(f"/api/images/{image}/full", headers=account.headers)
        assert (read.status_code, read.json()) == (404, NOT_FOUND)


def test_another_persons_image_is_refused(client, world, rows):
    image = upload(client, world.ben)

    response = add(client, world.ana, world.first, image_id=image)

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "image_not_attachable"},
    )
    assert rows("gifts", "hidden_occasion_id", world.first) == 0


def test_a_price_is_both_an_amount_and_a_currency(client, world):
    response = add(client, world.ana, world.first, price_amount=10)

    assert response.status_code == 422


def test_hidden_gifts_are_oldest_first(client, world):
    for title in ("First", "Second", "Third"):
        added(client, world.ana, world.first, title)

    assert titles(client, world.ben, world.first) == ["First", "Second", "Third"]


def test_adding_to_a_passed_occasion_is_refused(client, world, rows):
    move(client, world, world.first, PAST)

    response = add(client, world.ana, world.first)

    assert (response.status_code, response.json()) == (409, PASSED)
    assert rows("gifts", "hidden_occasion_id", world.first) == 0


def test_a_hidden_gift_stays_visible_in_its_passed_occasion(client, world):
    added(client, world.ana, world.first)

    move(client, world, world.first, PAST)

    assert titles(client, world.ben, world.first) == ["Drone"]


# Other occasions


def test_invitees_of_another_occasion_see_nothing_of_it(client, world, engine):
    gift = added(client, world.ana, world.first)
    reserve(client, world.ben, world.first, gift)

    assert every_route(client, world.cleo, world.first, gift) == REFUSED_EVERYWHERE
    # Through their own occasion, the gift is one they cannot see.
    assert listed(client, world.cleo, world.second).json() == []
    for action in (
        edit(client, world.cleo, world.second, gift, title="Changed"),
        remove(client, world.cleo, world.second, gift),
    ):
        assert (action.status_code, action.json()) == (404, NOT_FOUND)
    assert claim_routes(client, world.cleo, world.second, gift) == [404] * 5
    assert claims(client, world.cleo, world.second).json()["gifts"] == []
    assert titles(client, world.ana, world.first) == ["Drone"]
    assert_claims_consistent(engine)


def test_a_giver_of_two_occasions_changes_it_only_through_its_own(client, world):
    # Cleo joins the first occasion too: the second one still does not show
    # the first one's hidden gift.
    token = client.post(
        f"/api/occasions/{world.first}/link", headers=world.owner.headers
    ).json()["join_token"]
    client.post("/api/join", json={"token": token}, headers=world.cleo.headers)
    gift = added(client, world.cleo, world.first)

    moved = edit(client, world.cleo, world.second, gift, title="Changed")

    assert (moved.status_code, moved.json()) == (404, NOT_FOUND)
    assert edit(client, world.cleo, world.first, gift, title="Ok").status_code == 200


# Reserving, pledging, buying


def test_reserving_and_buying_it_through_the_claim_routes(client, world, engine):
    gift = added(client, world.ana, world.first)

    reserved = reserve(client, world.ben, world.first, gift)

    assert reserved.status_code == 200, reserved.text
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", False, participant("Ben", False))
    ]
    assert release(client, world.ben, world.first, gift).status_code == 204
    assert mark_bought(client, world.ben, world.first, gift).status_code == 200
    assert claims(client, world.ana, world.first).json()["gifts"] == [
        held(gift, "reserved", True, participant("Ben", False))
    ]
    assert_claims_consistent(engine)


def test_pledging_on_it_through_the_claim_routes(client, world, engine):
    gift = added(client, world.ana, world.first, price_amount=100, price_currency="EUR")

    pledged = pledge(client, world.ben, world.first, gift, "30.00")
    joined = pledge(client, world.ana, world.first, gift, "20.00")

    assert (pledged.status_code, joined.status_code) == (200, 200), joined.text
    assert claims(client, world.ben, world.first).json()["gifts"] == [
        held(
            gift,
            "group",
            False,
            participant("Ben", True, "30.00", "EUR"),
            participant("Ana", False, "20.00", "EUR"),
        )
    ]
    assert_claims_consistent(engine)


def test_a_hidden_gift_is_never_taken_elsewhere(client, world, engine):
    gift = added(client, world.ana, world.first)
    mark_bought(client, world.ben, world.first, gift)

    assert taken(gift) not in claims(client, world.cleo, world.second).json()["gifts"]
    assert claimed_ids(client, world.cleo, world.second) == set()
    assert_claims_consistent(engine)


# Editing


def test_the_author_edits_it(client, world):
    gift = added(client, world.ana, world.first, description="Old")

    response = edit(client, world.ana, world.first, gift, title="New")

    assert response.status_code == 200, response.text
    assert response.json()["title"] == "New"
    # A field left out is unchanged.
    assert response.json()["description"] == "Old"
    assert response.json()["author"] == "Ana"
    assert response.json()["mine"] is True
    assert titles(client, world.ben, world.first) == ["New"]


def test_the_author_replaces_and_removes_its_image(client, world):
    first = upload(client, world.ana)
    gift = add(client, world.ana, world.first, image_id=first).json()
    second = upload(client, world.ana)

    replaced = edit(client, world.ana, world.first, gift["id"], image_id=second)
    removed = edit(client, world.ana, world.first, gift["id"], image_id=None)

    assert replaced.json()["image"]["id"] == second
    assert removed.json()["image"] is None


def test_a_half_price_is_refused_on_an_edit(client, world):
    gift = added(client, world.ana, world.first, "Lamp")

    response = edit(client, world.ana, world.first, gift, title="X", price_amount=10)

    assert response.status_code == 422
    assert titles(client, world.ben, world.first) == ["Lamp"]


def test_another_giver_cannot_change_it(client, world):
    gift = added(client, world.ana, world.first)

    edited = edit(client, world.ben, world.first, gift, title="Changed")
    deleted = remove(client, world.ben, world.first, gift)

    assert (edited.status_code, edited.json()) == (403, NOT_AUTHOR)
    assert (deleted.status_code, deleted.json()) == (403, NOT_AUTHOR)
    assert titles(client, world.ana, world.first) == ["Drone"]


def test_a_reserved_gift_can_still_be_edited(client, world):
    gift = added(client, world.ana, world.first)
    reserve(client, world.ben, world.first, gift)

    response = edit(client, world.ana, world.first, gift, title="New")

    assert response.status_code == 200, response.text


def test_a_group_gift_can_still_be_edited(client, world):
    gift = added(client, world.ana, world.first, price_amount=100, price_currency="EUR")
    pledge(client, world.ben, world.first, gift, "30.00")

    response = edit(client, world.ana, world.first, gift, title="New")

    assert response.status_code == 200, response.text


def test_a_bought_gift_cannot_be_changed(client, world, engine):
    gift = added(client, world.ana, world.first)
    mark_bought(client, world.ben, world.first, gift)

    edited = edit(client, world.ana, world.first, gift, title="Changed")
    deleted = remove(client, world.ana, world.first, gift)

    assert (edited.status_code, edited.json()) == (409, BOUGHT)
    assert (deleted.status_code, deleted.json()) == (409, BOUGHT)
    assert titles(client, world.ben, world.first) == ["Drone"]
    assert claim_count(engine, gift) == 1


def test_a_gift_of_a_passed_occasion_cannot_be_changed(client, world):
    gift = added(client, world.ana, world.first)
    move(client, world, world.first, PAST)

    edited = edit(client, world.ana, world.first, gift, title="Changed")
    deleted = remove(client, world.ana, world.first, gift)

    assert (edited.status_code, edited.json()) == (409, PASSED)
    assert (deleted.status_code, deleted.json()) == (409, PASSED)
    assert titles(client, world.ben, world.first) == ["Drone"]


# Deleting


def test_the_author_deletes_it_and_no_activity_is_reachable(client, world, engine):
    gift = added(client, world.ana, world.first)
    reserve(client, world.ben, world.first, gift)

    response = remove(client, world.ana, world.first, gift)

    assert response.status_code == 204, response.text
    assert listed(client, world.ben, world.first).json() == []
    assert gift_row(engine, gift) is None
    assert claim_count(engine, gift) == 0
    for account, occasion in (
        (world.ana, world.first),
        (world.ben, world.first),
        (world.cleo, world.second),
    ):
        assert claim_routes(client, account, occasion, gift) == [404] * 5
        assert gift not in claimed_ids(client, account, occasion)
    assert_claims_consistent(engine)


def test_a_pledged_gift_deleted_by_its_author_leaves_no_pledge(client, world, engine):
    gift = added(client, world.ana, world.first, price_amount=100, price_currency="EUR")
    pledge(client, world.ben, world.first, gift, "30.00")

    assert remove(client, world.ana, world.first, gift).status_code == 204

    assert claim_count(engine, gift) == 0
    assert claims(client, world.ben, world.first).json()["gifts"] == []
    assert_claims_consistent(engine)


# When its author goes


def test_an_author_who_leaves_keeps_their_gifts_in_place(client, world, engine):
    gift = added(client, world.ana, world.first)

    left = client.delete(
        f"/api/occasions/{world.first}/membership", headers=world.ana.headers
    )

    assert left.status_code == 204, left.text
    [shown] = listed(client, world.ben, world.first).json()
    assert (shown["id"], shown["author"], shown["mine"]) == (gift, "Ana", False)
    # They can no longer change it, and nobody else can.
    assert every_route(client, world.ana, world.first, gift) == REFUSED_EVERYWHERE
    assert edit(client, world.ben, world.first, gift, title="X").status_code == 403
    assert_claims_consistent(engine)


def test_an_author_removed_by_the_owner_loses_the_gifts_nobody_bought(
    client, world, engine
):
    free = added(client, world.ana, world.first, "Free")
    reserved = added(client, world.ana, world.first, "Reserved")
    reserve(client, world.ben, world.first, reserved)
    pledged = added(
        client,
        world.ana,
        world.first,
        "Pledged",
        price_amount=100,
        price_currency="EUR",
    )
    pledge(client, world.ben, world.first, pledged, "30.00")
    bought = added(client, world.ana, world.first, "Bought")
    mark_bought(client, world.ben, world.first, bought)
    others = added(client, world.ben, world.first, "Ben's")
    elsewhere = add_hidden(engine, world, world.second, world.ana, "Elsewhere")

    remove_member(client, world, world.first, world.ana)

    shown = listed(client, world.ben, world.first).json()
    assert [gift["title"] for gift in shown] == ["Bought", "Ben's"]
    assert shown[0]["author"] == "Ana"
    for gift in (free, reserved, pledged):
        assert gift_row(engine, gift) is None
        assert claim_count(engine, gift) == 0
        assert claim_routes(client, world.ben, world.first, gift) == [404] * 5
    assert claimed_ids(client, world.ben, world.first) == {bought}
    assert gift_row(engine, others) is not None
    assert gift_row(engine, elsewhere) is not None
    assert_claims_consistent(engine)


def test_the_removal_answers_the_same_whether_or_not_gifts_go(client, world, engine):
    added(client, world.ana, world.first)

    response = client.delete(
        f"/api/occasions/{world.first}/members/{world.ana.id}",
        headers=world.owner.headers,
    )
    quiet = client.delete(
        f"/api/occasions/{world.first}/members/{world.ben.id}",
        headers=world.owner.headers,
    )

    assert (response.status_code, response.content) == (204, b"")
    assert (quiet.status_code, quiet.content) == (204, b"")
    assert_claims_consistent(engine)


def test_an_author_whose_account_is_deleted_leaves_no_name(client, world, engine):
    gift = added(client, world.ana, world.first)

    deleted = client.delete("/api/me", headers=world.ana.headers)

    assert deleted.status_code == 204, deleted.text
    [shown] = listed(client, world.ben, world.first).json()
    assert (shown["id"], shown["author"], shown["mine"]) == (gift, None, False)
    assert gift_row(engine, gift).hidden_by is None
    # Nobody can change it any more.
    assert edit(client, world.ben, world.first, gift, title="X").status_code == 403
    assert_claims_consistent(engine)


# For someone else


def test_the_owner_of_a_list_for_someone_else_gives_like_an_invitee(
    client, make_world, engine
):
    world = make_world("other")

    gift = add(client, world.owner, world.first, "From Olga").json()
    anas = added(client, world.ana, world.first, "From Ana")

    assert (gift["author"], gift["mine"]) == ("Olga", True)
    assert [
        (shown["title"], shown["author"], shown["mine"])
        for shown in listed(client, world.owner, world.first).json()
    ] == [("From Olga", "Olga", True), ("From Ana", "Ana", False)]
    assert reserve(client, world.owner, world.first, anas).status_code == 200
    assert anas in claimed_ids(client, world.owner, world.first)
    refused = edit(client, world.owner, world.first, anas, title="X")
    assert (refused.status_code, refused.json()) == (403, NOT_AUTHOR)
    assert_claims_consistent(engine)


# What no response carries


def test_no_user_id_and_no_timestamp_in_any_response(client, world, engine):
    image = upload(client, world.ana)
    created = add(client, world.ana, world.first, image_id=image)
    gift = created.json()["id"]
    answers = [
        created,
        listed(client, world.ben, world.first),
        edit(client, world.ana, world.first, gift, title="New"),
    ]
    user_ids = {account.id for account in (world.owner, world.ana, world.ben)}

    for response in answers:
        body = response.json()
        for found in body if isinstance(body, list) else [body]:
            assert found.keys() == HIDDEN_GIFT_KEYS
        for key, value in walk(body):
            assert not (key or "").endswith("_at"), key
            if isinstance(value, str):
                assert not any(user_id in value for user_id in user_ids), value


# The recipient


@pytest.mark.parametrize("state", ["free", "reserved", "bought", "group", "revealed"])
def test_the_recipient_gets_the_random_ids_404_on_every_route(
    client, world, engine, state
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    gift = added(client, world.ana, world.first, price_amount=100, price_currency="EUR")
    if state == "reserved":
        add_claim(engine, gift, world.first, world.ben)
    elif state == "bought":
        add_claim(engine, gift, world.first, world.ben, bought=True)
    elif state == "group":
        pledge(client, world.ben, world.first, gift, "30.00")
    elif state == "revealed":
        add_claim(engine, gift, world.first, world.ben, bought=True)
        client.app.state.clock = lambda: noon_after(day)

    assert every_route(client, world.owner, world.first, gift) == REFUSED_EVERYWHERE
    # What ids that exist nowhere get.
    nowhere = uuid.uuid4()
    assert every_route(client, world.owner, nowhere, nowhere) == REFUSED_EVERYWHERE
    # On their own occasion with a gift of no occasion of theirs too.
    assert every_route(client, world.owner, world.second, gift) == REFUSED_EVERYWHERE
    assert_claims_consistent(engine)


def test_a_new_occasion_starts_with_no_hidden_gifts(client, world):
    added(client, world.ana, world.first)

    new = share(client, world.owner, world.list_id, "New", world.ana)

    assert listed(client, world.ana, new).json() == []
