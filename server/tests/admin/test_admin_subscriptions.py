"""The Stripe subscription apart from a grant by hand (owner, 2026-11-11;
review R4-2): each row of the list and the detail say what Stripe does for the
account, its status, start and renewal or end date, next to the admin's grant.
Neither hides the other, and `plan` stays the effective one.
"""

import re
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from sqlalchemy import event, text

from app.billing.entitlements import GRACE


def iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def add_stripe(
    engine,
    user_id,
    status,
    period_end,
    started_at,
    cancel=False,
    created_at=None,
):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO entitlements (id, user_id, source, external_id, status,"
                " period_end, cancel_at_period_end, started_at, read_at, created_at)"
                " VALUES (:id, :user, 'stripe', :external, :status, :end, :cancel,"
                " :start, :start, coalesce(:created, now()))"
            ),
            {
                "id": uuid.uuid4(),
                "user": user_id,
                "external": f"sub_{uuid.uuid4().hex}",
                "status": status,
                "end": period_end,
                "cancel": cancel,
                "start": started_at,
                "created": created_at,
            },
        )


def users(client, admin):
    response = client.get("/api/admin/users", headers=admin.headers)
    assert response.status_code == 200, response.text
    return response.json()["users"]


def views(client, admin, user_id):
    """The user's row in the list and their detail."""
    [row] = [row for row in users(client, admin) if row["id"] == str(user_id)]
    response = client.get(f"/api/admin/users/{user_id}", headers=admin.headers)
    assert response.status_code == 200, response.text
    return row, response.json()


def grant(client, admin, user_id, **body):
    response = client.post(
        f"/api/admin/users/{user_id}/premium", json=body, headers=admin.headers
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def target(make_account):
    return make_account()


def test_never_subscribed_is_null_in_the_list_and_the_detail(client, admin, target):
    for view in views(client, admin, target.id):
        assert view["subscription"] is None
        assert view["manual_grant"] is None
        assert view["plan"] == {"plan": "free", "source": None, "until": None}


# (stored status, cancel_at_period_end, days to period_end) -> what is shown,
# and whether the stored date is shown.
CASES = {
    "active renews": ("active", False, 30, "active", True, "premium"),
    "canceling ends": ("active", True, 30, "canceling", True, "premium"),
    "past_due renews": ("past_due", False, 30, "past_due", True, "premium"),
    # A cancellation outweighs a failing card, as on `GET /api/billing`.
    "past_due canceling": ("past_due", True, 30, "canceling", True, "premium"),
    # Stripe's period end is not when they end (review R5-1).
    "incomplete": ("incomplete", False, 30, "incomplete", False, "free"),
    "ended": ("ended", False, -30, "ended", False, "free"),
    "ended early": ("ended", False, 300, "ended", False, "free"),
    # Its events were lost: it grants nothing, but Stripe may still bill it,
    # so it reads as no news since its stored date (review R5-2).
    "active past its grace": ("active", False, -30, "no_news", True, "free"),
    "past_due past its grace": ("past_due", False, -30, "no_news", True, "free"),
    "canceling past its grace": ("active", True, -30, "no_news", True, "free"),
}


@pytest.mark.parametrize(
    ("stored", "cancel", "days", "shown", "dated", "plan"),
    CASES.values(),
    ids=CASES.keys(),
)
def test_the_subscription_says_its_status_start_and_date(
    client, admin, target, engine, now, stored, cancel, days, shown, dated, plan
):
    started = now - timedelta(days=100)
    end = now + timedelta(days=days)
    add_stripe(engine, target.id, stored, end, started, cancel)

    for view in views(client, admin, target.id):
        assert view["subscription"] == {
            "status": shown,
            "started_at": iso(started),
            "period_end": iso(end) if dated else None,
        }
        assert view["manual_grant"] is None
        assert view["plan"]["plan"] == plan


def test_a_granting_row_without_a_date_reads_no_news(
    client, admin, target, engine, now
):
    add_stripe(engine, target.id, "active", None, now - timedelta(days=10))

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "no_news"
        assert view["subscription"]["period_end"] is None


def test_a_subscription_within_its_grace_is_still_shown_as_stored(
    client, admin, target, engine, now
):
    end = now - GRACE + timedelta(hours=1)
    add_stripe(engine, target.id, "past_due", end, now - timedelta(days=40))

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "past_due"
        assert view["plan"]["plan"] == "premium"


@pytest.mark.parametrize("stripe", ["active", "past_due"])
def test_a_grant_outlasting_the_subscription_hides_neither(
    client, admin, target, engine, now, stripe
):
    started = now - timedelta(days=10)
    stripe_end = now + timedelta(days=20)
    add_stripe(engine, target.id, stripe, stripe_end, started)

    granted = grant(client, admin, target.id, period_end="2027-06-01")

    for view in (granted, *views(client, admin, target.id)):
        assert view["plan"] == {
            "plan": "premium",
            "source": "manual",
            "until": "2027-06-01T12:00:00Z",
        }
        assert view["manual_grant"] == {"period_end": "2027-06-01T12:00:00Z"}
        assert view["subscription"] == {
            "status": stripe,
            "started_at": iso(started),
            "period_end": iso(stripe_end),
        }


def test_a_grant_shorter_than_the_subscription_hides_neither(
    client, admin, target, engine, now
):
    started = now - timedelta(days=10)
    stripe_end = now + timedelta(days=200)
    add_stripe(engine, target.id, "active", stripe_end, started, cancel=True)

    grant(client, admin, target.id, period_end="2026-12-01")

    for view in views(client, admin, target.id):
        assert view["plan"]["source"] == "stripe"
        assert view["manual_grant"] == {"period_end": "2026-12-01T12:00:00Z"}
        assert view["subscription"]["status"] == "canceling"


def test_ending_the_grant_leaves_the_subscription(client, admin, target, engine, now):
    add_stripe(engine, target.id, "active", now + timedelta(days=20), now)
    grant(client, admin, target.id)

    response = client.delete(
        f"/api/admin/users/{target.id}/premium", headers=admin.headers
    )

    assert response.status_code == 200, response.text
    for view in (response.json(), *views(client, admin, target.id)):
        assert view["manual_grant"] is None
        assert view["subscription"]["status"] == "active"


# A re-subscription: two Stripe rows for one account.


@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_the_subscription_in_force_wins_over_a_later_ended_one(
    client, admin, target, engine, now, old_first
):
    rows = [
        ("active", now + timedelta(days=10), now - timedelta(days=200)),
        ("ended", now - timedelta(days=5), now - timedelta(days=20)),
    ]
    for status, end, started in rows if old_first else reversed(rows):
        add_stripe(engine, target.id, status, end, started)

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "active"
        assert view["subscription"]["started_at"] == iso(now - timedelta(days=200))


@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_with_none_in_force_the_latest_started_is_shown(
    client, admin, target, engine, now, old_first
):
    rows = [
        ("ended", now - timedelta(days=100), now - timedelta(days=400)),
        ("incomplete", now + timedelta(days=1), now - timedelta(days=1)),
    ]
    for status, end, started in rows if old_first else reversed(rows):
        add_stripe(engine, target.id, status, end, started)

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "incomplete"


@pytest.mark.parametrize("old_first", [True, False], ids=["old-first", "new-first"])
def test_with_two_in_force_the_longest_is_shown_as_the_plan_shows_it(
    client, admin, target, engine, now, old_first
):
    rows = [
        ("past_due", now + timedelta(days=200), now - timedelta(days=300)),
        ("active", now + timedelta(days=20), now - timedelta(days=10)),
    ]
    for status, end, started in rows if old_first else reversed(rows):
        add_stripe(engine, target.id, status, end, started)

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "past_due"
        assert view["subscription"]["period_end"] == view["plan"]["until"]


def test_the_same_start_falls_back_to_the_latest_created(
    client, admin, target, engine, now
):
    started = now - timedelta(days=50)
    add_stripe(
        engine,
        target.id,
        "ended",
        now - timedelta(days=20),
        started,
        created_at=now - timedelta(days=1),
    )
    add_stripe(
        engine,
        target.id,
        "incomplete",
        now + timedelta(days=5),
        started,
        created_at=now - timedelta(days=2),
    )

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "ended"


# Constant queries per page (D5: 50 a page).


@contextmanager
def recording(client):
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = client.app.state.engine
    event.listen(engine, "after_cursor_execute", record)
    try:
        yield statements
    finally:
        event.remove(engine, "after_cursor_execute", record)


# The Stripe and Apple subscriptions' and the grant's reads, which filter on
# the source: three per page, whatever its size. The plan's reads (`summary`)
# do not, or exclude one with `!=`.
_BY_SOURCE = re.compile(r"entitlements\.source = ")


def by_source_reads(client, admin) -> int:
    with recording(client) as statements:
        users(client, admin)
    return sum(1 for statement in statements if _BY_SOURCE.search(statement))


def test_the_subscriptions_and_grants_are_read_once_per_page(
    client, admin, make_account, engine, now
):
    def subscribed():
        account = make_account()
        add_stripe(engine, account.id, "active", now + timedelta(days=9), now)
        grant(client, admin, account.id)

    subscribed()
    few = by_source_reads(client, admin)
    for _ in range(5):
        subscribed()

    assert by_source_reads(client, admin) == few == 3
