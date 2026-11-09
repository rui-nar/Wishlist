"""The hidden-gift model and the visibility guard (hidden gifts plan D1-D4,
D9, D12).

No route adds hidden gifts or marks gifts received yet: both are written
directly in the database, and every existing route must see exactly the
gifts `app.lists.visibility` allows. The world of `test_reservations.py`:
one list whose gifts cost 100 EUR, Ana and Ben invitees of its first
occasion, Cleo of its second.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent
from sqlalchemy import text
from test_group_gifts import leave, pledge
from test_reservations import (
    NOT_FOUND,
    PAST,
    add_group,
    claims,
    held,
    mark_bought,
    move,
    participant,
    release,
    reserve,
    share,
)
from test_roles import png

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

APP_DIR = Path(__file__).resolve().parents[2] / "app"
HIDDEN_COLUMNS = ("for_list_id", "hidden_occasion_id", "received_at")
# The modules allowed to name them (Conventions).
ALLOWED = (
    APP_DIR / "lists" / "models.py",
    APP_DIR / "lists" / "visibility.py",
    APP_DIR / "hidden_gifts",
)


def add_hidden(engine, world, occasion, author, title="Hidden gift", image=None):
    """A hidden gift of the occasion, added by `author`; returns its id."""
    with engine.begin() as connection:
        gift = connection.scalar(
            text(
                "INSERT INTO gifts (id, for_list_id, hidden_occasion_id, hidden_by,"
                " title, description, links, price_amount, price_currency,"
                " image_id)"
                " VALUES (:id, :list, :occasion, :author, :title, '', '{}', 100,"
                " 'EUR', :image) RETURNING id"
            ),
            {
                "id": uuid.uuid4(),
                "list": world.list_id,
                "occasion": occasion,
                "author": author.id,
                "title": title,
                "image": image,
            },
        )
        if image is not None:
            connection.execute(
                text("UPDATE images SET attached_at = now() WHERE id = :image"),
                {"image": image},
            )
    return str(gift)


def add_claim(engine, gift, occasion, account, bought=False):
    """A reservation by `account`, bought or not, made directly."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind, bought_at)"
                " VALUES (:gift, :occasion, 'reservation', :bought)"
            ),
            {
                "gift": gift,
                "occasion": occasion,
                "bought": datetime.now(UTC) if bought else None,
            },
        )
        connection.execute(
            text(
                "INSERT INTO claim_participants (gift_id, user_id)"
                " VALUES (:gift, :user)"
            ),
            {"gift": gift, "user": account.id},
        )


def give(engine, world, gift, state):
    """Puts the gift in `state`, in the first occasion."""
    if state == "reserved":
        add_claim(engine, gift, world.first, world.ben)
    elif state == "bought":
        add_claim(engine, gift, world.first, world.ben, bought=True)
    elif state == "group":
        add_group(engine, gift, world.first, (world.ana, "30.00"), (world.ben, None))


def set_received(engine, gift, received=True):
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE gifts SET received_at = :at WHERE id = :gift"),
            {"at": datetime.now(UTC) if received else None, "gift": gift},
        )


def gift_row(engine, gift):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT list_id, for_list_id, hidden_occasion_id, hidden_by,"
                " received_at, title FROM gifts WHERE id = :gift"
            ),
            {"gift": gift},
        ).one_or_none()


def claim_count(engine, gift):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT count(*) FROM gift_claims WHERE gift_id = :gift"),
            {"gift": gift},
        )


def upload(client, account):
    """A pending image of `account`; returns its id."""
    response = client.post("/api/images", content=png(), headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def noon_after(day: date) -> datetime:
    """When an occasion dated `day` has passed (reserving plan D8)."""
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC) + timedelta(days=1)


def first_on(client, world, day: date) -> None:
    """Makes the first occasion one created on `day`, Ana and Ben its
    invitees: its reveal date is `day`. Moving the first one there would
    keep its later date as the reveal date (D3)."""
    world.first = share(
        client,
        world.owner,
        world.list_id,
        "Soon",
        world.ana,
        world.ben,
        on=day.isoformat(),
    )


def edit(client, world, gift):
    """The owner's edit of the gift, changing nothing: 200 for any gift they
    see (`owner_visible`), the random id's 404 otherwise."""
    return client.patch(f"/api/gifts/{gift}", json={}, headers=world.owner.headers)


def claim_routes(client, account, occasion, gift):
    """The status of every claim route on the gift, as `account`."""
    return [
        reserve(client, account, occasion, gift).status_code,
        release(client, account, occasion, gift).status_code,
        mark_bought(client, account, occasion, gift).status_code,
        pledge(client, account, occasion, gift).status_code,
        leave(client, account, occasion, gift).status_code,
    ]


def claimed_ids(client, account, occasion):
    response = claims(client, account, occasion)
    assert response.status_code == 200, response.text
    return {claim["gift_id"] for claim in response.json()["gifts"]}


def gift_ids(client, world):
    detail = client.get(f"/api/lists/{world.list_id}", headers=world.owner.headers)
    return [gift["id"] for gift in detail.json()["gifts"]]


def answer(response):
    # Everything the recipient receives but the time it was sent.
    headers = {k: v for k, v in response.headers.items() if k.lower() != "date"}
    return response.status_code, response.content, headers


def recipient_answers(client, world, gift, image):
    """Every answer the recipient gets from the list's reads, and from the
    owner and occasion routes given `gift` and `image` ids."""
    calls = [
        ("GET", "/api/lists", None),
        ("GET", f"/api/lists/{world.list_id}", None),
        ("GET", f"/api/occasions/{world.first}", None),
        ("GET", f"/api/occasions/{world.second}", None),
        ("PATCH", f"/api/gifts/{gift}", {"title": "Changed"}),
        ("DELETE", f"/api/gifts/{gift}", None),
        ("GET", f"/api/images/{image}/full", None),
        ("GET", f"/api/occasions/{world.first}/images/{image}/thumb", None),
        ("GET", f"/api/occasions/{world.second}/images/{image}/full", None),
    ]
    return [
        answer(client.request(method, path, json=body, headers=world.owner.headers))
        for method, path, body in calls
    ]


# The recipient


@pytest.mark.parametrize("state", ["free", "reserved", "bought", "group"])
def test_the_recipient_sees_nothing_of_a_hidden_gift(client, world, engine, state):
    random_gift, random_image = uuid.uuid4(), uuid.uuid4()
    image = upload(client, world.ana)
    before = recipient_answers(client, world, random_gift, random_image)

    hidden = add_hidden(engine, world, world.first, world.ana, image=image)
    give(engine, world, hidden, state)

    assert recipient_answers(client, world, hidden, image) == before
    assert recipient_answers(client, world, random_gift, random_image) == before
    # The probes changed nothing.
    assert gift_row(engine, hidden).title == "Hidden gift"
    assert claim_count(engine, hidden) == (0 if state == "free" else 1)
    assert_claims_consistent(engine)


def test_hidden_gifts_count_towards_nothing(client, world, engine):
    for state in ("free", "reserved", "bought"):
        give(engine, world, add_hidden(engine, world, world.first, world.ana), state)

    summary = client.get("/api/lists", headers=world.owner.headers).json()

    assert summary[0]["gift_count"] == 3
    assert_claims_consistent(engine)


# The givers


@pytest.mark.parametrize("kind", ["self", "other"])
def test_givers_reserve_pledge_and_buy_a_hidden_gift(client, make_world, engine, kind):
    world = make_world(kind)
    # On a "for someone else" list its owner gives too (reserving plan D4).
    giver = world.ana if kind == "self" else world.owner
    shown = gift_ids(client, world)
    hidden = add_hidden(engine, world, world.first, world.ben)

    reserved = reserve(client, giver, world.first, hidden)
    assert reserved.status_code == 200, reserved.text
    assert reserved.json() == held(
        hidden, "reserved", False, participant(giver.name, True)
    )
    assert claims(client, world.ben, world.first).json()["gifts"] == [
        held(hidden, "reserved", False, participant(giver.name, False))
    ]
    assert release(client, giver, world.first, hidden).status_code == 204
    started = pledge(client, giver, world.first, hidden, "30.00")
    assert started.status_code == 200, started.text
    assert pledge(client, world.ben, world.first, hidden).status_code == 200
    assert leave(client, world.ben, world.first, hidden).status_code == 204
    bought = mark_bought(client, giver, world.first, hidden)
    assert bought.status_code == 200, bought.text
    assert bought.json() == held(
        hidden, "group", True, participant(giver.name, True, "30.00", "EUR")
    )
    # Its owners' list never shows it, whoever the list is for.
    assert gift_ids(client, world) == shown
    assert_claims_consistent(engine)


def test_an_invitee_of_another_occasion_sees_nothing_of_a_hidden_gift(
    client, world, engine
):
    hidden = add_hidden(engine, world, world.first, world.ana)
    reserve(client, world.ben, world.first, hidden)

    assert claim_routes(client, world.cleo, world.second, hidden) == [404] * 5
    assert claim_routes(client, world.cleo, world.first, hidden) == [404] * 5
    # No entry, so no "taken" either: no other occasion sees it.
    assert claims(client, world.cleo, world.second).json()["gifts"] == []
    assert claim_count(engine, hidden) == 1
    assert_claims_consistent(engine)


@pytest.mark.parametrize("kind", ["self", "other"])
def test_the_occasion_image_route_serves_a_hidden_gift_to_its_givers_only(
    client, make_world, engine, kind
):
    world = make_world(kind)
    image = upload(client, world.ana)
    add_hidden(engine, world, world.first, world.ana, image=image)
    path = f"/api/occasions/{world.first}/images/{image}/thumb"
    elsewhere = f"/api/occasions/{world.second}/images/{image}/thumb"

    assert client.get(path, headers=world.ben.headers).status_code == 200
    assert client.get(path, headers=world.ana.headers).status_code == 200
    owner = client.get(path, headers=world.owner.headers)
    # The recipient never; the owner of a "for someone else" list gives.
    assert owner.status_code == (404 if kind == "self" else 200)
    assert client.get(elsewhere, headers=world.cleo.headers).status_code == 404
    assert client.get(elsewhere, headers=world.owner.headers).status_code == 404
    # The owners' own path never serves it, nor does it to its uploader.
    for account in (world.owner, world.ana):
        response = client.get(f"/api/images/{image}/full", headers=account.headers)
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert_claims_consistent(engine)


# Received


def test_a_received_gift_leaves_every_view_and_comes_back_with_its_claim(
    client, world, engine
):
    gift = world.gifts[0]
    order = gift_ids(client, world)
    assert reserve(client, world.ana, world.first, gift).status_code == 200
    reservation = claims(client, world.ana, world.first).json()

    set_received(engine, gift)

    assert gift_ids(client, world) == order[1:]
    summary = client.get("/api/lists", headers=world.owner.headers).json()
    assert summary[0]["gift_count"] == 2
    for account in (world.owner, world.ana):
        view = client.get(f"/api/occasions/{world.first}", headers=account.headers)
        assert [shown["id"] for shown in view.json()["gifts"]] == order[1:]
    assert claims(client, world.ana, world.first).json()["gifts"] == []
    assert claim_count(engine, gift) == 1
    assert claim_routes(client, world.ana, world.first, gift) == [404] * 5
    assert claim_routes(client, world.ben, world.first, gift) == [404] * 5
    # Still the owner's, under "Received" (U3).
    assert edit(client, world, gift).status_code == 200

    set_received(engine, gift, received=False)

    assert gift_ids(client, world) == order
    assert claims(client, world.ana, world.first).json() == reservation
    assert_claims_consistent(engine)


def test_a_received_revealed_gift_stays_visible_when_its_date_moves_later(
    client, world, engine
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, "bought")
    client.app.state.clock = lambda: noon_after(day)
    assert edit(client, world, hidden).status_code == 200

    set_received(engine, hidden)
    move(client, world, world.first, (day + timedelta(days=30)).isoformat())

    assert edit(client, world, hidden).status_code == 200
    assert_claims_consistent(engine)


# The reveal


def test_a_bought_hidden_gift_is_revealed_once_the_reveal_date_has_passed(
    client, world, engine
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    bought = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, bought, "bought")
    reserved = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, reserved, "reserved")
    free = add_hidden(engine, world, world.first, world.ana)
    noon = noon_after(day)

    client.app.state.clock = lambda: noon - timedelta(seconds=1)
    early = edit(client, world, bought)
    client.app.state.clock = lambda: noon
    revealed = edit(client, world, bought)

    assert (early.status_code, early.json()) == (404, NOT_FOUND)
    assert revealed.status_code == 200, revealed.text
    assert revealed.json()["list_id"] == world.list_id
    # Never revealed unless bought.
    for gift in (reserved, free):
        assert (edit(client, world, gift).status_code) == 404
    # The list itself is unchanged: revealed gifts get their own place (U3).
    assert len(gift_ids(client, world)) == 3
    assert_claims_consistent(engine)


def test_moving_the_date_into_the_past_does_not_reveal(client, world, engine):
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, "bought")

    move(client, world, world.first, PAST)

    assert (edit(client, world, hidden).status_code) == 404
    # Moving it back and forth keeps the latest date it had.
    move(client, world, world.first, test_reservations.FUTURE)
    move(client, world, world.first, PAST)
    assert (edit(client, world, hidden).status_code) == 404
    with engine.connect() as connection:
        latest = connection.scalar(
            text("SELECT latest_date FROM occasions WHERE id = :id"),
            {"id": world.first},
        )
    assert latest.isoformat() == test_reservations.FUTURE
    assert_claims_consistent(engine)


def test_moving_the_date_later_hides_a_revealed_gift_again(client, world, engine):
    day = date.today() + timedelta(days=2)
    later = day + timedelta(days=10)
    first_on(client, world, day)
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, "bought")
    client.app.state.clock = lambda: noon_after(day)
    assert edit(client, world, hidden).status_code == 200

    move(client, world, world.first, later.isoformat())

    assert edit(client, world, hidden).status_code == 404
    client.app.state.clock = lambda: noon_after(later)
    assert edit(client, world, hidden).status_code == 200
    assert_claims_consistent(engine)


# Deletions


def hidden_in_every_state(engine, world):
    """A hidden gift of the first occasion in each state, one received."""
    gifts = {}
    for state in ("free", "reserved", "bought", "group"):
        gifts[state] = add_hidden(engine, world, world.first, world.ana, title=state)
        give(engine, world, gifts[state], state)
    gifts["received"] = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, gifts["received"], "bought")
    set_received(engine, gifts["received"])
    return gifts


def delete_first(client, world):
    response = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )
    assert response.status_code == 204, response.text


def assert_gone(client, world, engine, gifts):
    """The gifts and their claims are gone, and nothing of them is reachable
    by the other occasion's givers."""
    for gift in gifts:
        assert gift_row(engine, gift) is None
        assert claim_count(engine, gift) == 0
        assert claim_routes(client, world.cleo, world.second, gift) == [404] * 5
    assert not claimed_ids(client, world.cleo, world.second) & set(gifts)


def assert_revealed_row(engine, world, gift, received):
    row = gift_row(engine, gift)
    assert row.list_id is None
    assert str(row.for_list_id) == world.list_id
    assert row.hidden_occasion_id is None
    assert row.hidden_by is None
    assert (row.received_at is not None) is received


def test_deleting_an_occasion_before_its_reveal_date_deletes_its_hidden_gifts(
    client, world, engine
):
    gifts = hidden_in_every_state(engine, world)

    delete_first(client, world)

    assert_gone(
        client, world, engine, [gifts[s] for s in ("free", "reserved", "bought")]
    )
    assert_gone(client, world, engine, [gifts["group"]])
    assert_revealed_row(engine, world, gifts["received"], received=True)
    # Its claim stays bought, of no occasion.
    assert claim_count(engine, gifts["received"]) == 1
    assert edit(client, world, gifts["received"]).status_code == 200
    assert_claims_consistent(engine)


def test_deleting_an_occasion_after_its_reveal_date_reveals_its_bought_gifts(
    client, world, engine
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    gifts = hidden_in_every_state(engine, world)
    client.app.state.clock = lambda: noon_after(day)

    delete_first(client, world)

    assert_gone(
        client, world, engine, [gifts[s] for s in ("free", "reserved", "group")]
    )
    assert_revealed_row(engine, world, gifts["bought"], received=False)
    assert_revealed_row(engine, world, gifts["received"], received=True)
    for gift in (gifts["bought"], gifts["received"]):
        assert edit(client, world, gift).status_code == 200
        assert claim_routes(client, world.cleo, world.second, gift) == [404] * 5
    assert claimed_ids(client, world.cleo, world.second) == set()
    assert_claims_consistent(engine)


def test_a_received_gift_survives_its_occasion_whose_date_moved_later(
    client, world, engine
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, "bought")
    client.app.state.clock = lambda: noon_after(day)
    set_received(engine, hidden)
    other = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, other, "bought")
    move(client, world, world.first, (day + timedelta(days=30)).isoformat())

    delete_first(client, world)

    assert_revealed_row(engine, world, hidden, received=True)
    assert edit(client, world, hidden).status_code == 200
    # Not received, and its reveal date not passed: deleted.
    assert_gone(client, world, engine, [other])
    assert_claims_consistent(engine)


def test_moving_the_date_into_the_past_then_deleting_deletes_the_hidden_gifts(
    client, world, engine
):
    gifts = hidden_in_every_state(engine, world)
    move(client, world, world.first, PAST)

    delete_first(client, world)

    assert_gone(
        client,
        world,
        engine,
        [gifts[s] for s in ("free", "reserved", "bought", "group")],
    )
    assert_revealed_row(engine, world, gifts["received"], received=True)
    assert_claims_consistent(engine)


def unbought_hidden_claims(engine, world):
    """Hidden gifts holding unbought claims, and a revealed row with its
    bought claim of no occasion."""
    give(engine, world, add_hidden(engine, world, world.first, world.ana), "reserved")
    give(engine, world, add_hidden(engine, world, world.first, world.ana), "group")
    revealed = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, revealed, "bought")
    with engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE gifts SET hidden_occasion_id = NULL, hidden_by = NULL"
                " WHERE id = :gift"
            ),
            {"gift": revealed},
        )
        connection.execute(
            text("UPDATE gift_claims SET occasion_id = NULL WHERE gift_id = :gift"),
            {"gift": revealed},
        )


def test_deleting_the_list_with_hidden_gifts_holding_claims(
    client, world, engine, rows
):
    unbought_hidden_claims(engine, world)

    response = client.delete(f"/api/lists/{world.list_id}", headers=world.owner.headers)

    assert response.status_code == 204, response.text
    assert rows("gifts") == 0
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_deleting_the_owners_account_with_hidden_gifts_holding_claims(
    client, world, engine, rows
):
    unbought_hidden_claims(engine, world)

    response = client.delete("/api/me", headers=world.owner.headers)

    assert response.status_code == 204, response.text
    assert rows("gifts") == 0
    assert rows("gift_claims") == 0
    assert_claims_consistent(engine)


def test_deleting_the_authors_account_leaves_the_gift_with_no_author(
    client, world, engine
):
    hidden = add_hidden(engine, world, world.first, world.ana)
    give(engine, world, hidden, "reserved")

    response = client.delete("/api/me", headers=world.ana.headers)

    assert response.status_code == 204, response.text
    row = gift_row(engine, hidden)
    assert row.hidden_by is None
    assert str(row.hidden_occasion_id) == world.first
    assert claims(client, world.ben, world.first).json()["gifts"] == [
        held(hidden, "reserved", False, participant("Ben", True))
    ]
    assert_claims_consistent(engine)


def test_deleting_a_gift_drops_its_activity(client, world, engine):
    gift = world.gifts[0]
    add_group(engine, gift, world.first, (world.ana, "30.00"), (world.ben, None))

    response = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)

    assert response.status_code == 204
    assert claim_count(engine, gift) == 0
    assert claim_routes(client, world.ana, world.first, gift) == [404] * 5
    assert_claims_consistent(engine)


# The guard


def test_only_the_visibility_module_names_the_hidden_gift_columns():
    """Every other module asks `app.lists.visibility` (Conventions, D4)."""
    naming = []
    for module in sorted(APP_DIR.rglob("*.py")):
        if any(module == allowed or allowed in module.parents for allowed in ALLOWED):
            continue
        source = module.read_text(encoding="utf-8")
        naming += [
            f"{module.relative_to(APP_DIR)}: {column}"
            for column in HIDDEN_COLUMNS
            if column in source
        ]

    assert naming == []
