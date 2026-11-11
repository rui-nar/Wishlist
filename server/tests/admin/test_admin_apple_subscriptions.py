"""The Apple subscription in its own block (Apple IAP plan D9): each row of
the list and the detail say what Apple does for the account, shaped like the
Stripe block, and an admin's deletion past one that may still charge is
logged."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.entitlements import GRACE
from app.billing.models import Entitlement

ORIGINAL = "2000000001"


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


@pytest.fixture
def started(now):
    return now - timedelta(days=100)


@pytest.fixture
def add(engine, now, started):
    def add_(user_id, source="apple", **fields):
        values = {
            "user_id": user_id,
            "source": source,
            "external_id": f"{uuid.uuid4().int % 10**12}",
            "status": "active",
            "period_end": now + timedelta(days=100),
            "cancel_at_period_end": False,
            "started_at": started,
            "read_at": now,
        } | fields
        with Session(engine) as db, db.begin():
            db.add(Entitlement(**values))

    return add_


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
def test_the_apple_block(client, admin, make_account, add, now, started, case):
    stored, cancel, days, shown, dated = CASES[case]
    target = make_account()
    end = now + timedelta(days=days)
    add(target.id, status=stored, cancel_at_period_end=cancel, period_end=end)

    for view in views(client, admin, target.id):
        assert view["apple_subscription"] == {
            "status": shown,
            "started_at": iso(started),
            "period_end": iso(end) if dated else None,
        }
        # Stripe's block stays Stripe's.
        assert view["subscription"] is None


def test_both_blocks_side_by_side(client, admin, make_account, add):
    target = make_account()
    add(target.id, source="stripe", external_id="sub_1", status="past_due")
    add(target.id, status="active", cancel_at_period_end=True)

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "past_due"
        assert view["apple_subscription"]["status"] == "canceling"
        assert view["plan"]["plan"] == "premium"


def test_a_stripe_row_ended_and_not_canceling_is_still_ended(
    client, admin, make_account, add
):
    """Only Apple's ended rows set to renew are in retry."""
    target = make_account()
    add(target.id, source="stripe", external_id="sub_1", status="ended")
    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "ended"


def test_the_one_in_force_is_shown(client, admin, make_account, add, now):
    target = make_account()
    add(target.id, status="ended", cancel_at_period_end=True)
    add(target.id, status="active", period_end=now + GRACE + timedelta(days=1))
    for view in views(client, admin, target.id):
        assert view["apple_subscription"]["status"] == "active"


def test_the_admins_deletion_logs_a_renewing_one(
    client, admin, make_account, add, engine, caplog
):
    target = make_account()
    add(target.id, external_id=ORIGINAL)
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
    with Session(engine) as db:
        assert not db.scalar(
            select(func.count()).select_from(User).where(User.id == target.id)
        )
    assert (
        f"billing: account {target.id} deleted with Apple subscription"
        f" {ORIGINAL} still renewing"
    ) in caplog.text
