"""The Google subscription in its own block (Android release plan D8): each
row of the list and the detail say what Google Play does for the account,
shaped like the Stripe and Apple blocks, and an admin's deletion cancels a
renewing one first (D6)."""

import copy
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.entitlements import GRACE
from app.billing.google_gateway import GoogleUnavailable, MissingAtGoogle
from app.billing.models import Entitlement

PRODUCT_ID = "premium_yearly"
TOKEN = "token-1.AO-J1Oa"


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


@pytest.fixture
def started(now):
    return now - timedelta(days=100)


@pytest.fixture
def add(engine, now, started):
    def add_(user_id, source="google", **fields):
        values = {
            "user_id": user_id,
            "source": source,
            "external_id": f"token-{uuid.uuid4().hex}",
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


def test_no_google_subscription_is_null(client, admin, make_account):
    target = make_account()
    for view in views(client, admin, target.id):
        assert view["google_subscription"] is None
        assert view["google_renewing"] is False


# (stored status, cancel_at_period_end, days to period_end) -> (shown status,
# the stored date shown).
CASES = {
    "active renews": ("active", False, 30, "active", True),
    "canceling ends": ("active", True, 30, "canceling", True),
    "grace period": ("past_due", False, 10, "past_due", True),
    "on hold or paused, Google may charge": ("ended", False, -5, "past_due", False),
    "expired": ("ended", True, -5, "ended", False),
    "no news past the grace": ("active", False, -4, "no_news", True),
}


@pytest.mark.parametrize("case", CASES)
def test_the_google_block(client, admin, make_account, add, now, started, case):
    stored, cancel, days, shown, dated = CASES[case]
    target = make_account()
    end = now + timedelta(days=days)
    add(target.id, status=stored, cancel_at_period_end=cancel, period_end=end)

    for view in views(client, admin, target.id):
        assert view["google_subscription"] == {
            "status": shown,
            "started_at": iso(started),
            "period_end": iso(end) if dated else None,
        }
        # The other blocks stay theirs.
        assert view["subscription"] is None
        assert view["apple_subscription"] is None


def test_three_blocks_side_by_side(client, admin, make_account, add):
    target = make_account()
    add(target.id, source="stripe", external_id="sub_1", status="past_due")
    add(target.id, source="apple", external_id="2000000001", cancel_at_period_end=True)
    add(target.id, status="active")

    for view in views(client, admin, target.id):
        assert view["subscription"]["status"] == "past_due"
        assert view["apple_subscription"]["status"] == "canceling"
        assert view["google_subscription"]["status"] == "active"
        assert (view["apple_renewing"], view["google_renewing"]) == (False, True)


def test_the_one_in_force_is_shown(client, admin, make_account, add, now):
    target = make_account()
    add(target.id, status="ended", cancel_at_period_end=True)
    add(target.id, status="active", period_end=now + GRACE + timedelta(days=1))
    for view in views(client, admin, target.id):
        assert view["google_subscription"]["status"] == "active"


@pytest.mark.parametrize(
    "source, status, cancel, renewing",
    [
        ("google", "active", False, True),
        ("google", "ended", False, True),
        ("google", "active", True, False),
        ("apple", "active", False, False),
        ("stripe", "active", False, False),
        ("manual", "active", False, False),
    ],
)
def test_google_renewing(
    client, admin, make_account, add, source, status, cancel, renewing
):
    target = make_account()
    add(target.id, source=source, status=status, cancel_at_period_end=cancel)
    for view in views(client, admin, target.id):
        assert view["google_renewing"] is renewing


# The admin's deletion goes the account's way (admin panel plan D9).


class Google:
    """Google Play as `closing.stop_billing` asks it: a read, then a cancel."""

    product_id = PRODUCT_ID

    def __init__(self) -> None:
        self.purchases: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.failure: Exception | None = None

    def subscription(self, token):
        self.calls.append(("subscription", token))
        if token not in self.purchases:
            raise MissingAtGoogle()
        return copy.deepcopy(self.purchases[token])

    def cancel(self, token):
        self.calls.append(("cancel", token))
        if self.failure is not None:
            raise self.failure


def renewing_purchase():
    return {
        "subscriptionState": "SUBSCRIPTION_STATE_ACTIVE",
        "lineItems": [
            {"productId": PRODUCT_ID, "autoRenewingPlan": {"autoRenewEnabled": True}}
        ],
    }


def delete(client, admin, target_id):
    email = client.get(f"/api/admin/users/{target_id}", headers=admin.headers).json()[
        "email"
    ]
    return client.request(
        "DELETE",
        f"/api/admin/users/{target_id}",
        json={"email": email},
        headers=admin.headers,
    )


def exists(engine, user_id):
    with Session(engine) as db:
        return bool(
            db.scalar(select(func.count()).select_from(User).where(User.id == user_id))
        )


def test_the_admins_deletion_cancels_a_renewing_one_first(
    client, admin, make_account, add, engine
):
    google = Google()
    client.app.state.google_gateway = google
    target = make_account()
    add(target.id, external_id=TOKEN)
    google.purchases[TOKEN] = renewing_purchase()

    response = delete(client, admin, target.id)

    assert response.status_code == 204, response.text
    assert google.calls == [("subscription", TOKEN), ("cancel", TOKEN)]
    assert not exists(engine, target.id)


def test_the_admins_deletion_is_refused_when_google_fails(
    client, admin, make_account, add, engine
):
    google = Google()
    google.failure = GoogleUnavailable()
    client.app.state.google_gateway = google
    target = make_account()
    add(target.id, external_id=TOKEN)
    google.purchases[TOKEN] = renewing_purchase()

    response = delete(client, admin, target.id)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )
    assert exists(engine, target.id)


def test_the_admins_deletion_is_refused_without_the_gateway(
    client, admin, make_account, add, engine
):
    target = make_account()
    add(target.id, external_id=TOKEN)

    response = delete(client, admin, target.id)

    assert (response.status_code, response.json()["code"]) == (
        409,
        "billing_unavailable",
    )
    assert exists(engine, target.id)
