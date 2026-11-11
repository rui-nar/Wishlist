"""Apple's transactions into our facts (Apple IAP plan D3 to D6).

Pure but for `renewing`: Apple's signed payloads, already verified by the
gateway, as plain dicts in, facts out. A notification or a client's report
only says which subscription to look at; what is recorded comes from Apple's
current answer for it, so ordering and repeats take care of themselves (D4).
Every field is read defensively: a value that is not what Apple documents
counts as absent.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.orm import Session

from app.billing.entitlements import EntitlementFacts
from app.billing.models import ACTIVE, APPLE, ENDED, PAST_DUE, Entitlement

# Apple's environments, by their names in a payload.
SANDBOX = "Sandbox"
PRODUCTION = "Production"

# Apple's subscription statuses (App Store Server API, `status`).
STATUS_ACTIVE = 1
STATUS_EXPIRED = 2
STATUS_BILLING_RETRY = 3
STATUS_BILLING_GRACE_PERIOD = 4
STATUS_REVOKED = 5

# D5: Premium lasts through the billing grace period and no longer; a retry
# past it, an expiry and a revocation grant nothing.
_STATUSES = {
    STATUS_ACTIVE: ACTIVE,
    STATUS_BILLING_GRACE_PERIOD: PAST_DUE,
    STATUS_BILLING_RETRY: ENDED,
    STATUS_EXPIRED: ENDED,
    STATUS_REVOKED: ENDED,
}

# The ones Apple may still charge, when auto-renew is on.
_CAN_CHARGE = frozenset(
    {STATUS_ACTIVE, STATUS_BILLING_GRACE_PERIOD, STATUS_BILLING_RETRY}
)

AUTO_RENEWABLE = "Auto-Renewable Subscription"


@dataclass(frozen=True)
class AppleSubscription:
    """One subscription as the App Store Server API states it now: its status,
    its latest transaction and its renewal info, each verified."""

    status: int | None
    transaction: dict[str, Any]
    renewal: dict[str, Any]


def signed_transaction(notification: dict[str, Any]) -> str | None:
    """The transaction a notification points at, still signed, or None when it
    is about no subscription (a summary, a test)."""
    found = _mapping(notification.get("data")).get("signedTransactionInfo")
    return found if isinstance(found, str) and found else None


def original_transaction_id(transaction: dict[str, Any]) -> str | None:
    """The subscription's id at Apple, our `external_id`: digits, or None."""
    found = transaction.get("originalTransactionId")
    if isinstance(found, str) and found.isascii() and found.isdigit():
        return found
    return None


def environment(transaction: dict[str, Any]) -> str | None:
    found = transaction.get("environment")
    return found if found in (SANDBOX, PRODUCTION) else None


def product_id(transaction: dict[str, Any]) -> str | None:
    found = transaction.get("productId")
    return found if isinstance(found, str) and found else None


def is_subscription(transaction: dict[str, Any]) -> bool:
    return transaction.get("type") == AUTO_RENEWABLE


def account_token(transaction: dict[str, Any]) -> uuid.UUID | None:
    """The `appAccountToken` the app set at the purchase, the account's id
    (D2), or None when absent or no uuid."""
    value = transaction.get("appAccountToken")
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def facts(
    subscription: AppleSubscription, user_id: uuid.UUID
) -> EntitlementFacts | None:
    """The subscription as `EntitlementFacts`, or None when its id or status
    is not one Apple documents: nothing is then known about it.

    `cancel_at_period_end` says Apple will not charge again: auto-renew off,
    or a subscription that cannot renew any more. A row `ended` with it false
    is therefore in billing retry, which Apple may still charge (D9)."""
    transaction = subscription.transaction
    external_id = original_transaction_id(transaction)
    status = _STATUSES.get(subscription.status)
    if external_id is None or status is None:
        return None
    expires = _timestamp(transaction.get("expiresDate"))
    period_end = expires
    if subscription.status == STATUS_BILLING_GRACE_PERIOD:
        # The grace period's end is when Premium ends (review R1-5).
        period_end = (
            _timestamp(subscription.renewal.get("gracePeriodExpiresDate")) or expires
        )
    auto_renew = subscription.renewal.get("autoRenewStatus")
    renews = (
        subscription.status in _CAN_CHARGE
        and type(auto_renew) is int
        and auto_renew == 1
    )
    return EntitlementFacts(
        source=APPLE,
        external_id=external_id,
        user_id=user_id,
        status=status,
        period_end=period_end,
        cancel_at_period_end=not renews,
        started_at=_timestamp(transaction.get("originalPurchaseDate")),
    )


def _renewing() -> ColumnElement[bool]:
    """An Apple subscription that Apple may still charge, whatever `summary`
    shows (D9): `cancel_at_period_end` false, by `facts`."""
    return and_(
        Entitlement.source == APPLE, Entitlement.cancel_at_period_end.is_(False)
    )


def renewing(db: Session, user_id: uuid.UUID) -> list[str]:
    """The account's renewing Apple subscriptions: the server cannot cancel
    them, so a deletion only warns of them."""
    return list(
        db.scalars(
            select(Entitlement.external_id)
            .where(Entitlement.user_id == user_id, _renewing())
            .order_by(Entitlement.external_id)
        )
    )


def renewing_accounts(db: Session, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Those of `user_ids` with a renewing Apple subscription, in one query:
    the admin's deletion warns of it (review R2-2)."""
    return set(
        db.scalars(
            select(Entitlement.user_id)
            .where(Entitlement.user_id.in_(user_ids), _renewing())
            .distinct()
        )
    )


def _timestamp(value: Any) -> datetime | None:
    """Apple's dates are milliseconds since the epoch."""
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, UTC)
    except OverflowError, ValueError, OSError:
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
