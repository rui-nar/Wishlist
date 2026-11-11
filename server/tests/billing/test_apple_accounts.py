"""An Apple subscription where accounts are seen and deleted (Apple IAP plan
D9): the admin row's own block, shaped like Stripe's, and the line logged
when a deletion goes ahead past one that may still charge."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.entitlements import GRACE
from app.billing.models import Entitlement

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
STARTED = NOW - timedelta(days=100)
ORIGINAL = "2000000001"


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def add(engine, user_id, source="apple", **fields):
    values = {
        "user_id": user_id,
        "source": source,
        "external_id": f"{uuid.uuid4().int % 10**12}",
        "status": "active",
        "period_end": NOW + timedelta(days=100),
        "cancel_at_period_end": False,
        "started_at": STARTED,
        "read_at": NOW,
    } | fields
    with Session(engine) as db, db.begin():
        db.add(Entitlement(**values))


@pytest.fixture
def admin(make_account):
    return make_account()


@pytest.fixture
def client(make_client, admin):
    client = make_client(admin_user_ids=str(admin.id))
    client.app.state.clock = lambda: NOW
    return client


def views(client, admin, user_id):
    """The user's row in the list and their detail."""
    listed = client.get("/api/admin/users", headers=admin.headers)
    assert listed.status_code == 200, listed.text
    [row] = [row for row in listed.json()["users"] if row["id"] == str(user_id)]
    detail = client.get(f"/api/admin/users/{user_id}", headers=admin.headers)
    assert detail.status_code == 200, detail.text
    return row, detail.json()


def test_no_apple_subscription_is_null(client, admin, make_account):
    target = make_account()
    for view in views(client, admin, target.id):
        assert view["apple_subscription"] is None


# (stored status, cancel_at_period_end, days to period_end) -> (shown status,
# the stored date shown).
CASES = {
    "active renews": ("active", False, 30, "active", True),
    "canceling ends": ("active", True, 30, "canceling", True),
    "grace period": ("past_due", False, 10, "past_due", True),
    "billing retry, Apple may charge": ("ended", False, -5, "past_due", False),
    "expired": ("ended", True, -5, "ended", False),
    "no news past the grace": ("active", False, -4, "no_news", True),
}


@pytest.mark.parametrize("case", CASES)
def test_the_apple_block(client, admin, make_account, engine, case):
    stored, cancel, days, shown, dated = CASES[case]
    target = make_account()
    end = NOW + timedelta(days=days)
    add(
        engine,
        target.id,
        status=stored,
        cancel_at_period_end=cancel,
        period_end=end,
    )

    for view in views(client, admin, target.id):
        assert view["apple_subscription"] == {
            "status": shown,
            "started_at": iso(STARTED),
            "period_end": iso(end) if dated else None,
        }
        # Stripe's block stays Stripe's.
        assert view["subscription"] is None


def test_both_blocks_side_by_side(client, admin, make_account, engine):
    target = make_account()
    add(engine, target.id, source="stripe", external_id="sub_1", status="past_due")
    add(engine, target.id, status="active", cancel_at_period_end=True)

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "past_due"
        assert view["apple_subscription"]["status"] == "canceling"
        assert view["plan"]["plan"] == "premium"


def test_a_stripe_row_ended_and_not_canceling_is_still_ended(
    client, admin, make_account, engine
):
    """Only Apple's ended rows set to renew are in retry."""
    target = make_account()
    add(engine, target.id, source="stripe", external_id="sub_1", status="ended")
    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "ended"


def test_the_one_in_force_is_shown(client, admin, make_account, engine):
    target = make_account()
    add(engine, target.id, status="ended", cancel_at_period_end=True)
    add(engine, target.id, status="active", period_end=NOW + GRACE + timedelta(1))
    for view in views(client, admin, target.id):
        assert view["apple_subscription"]["status"] == "active"


# Deleting the account (D9).


@pytest.fixture
def user_client(make_client):
    return make_client()


def deleted(engine, user_id):
    with Session(engine) as db:
        return not db.scalar(
            select(func.count()).select_from(User).where(User.id == user_id)
        )


@pytest.mark.parametrize("status", ["active", "past_due", "ended"])
def test_a_deletion_past_a_renewing_apple_subscription_is_logged(
    user_client, make_account, engine, caplog, status
):
    target = make_account()
    add(engine, target.id, external_id=ORIGINAL, status=status)

    with caplog.at_level(logging.WARNING, logger="app.accounts.deletion"):
        response = user_client.delete("/api/me", headers=target.headers)

    assert response.status_code == 204, response.text
    assert deleted(engine, target.id)
    assert [record.getMessage() for record in caplog.records] == [
        f"billing: account {target.id} deleted with Apple subscription"
        f" {ORIGINAL} still renewing"
    ]


def test_no_line_for_one_set_to_stop(user_client, make_account, engine, caplog):
    target = make_account()
    add(engine, target.id, external_id=ORIGINAL, cancel_at_period_end=True)

    with caplog.at_level(logging.WARNING, logger="app.accounts.deletion"):
        assert user_client.delete("/api/me", headers=target.headers).status_code == 204

    assert deleted(engine, target.id)
    assert caplog.records == []


def test_the_admins_deletion_logs_it_too(client, admin, make_account, engine, caplog):
    target = make_account()
    add(engine, target.id, external_id=ORIGINAL)
    email = client.get(f"/api/admin/users/{target.id}", headers=admin.headers).json()[
        "email"
    ]

    with caplog.at_level(logging.WARNING, logger="app.accounts.deletion"):
        response = client.request(
            "DELETE",
            f"/api/admin/users/{target.id}",
            json={"email": email},
            headers=admin.headers,
        )

    assert response.status_code == 204, response.text
    assert deleted(engine, target.id)
    assert f"Apple subscription {ORIGINAL} still renewing" in caplog.text
