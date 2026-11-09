"""The owner's gift edit and deletion do the same work whatever the gift's
activity (comments plan D12).

The statements and row counts of a `PATCH` and `DELETE /api/gifts/{id}` on a
gift with activity and on its twin with none are recorded and compared, every
id numbered by its first appearance. The world of `test_reservations.py`.
"""

import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta

import pytest
import test_reservations
from sqlalchemy import event, inspect
from test_comments import posted
from test_follows import follow
from test_group_gifts import pledge
from test_hidden_gifts import added
from test_hidden_model import add_hidden, first_on, give, noon_after
from test_reservations import mark_bought, reserve

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


def owner_request(client, world, method, gift, body):
    """The statements of the owner's request on the gift."""
    with recording(client) as calls:
        response = client.request(
            method, f"/api/gifts/{gift}", json=body, headers=world.owner.headers
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


@pytest.mark.parametrize("activity", ACTIVITIES)
@pytest.mark.parametrize(("method", "body"), REQUESTS)
def test_the_owners_request_does_the_same_work_whatever_the_activity(
    client, world, activity, method, body
):
    first, second = twins(client, world)
    ACTIVITIES[activity](client, world, first)

    assert owner_request(client, world, method, first, body) == owner_request(
        client, world, method, second, body
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

    assert owner_request(client, world, method, first, body) == owner_request(
        client, world, method, second, body
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
