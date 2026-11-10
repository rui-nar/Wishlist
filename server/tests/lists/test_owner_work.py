"""The owner's gift edit and deletion do the same work whatever the gift's
activity (comments plan D12).

The statements and row counts of a `PATCH` and `DELETE /api/gifts/{id}` on a
gift with activity and on its twin with none are recorded and compared, every
id numbered by its first appearance. The world of `test_reservations.py`, and
for every state of `test_surprise.py` its world, whose G1 holds the state and
whose G2 is its twin.

The growing paths too, with the free plan's limits enforced (premium plan D7):
adding a gift and creating a list on twin worlds, one with the activity, and
putting back twin gifts, below the limit and at it.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

import pytest
import test_reservations
from sqlalchemy import event, inspect
from test_comments import posted
from test_follows import follow
from test_group_gifts import pledge
from test_hidden_gifts import added
from test_hidden_model import add_hidden, first_on, give, noon_after
from test_reservations import mark_bought, reserve
from test_surprise import OWNER, STATES, build

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

_IDS = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[0-9a-f]{32}"
)
TWIN = {"title": "Twin", "price_amount": 100, "price_currency": "EUR"}


@contextmanager
def recording(client) -> Iterator[list[tuple[str, str, int]]]:
    calls: list[tuple[str, str, int]] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        calls.append((statement, repr(parameters), cursor.rowcount))

    engine = client.app.state.engine
    event.listen(engine, "after_cursor_execute", record)
    try:
        yield calls
    finally:
        event.remove(engine, "after_cursor_execute", record)


def normalised(calls):
    seen: dict[str, str] = {}

    def name(match: re.Match[str]) -> str:
        return seen.setdefault(match[0], f"id{len(seen)}")

    return [(statement, _IDS.sub(name, params), n) for statement, params, n in calls]


def owner_request(client, owner, method, gift, body):
    """The statements of the owner's request on the gift."""
    with recording(client) as calls:
        response = client.request(
            method, f"/api/gifts/{gift}", json=body, headers=owner.headers
        )
    assert response.status_code in (200, 204), response.text
    return normalised(calls)


def twins(client, world):
    return [
        client.post(
            f"/api/lists/{world.list_id}/gifts", json=TWIN, headers=world.owner.headers
        ).json()["id"]
        for _ in range(2)
    ]


def reserved(client, world, gift):
    reserve(client, world.ana, world.first, gift)


def bought(client, world, gift):
    reserve(client, world.ana, world.first, gift)
    mark_bought(client, world.ana, world.first, gift)


def group_with_pledges(client, world, gift):
    for member, amount in ((world.ana, "30.00"), (world.ben, None)):
        assert pledge(client, member, world.first, gift, amount).status_code == 200


def commented_and_followed(client, world, gift):
    posted(client, world.ana, world.first, gift)
    follow(client, world.ben, world.first, gift)


def taken_elsewhere(client, world, gift):
    reserve(client, world.cleo, world.second, gift)


ACTIVITIES = {
    "reserved": reserved,
    "bought": bought,
    "group with pledges": group_with_pledges,
    "commented and followed": commented_and_followed,
    "taken elsewhere": taken_elsewhere,
}
REQUESTS = [("PATCH", {"title": "Renamed"}), ("DELETE", None)]


def enforce(client, billing_on, **limits):
    """The free plan's limits enforced on this app (premium plan Conventions)."""
    state = client.app.state
    state.settings = state.settings.model_copy(update=billing_on | limits)


def hidden_gift_added(client, world, gift):
    added(client, world.ana, world.first)


GROWTH_ACTIVITIES = ACTIVITIES | {"hidden gift added": hidden_gift_added}


def frozen(client, *owners):
    """The clock stopped: premium is read with the time as a parameter. Each
    session's use is recorded once, before the comparison."""
    now = datetime.now(UTC)
    client.app.state.clock = lambda: now
    for owner in owners:
        client.get("/api/lists", headers=owner.headers)


def growth(client, owner, method, path, body):
    """The answer's status and the statements of an owner's growing request."""
    with recording(client) as calls:
        response = client.request(method, path, json=body, headers=owner.headers)
    return response.status_code, normalised(calls)


def advisory_locks(calls):
    return [call for call in calls if "pg_advisory_xact_lock" in call[0]]


@pytest.mark.parametrize("activity", GROWTH_ACTIVITIES)
@pytest.mark.parametrize(("limit", "expected"), [(20, 201), (3, 402)])
def test_adding_a_gift_does_the_same_work_whatever_the_activity(
    client, make_world, billing_on, activity, limit, expected
):
    active, quiet = make_world(), make_world()
    GROWTH_ACTIVITIES[activity](client, active, active.gifts[0])
    enforce(client, billing_on, free_max_gifts_per_list=limit)
    frozen(client, active.owner, quiet.owner)

    status, statements = growth(
        client, active.owner, "POST", f"/api/lists/{active.list_id}/gifts", TWIN
    )

    assert status == expected
    assert advisory_locks(statements)
    assert (status, statements) == growth(
        client, quiet.owner, "POST", f"/api/lists/{quiet.list_id}/gifts", TWIN
    )


@pytest.mark.parametrize("activity", GROWTH_ACTIVITIES)
@pytest.mark.parametrize(("limit", "expected"), [(5, 201), (1, 402)])
def test_creating_a_list_does_the_same_work_whatever_the_activity(
    client, make_world, billing_on, activity, limit, expected
):
    active, quiet = make_world(), make_world()
    GROWTH_ACTIVITIES[activity](client, active, active.gifts[0])
    enforce(client, billing_on, free_max_lists=limit)
    frozen(client, active.owner, quiet.owner)
    body = {"title": "Next", "recipient_kind": "self"}

    status, statements = growth(client, active.owner, "POST", "/api/lists", body)

    assert status == expected
    assert advisory_locks(statements)
    assert (status, statements) == growth(
        client, quiet.owner, "POST", "/api/lists", body
    )


@pytest.mark.parametrize("activity", GROWTH_ACTIVITIES)
@pytest.mark.parametrize(("limit", "expected"), [(20, 204), (3, 402)])
def test_putting_back_does_the_same_work_whatever_the_activity(
    client, world, billing_on, activity, limit, expected
):
    first, second = twins(client, world)
    GROWTH_ACTIVITIES[activity](client, world, first)
    for gift in (first, second):
        marked = client.post(f"/api/gifts/{gift}/received", headers=world.owner.headers)
        assert marked.status_code == 204, marked.text
    enforce(client, billing_on, free_max_gifts_per_list=limit)
    frozen(client, world.owner)

    status, statements = growth(
        client, world.owner, "DELETE", f"/api/gifts/{first}/received", None
    )

    assert status == expected
    assert advisory_locks(statements)
    assert (status, statements) == growth(
        client, world.owner, "DELETE", f"/api/gifts/{second}/received", None
    )


@pytest.mark.parametrize("activity", ACTIVITIES)
@pytest.mark.parametrize(("method", "body"), REQUESTS)
def test_the_owners_request_does_the_same_work_whatever_the_activity(
    client, world, activity, method, body
):
    first, second = twins(client, world)
    ACTIVITIES[activity](client, world, first)

    assert owner_request(client, world.owner, method, first, body) == owner_request(
        client, world.owner, method, second, body
    )


@pytest.mark.parametrize("state", STATES)
@pytest.mark.parametrize(("method", "body"), REQUESTS)
def test_the_owners_request_does_the_same_work_in_every_state(
    client, make_account, engine, state, method, body
):
    built = build(client, make_account, engine, state)
    owner = built.accounts[OWNER]

    assert owner_request(client, owner, method, built.ids["G1"], body) == owner_request(
        client, owner, method, built.ids["G2"], body
    )


@pytest.mark.parametrize(("method", "body"), REQUESTS)
def test_a_revealed_gifts_request_does_the_same_work_with_or_without_a_thread(
    client, world, engine, method, body
):
    day = date.today() + timedelta(days=2)
    first_on(client, world, day)
    first, second = (
        add_hidden(engine, world, world.first, world.ana, "Twin") for _ in range(2)
    )
    for gift in (first, second):
        give(engine, world, gift, "bought")
    commented_and_followed(client, world, first)
    client.app.state.clock = lambda: noon_after(day)
    # The clock's jump records the session's use once, before the comparison.
    client.get("/api/lists", headers=world.owner.headers)

    assert owner_request(client, world.owner, method, first, body) == owner_request(
        client, world.owner, method, second, body
    )


@pytest.mark.parametrize("holds_things", [False, True])
def test_a_removal_writes_exactly_one_of_each_event(client, world, rows, holds_things):
    if holds_things:
        group_with_pledges(client, world, world.gifts[0])
        added(client, world.ana, world.first)
        added(client, world.ana, world.first, "Pledged")

    response = client.delete(
        f"/api/occasions/{world.first}/members/{world.ana.id}",
        headers=world.owner.headers,
    )

    assert response.status_code == 204, response.text
    assert rows("notification_events", "kind", "participants_left") == 1
    assert rows("notification_events", "kind", "gifts_removed") == 1
    assert rows("notification_events") == 2


ACTIVITY_TABLES = [
    "gift_claims",
    "claim_participants",
    "comments",
    "gift_follows",
    "notification_events",
    "notifications",
    "email_digests",
]


def test_no_activity_table_has_a_foreign_key_to_gifts(engine):
    inspector = inspect(engine)
    referring = [
        (table, key["name"])
        for table in ACTIVITY_TABLES
        for key in inspector.get_foreign_keys(table)
        if key["referred_table"] == "gifts"
    ]

    assert referring == []
