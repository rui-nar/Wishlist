"""The free plan's limits (premium plan D4-D9).

The world of `test_reservations.py`: one list of three gifts, Ana and Ben
invitees of its first occasion, Cleo of its second. Limits are switched on by
replacing the app's settings (Conventions), and purchases recorded through
`entitlements.apply`, as a provider's translator records them.
"""

import ast
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
import test_reservations
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_comments import posted
from test_group_gifts import pledge
from test_hidden_gifts import added
from test_hidden_model import add_hidden, gift_row, upload
from test_owner_work import advisory_locks, enforce, normalised, recording
from test_received import (
    NOT_REVEALED,
    detail,
    gift_count,
    ids,
    keep,
    mark_received,
    put_back,
    revealed_gift,
)
from test_reservations import NOT_FOUND, reserve, share

from app.billing.entitlements import GRACE, EntitlementFacts, apply

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

APP_DIR = Path(__file__).resolve().parents[2] / "app"


def refusal(resource, limit):
    return {
        "detail": "The free plan's limit is reached",
        "code": "plan_limit",
        "resource": resource,
        "limit": limit,
    }


def new_list(client, account, title="Another"):
    return client.post(
        "/api/lists",
        json={"title": title, "recipient_kind": "self"},
        headers=account.headers,
    )


def new_gift(client, account, list_id, title="Next"):
    return client.post(
        f"/api/lists/{list_id}/gifts", json={"title": title}, headers=account.headers
    )


def lists_of(client, account):
    return client.get("/api/lists", headers=account.headers).json()


def give_premium(engine, account, period_end=None, status="active"):
    """A purchase by `account`, in force for a month unless `period_end`."""
    now = datetime.now(UTC)
    with Session(engine) as db, db.begin():
        apply(
            db,
            EntitlementFacts(
                source="stripe",
                external_id=uuid.uuid4().hex,
                user_id=uuid.UUID(account.id),
                status=status,
                period_end=period_end or now + timedelta(days=30),
                cancel_at_period_end=False,
                started_at=now,
            ),
            now,
        )


def add_owner(engine, list_id, account):
    # No route adds a co-owner (as `test_surprise.py` inserts Cora's row).
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": list_id, "user": account.id},
        )


# The limit and the next request


def test_a_free_user_stops_at_the_list_limit(client, make_account, billing_on):
    enforce(client, billing_on, free_max_lists=2)
    ada = make_account()

    assert new_list(client, ada).status_code == 201
    assert new_list(client, ada).status_code == 201
    refused = new_list(client, ada, "One too many")

    assert (refused.status_code, refused.json()) == (402, refusal("lists", 2))
    assert [found["title"] for found in lists_of(client, ada)] == ["Another"] * 2


def test_a_free_list_stops_at_the_gift_limit(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=4)

    assert new_gift(client, world.owner, world.list_id).status_code == 201
    refused = new_gift(client, world.owner, world.list_id, "One too many")

    assert (refused.status_code, refused.json()) == (402, refusal("gifts", 4))
    assert gift_count(client, world) == 4


def test_the_defaults_are_one_list_and_twenty_gifts(client, make_account, billing_on):
    enforce(client, billing_on)
    ada = make_account()
    list_id = new_list(client, ada).json()["id"]

    for n in range(20):
        assert new_gift(client, ada, list_id, f"Gift {n}").status_code == 201

    assert new_gift(client, ada, list_id).json() == refusal("gifts", 20)
    assert new_list(client, ada).json() == refusal("lists", 1)


def test_a_refused_request_writes_nothing(client, world, billing_on, rows):
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)
    gifts, lists = rows("gifts"), rows("lists")

    assert new_gift(client, world.owner, world.list_id).status_code == 402
    assert new_list(client, world.owner).status_code == 402

    assert (rows("gifts"), rows("lists")) == (gifts, lists)


def test_another_persons_list_is_still_a_404_at_the_limit(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=3)

    refused = new_gift(client, world.ana, world.list_id)

    assert (refused.status_code, refused.json()) == (404, NOT_FOUND)


# What counts


def test_received_hidden_and_revealed_gifts_do_not_count(
    client, world, billing_on, engine
):
    added(client, world.ana, world.first)
    assert mark_received(client, world.owner, world.gifts[0]).status_code == 204
    revealed_gift(client, world, engine)
    enforce(client, billing_on, free_max_gifts_per_list=4)

    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_gift(client, world.owner, world.list_id).status_code == 402
    assert gift_count(client, world) == 4


def test_marking_received_frees_a_place(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=3)
    assert new_gift(client, world.owner, world.list_id).status_code == 402

    assert mark_received(client, world.owner, world.gifts[0]).status_code == 204

    assert new_gift(client, world.owner, world.list_id).status_code == 201


def test_deleting_a_gift_frees_a_place(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=3)

    client.delete(f"/api/gifts/{world.gifts[0]}", headers=world.owner.headers)

    assert new_gift(client, world.owner, world.list_id).status_code == 201


# Put back


def test_put_back_at_the_limit_is_refused_and_the_gift_stays_received(
    client, world, billing_on
):
    gift = world.gifts[0]
    assert mark_received(client, world.owner, gift).status_code == 204
    assert new_gift(client, world.owner, world.list_id).status_code == 201
    enforce(client, billing_on, free_max_gifts_per_list=3)

    refused = put_back(client, world.owner, gift)

    assert (refused.status_code, refused.json()) == (402, refusal("gifts", 3))
    shown = detail(client, world)
    assert gift in ids(shown["received"])
    assert gift not in ids(shown["gifts"])
    assert gift_count(client, world) == 3


def test_put_back_below_the_limit_returns_the_gift(client, world, billing_on):
    gift = world.gifts[0]
    assert mark_received(client, world.owner, gift).status_code == 204
    enforce(client, billing_on, free_max_gifts_per_list=3)

    assert put_back(client, world.owner, gift).status_code == 204

    assert gift in ids(detail(client, world)["gifts"])


def test_putting_back_a_gift_on_the_list_at_the_limit_is_a_no_op(
    client, world, billing_on
):
    enforce(client, billing_on, free_max_gifts_per_list=3)

    response = put_back(client, world.owner, world.gifts[0])

    assert response.status_code == 204
    assert gift_count(client, world) == 3


def test_putting_back_a_revealed_gift_is_never_refused(
    client, world, billing_on, engine
):
    gift = revealed_gift(client, world, engine)
    assert mark_received(client, world.owner, gift).status_code == 204
    enforce(client, billing_on, free_max_gifts_per_list=3)

    response = put_back(client, world.owner, gift)

    assert response.status_code == 204
    assert gift in ids(detail(client, world)["revealed"])
    assert gift_count(client, world) == 3


# Keep


def test_keep_at_the_limit_is_refused_and_the_gift_stays_revealed(
    client, world, billing_on, engine
):
    gift = revealed_gift(client, world, engine)
    enforce(client, billing_on, free_max_gifts_per_list=3)

    refused = keep(client, world.owner, gift)

    assert (refused.status_code, refused.json()) == (402, refusal("gifts", 3))
    assert ids(detail(client, world)["revealed"]) == [gift]
    assert gift_row(engine, gift) is not None


def test_keep_under_the_limit_makes_a_new_gift(client, world, billing_on, engine):
    gift = revealed_gift(client, world, engine)
    enforce(client, billing_on, free_max_gifts_per_list=4)

    kept = keep(client, world.owner, gift)

    assert kept.status_code == 200, kept.text
    assert kept.json()["id"] != gift
    assert kept.json()["id"] in ids(detail(client, world)["gifts"])
    assert gift_row(engine, gift) is None


def test_keep_on_an_unrevealed_gift_at_the_limit_is_the_random_ids_404(
    client, world, billing_on, engine
):
    unrevealed = add_hidden(engine, world, world.first, world.ana)
    enforce(client, billing_on, free_max_gifts_per_list=3)

    response = keep(client, world.owner, unrevealed)
    random = keep(client, world.owner, uuid.uuid4())

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert (response.status_code, response.json()) == (
        random.status_code,
        random.json(),
    )


def test_keep_on_a_gift_on_the_list_at_the_limit_is_not_revealed(
    client, world, billing_on
):
    enforce(client, billing_on, free_max_gifts_per_list=3)

    response = keep(client, world.owner, world.gifts[0])

    assert (response.status_code, response.json()) == (409, NOT_REVEALED)


def test_keep_of_a_received_gift_whose_date_moved_later_answers_not_revealed(
    client, world, billing_on, engine
):
    # An owner sees it received, not revealed: the limit is never reached for
    # it, as for any gift not revealed.
    gift = revealed_gift(client, world, engine)
    assert mark_received(client, world.owner, gift).status_code == 204
    later = (date.today() + timedelta(days=40)).isoformat()
    moved = client.patch(
        f"/api/occasions/{world.first}",
        json={"date": later},
        headers=world.owner.headers,
    )
    assert moved.status_code == 200, moved.text
    enforce(client, billing_on, free_max_gifts_per_list=3)

    response = keep(client, world.owner, gift)

    assert (response.status_code, response.json()) == (409, NOT_REVEALED)


# An over-limit list


def test_an_over_limit_list_is_readable_shareable_and_editable(
    client, world, billing_on
):
    owner = world.owner
    enforce(client, billing_on, free_max_gifts_per_list=1, free_max_lists=0)
    headers = owner.headers
    assert new_gift(client, owner, world.list_id).status_code == 402
    assert new_list(client, owner).status_code == 402

    assert client.get("/api/lists", headers=headers).status_code == 200
    assert client.get(f"/api/lists/{world.list_id}", headers=headers).status_code == 200
    renamed = client.patch(
        f"/api/lists/{world.list_id}", json={"title": "New"}, headers=headers
    )
    assert renamed.status_code == 200, renamed.text
    gift = world.gifts[0]
    edited = client.patch(f"/api/gifts/{gift}", json={"title": "New"}, headers=headers)
    assert edited.status_code == 200, edited.text
    image = client.patch(
        f"/api/gifts/{gift}", json={"image_id": upload(client, owner)}, headers=headers
    )
    assert image.status_code == 200, image.text
    assert client.get(image.json()["image"]["url"], headers=headers).status_code == 200
    occasion = share(client, owner, world.list_id, "New occasion", world.ben)
    assert (
        client.get(f"/api/occasions/{occasion}", headers=world.ben.headers).status_code
        == 200
    )
    assert (
        client.get(
            f"/api/occasions/{world.first}", headers=world.ana.headers
        ).status_code
        == 200
    )
    assert mark_received(client, owner, world.gifts[1]).status_code == 204
    deleted = client.delete(f"/api/gifts/{gift}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    assert (
        client.delete(f"/api/lists/{world.list_id}", headers=headers).status_code == 204
    )


# Premium


def test_a_premium_owner_has_no_limit(client, world, billing_on, engine):
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)
    give_premium(engine, world.owner)

    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_list(client, world.owner).status_code == 201
    assert new_list(client, world.owner).status_code == 201
    assert gift_count(client, world) == 4


def test_premium_at_a_zero_limit_still_grows(client, make_account, billing_on, engine):
    # The list limit reads the acting user first, not only their lists.
    enforce(client, billing_on, free_max_lists=0)
    ada = make_account()
    give_premium(engine, ada)

    assert new_list(client, ada).status_code == 201


def test_premium_ended_by_the_clock_deletes_nothing_and_stops_growth(
    client, world, billing_on, engine, caplog
):
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)
    end = datetime.now(UTC) + timedelta(days=1)
    give_premium(engine, world.owner, end)
    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_list(client, world.owner, "Second").status_code == 201

    client.app.state.clock = lambda: end + GRACE - timedelta(hours=1)
    assert new_gift(client, world.owner, world.list_id).status_code == 201

    client.app.state.clock = lambda: end + GRACE + timedelta(hours=1)
    with caplog.at_level(logging.WARNING, logger="app.billing.entitlements"):
        refused = new_gift(client, world.owner, world.list_id)
        list_refused = new_list(client, world.owner, "Third")

    assert (refused.status_code, refused.json()) == (402, refusal("gifts", 3))
    assert (list_refused.status_code, list_refused.json()) == (
        402,
        refusal("lists", 1),
    )
    assert caplog.text.count("entitlement past its grace") == 2
    # Nothing went away.
    assert gift_count(client, world) == 5
    assert len(lists_of(client, world.owner)) == 2


# Co-owners


def test_a_premium_co_owner_covers_the_list_for_both(
    client, world, billing_on, engine, make_account
):
    cora = make_account("Cora")
    add_owner(engine, world.list_id, cora)
    give_premium(engine, cora)
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)

    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_gift(client, cora, world.list_id).status_code == 201
    assert gift_count(client, world) == 5


def test_a_covered_list_counts_for_no_free_co_owner(
    client, world, billing_on, engine, make_account
):
    cora = make_account("Cora")
    add_owner(engine, world.list_id, cora)
    give_premium(engine, cora)
    enforce(client, billing_on, free_max_lists=1)

    assert new_list(client, world.owner, "Her own").status_code == 201
    # The covered list counted for nothing; her own list does.
    assert new_list(client, world.owner, "One more").json() == refusal("lists", 1)


def test_co_owners_without_premium_count_the_list_for_each(
    client, world, billing_on, engine, make_account
):
    cora = make_account("Cora")
    add_owner(engine, world.list_id, cora)
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)

    assert new_list(client, cora).json() == refusal("lists", 1)
    assert new_gift(client, cora, world.list_id).json() == refusal("gifts", 3)


def test_a_refusal_logs_each_owners_lapse(
    client, world, billing_on, engine, make_account, caplog
):
    cora = make_account("Cora")
    add_owner(engine, world.list_id, cora)
    give_premium(engine, cora, datetime.now(UTC) - timedelta(days=10))
    enforce(client, billing_on, free_max_gifts_per_list=3)

    with caplog.at_level(logging.WARNING, logger="app.billing.entitlements"):
        response = new_gift(client, world.owner, world.list_id)

    assert response.status_code == 402
    assert caplog.text.count("entitlement past its grace") == 1


# Off, and the settings


@pytest.fixture
def growth_requests(client, world, engine):
    """Every growing path once, with a received and a revealed gift to work on."""
    gift = revealed_gift(client, world, engine)
    received = world.gifts[0]
    assert mark_received(client, world.owner, received).status_code == 204

    def run():
        results = []
        with recording(client) as calls:
            results.append(new_list(client, world.owner).status_code)
            results.append(new_gift(client, world.owner, world.list_id).status_code)
            results.append(put_back(client, world.owner, received).status_code)
            results.append(keep(client, world.owner, gift).status_code)
        return results, normalised(calls)

    return run


def enforcement_off(billing_on):
    return billing_on | {"billing_enforce_limits": False}


def stripe_absent(billing_on):
    return {"billing_enforce_limits": True}


@pytest.mark.parametrize("settings", [enforcement_off, stripe_absent])
def test_without_enforcement_nothing_is_limited_or_locked(
    client, billing_on, growth_requests, settings
):
    state = client.app.state
    state.settings = state.settings.model_copy(
        update=settings(billing_on)
        | {"free_max_lists": 0, "free_max_gifts_per_list": 0}
    )

    results, statements = growth_requests()

    assert results == [201, 201, 204, 200]
    assert advisory_locks(statements) == []
    assert not [call for call in statements if "count(" in call[0]]


def test_with_enforcement_every_growing_path_takes_the_lock(
    client, billing_on, growth_requests
):
    enforce(client, billing_on, free_max_lists=5, free_max_gifts_per_list=20)

    results, statements = growth_requests()

    assert results == [201, 201, 204, 200]
    assert len(advisory_locks(statements)) == 4


def test_the_settings_change_the_limits(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)
    assert new_gift(client, world.owner, world.list_id).json() == refusal("gifts", 3)
    assert new_list(client, world.owner).json() == refusal("lists", 1)

    enforce(client, billing_on, free_max_gifts_per_list=4, free_max_lists=2)

    assert new_gift(client, world.owner, world.list_id).status_code == 201
    assert new_list(client, world.owner).status_code == 201
    assert new_gift(client, world.owner, world.list_id).json() == refusal("gifts", 4)


# Givers are never limited


def give_everything(client, giver, world, occasion):
    """Every invitee action: reserve, pledge, comment, add a hidden gift."""
    reserved, pledged, commented = world.gifts
    assert reserve(client, giver, occasion, reserved).status_code == 200
    assert pledge(client, giver, occasion, pledged).status_code == 200
    posted(client, giver, occasion, commented)
    added(client, giver, occasion)


def test_an_invitee_at_their_own_limit_can_still_give(
    client, world, billing_on, make_account
):
    assert new_list(client, world.ana).status_code == 201
    enforce(client, billing_on, free_max_lists=1, free_max_gifts_per_list=3)

    joined = share(client, world.owner, world.list_id, "Joining", world.ana)

    give_everything(client, world.ana, world, joined)


def test_a_for_someone_else_owner_at_the_limit_can_still_give(
    client, make_world, billing_on
):
    world = make_world("other")
    enforce(client, billing_on, free_max_lists=1, free_max_gifts_per_list=3)
    assert new_gift(client, world.owner, world.list_id).status_code == 402

    give_everything(client, world.owner, world, world.first)


# The limits read nothing of invitee activity (D7)


def test_the_limits_module_imports_no_activity_model():
    source = (APP_DIR / "billing" / "limits.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
            imported |= {f"{node.module}.{alias.name}" for alias in node.names}

    forbidden = (
        "app.reserving",
        "app.comments",
        "app.notifications",
        "app.hidden_gifts",
    )
    assert [module for module in imported if module.startswith(forbidden)] == []
    for name in ("GiftClaim", "ClaimParticipant", "Comment", "Notification"):
        assert name not in source
