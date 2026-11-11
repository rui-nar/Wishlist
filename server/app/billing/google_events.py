"""Google Play's subscriptions into our facts (Android release plan D6).

Pure but for the queries at the end: the Play Developer API's answers, as
plain dicts in, facts out. A notification or a client's report only says which
purchase to look at; what is recorded comes from Google's current answer for
it, so ordering and repeats take care of themselves. Every field is read
defensively: a value that is not what Google documents counts as absent.

A purchase is known by its purchase token, our `external_id`. A token that
replaces another (`linkedPurchaseToken`: a re-signup or a change of plan)
gets its own row, and the one it replaces is ended: Google reads, acknowledges
and cancels a subscription by its current token only, so a row keyed by the
first token could not stop its successor at an account's deletion.

No purchase token goes into a log line: logs name a purchase by its order id.
"""

import base64
import binascii
import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, func, select, update
from sqlalchemy.orm import Session

from app.billing.entitlements import EntitlementFacts
from app.billing.models import ACTIVE, ENDED, GOOGLE, INCOMPLETE, PAST_DUE, Entitlement

# Google documents no maximum; tokens seen are a few hundred characters. Kept
# well under what the unique index on `external_id` can hold (2704 bytes).
MAX_TOKEN_LENGTH = 2048
# What a purchase token is made of, which keeps it safe in a URL path.
_TOKEN = re.compile(r"[A-Za-z0-9._\-]+")

# `subscriptionState` (purchases.subscriptionsv2).
PENDING = "SUBSCRIPTION_STATE_PENDING"
STATE_ACTIVE = "SUBSCRIPTION_STATE_ACTIVE"
PAUSED = "SUBSCRIPTION_STATE_PAUSED"
IN_GRACE_PERIOD = "SUBSCRIPTION_STATE_IN_GRACE_PERIOD"
ON_HOLD = "SUBSCRIPTION_STATE_ON_HOLD"
CANCELED = "SUBSCRIPTION_STATE_CANCELED"
EXPIRED = "SUBSCRIPTION_STATE_EXPIRED"
PENDING_PURCHASE_CANCELED = "SUBSCRIPTION_STATE_PENDING_PURCHASE_CANCELED"

# D6: Premium lasts through Play's grace period and no longer; on hold,
# paused, expired or voided grants nothing. A canceled one stays active to the
# end of what was paid, set to stop. A payment still pending grants nothing.
_STATUSES = {
    STATE_ACTIVE: ACTIVE,
    CANCELED: ACTIVE,
    IN_GRACE_PERIOD: PAST_DUE,
    ON_HOLD: ENDED,
    PAUSED: ENDED,
    EXPIRED: ENDED,
    PENDING: INCOMPLETE,
    PENDING_PURCHASE_CANCELED: ENDED,
}

# The ones Google may still charge, when auto-renew is on: on hold and paused
# resume by themselves, and a pending payment completes.
_CAN_CHARGE = frozenset({STATE_ACTIVE, IN_GRACE_PERIOD, ON_HOLD, PAUSED, PENDING})

# The ones a pending acknowledgement is owed for: Google refunds a purchase
# left unacknowledged for three days.
_ACKNOWLEDGEABLE = frozenset({STATE_ACTIVE, IN_GRACE_PERIOD, CANCELED})
ACKNOWLEDGEMENT_PENDING = "ACKNOWLEDGEMENT_STATE_PENDING"

# `voidedPurchaseNotification.productType`: a subscription, not a one-time
# product, which is never sold here.
VOIDED_SUBSCRIPTION = 1


def is_token(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) <= MAX_TOKEN_LENGTH
        and _TOKEN.fullmatch(value) is not None
    )


def developer_notification(body: bytes | None) -> dict[str, Any] | None:
    """The `DeveloperNotification` a Pub/Sub push carries, base64 in
    `message.data`, or None for anything else."""
    if body is None:
        return None
    try:
        push = json.loads(body)
        data = _mapping(_mapping(push).get("message")).get("data")
        if not isinstance(data, str):
            return None
        decoded = json.loads(base64.b64decode(data, validate=True))
    except ValueError, RecursionError, binascii.Error:
        return None
    return decoded if isinstance(decoded, dict) else None


def notification_package(notification: dict[str, Any]) -> Any:
    return notification.get("packageName")


def notification_token(notification: dict[str, Any]) -> str | None:
    """The purchase a notification points at, or None when it is about no
    subscription: a test, a one-time product, or what Google adds later. A
    voided purchase is a pointer too (review R1-4): Play's state decides."""
    subscription = _mapping(notification.get("subscriptionNotification"))
    if subscription:
        token = subscription.get("purchaseToken")
        return token if isinstance(token, str) and token else None
    voided = _mapping(notification.get("voidedPurchaseNotification"))
    if voided.get("productType") == VOIDED_SUBSCRIPTION:
        token = voided.get("purchaseToken")
        return token if isinstance(token, str) and token else None
    return None


def notification_order(notification: dict[str, Any]) -> str | None:
    """A voided purchase's order id, for a log line."""
    return _order(_mapping(notification.get("voidedPurchaseNotification")))


def line_item(purchase: dict[str, Any], product_id: str) -> dict[str, Any] | None:
    """The purchase's line item for `product_id`, the one subscription sold
    here, or None when it is not part of it."""
    items = purchase.get("lineItems")
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("productId") == product_id:
            return item
    return None


def account_id(purchase: dict[str, Any]) -> uuid.UUID | None:
    """The `obfuscatedExternalAccountId` the app set at the purchase, the
    account's id (D6), or None when absent or no uuid."""
    identifiers = _mapping(purchase.get("externalAccountIdentifiers"))
    value = identifiers.get("obfuscatedExternalAccountId")
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def linked_token(purchase: dict[str, Any]) -> str | None:
    """The token this purchase replaces, if any."""
    found = purchase.get("linkedPurchaseToken")
    return found if is_token(found) else None


def expired_token(purchase: dict[str, Any]) -> str | None:
    """For a resubscription made in the Play Store after expiry, which
    carries no account id, the token of the subscription that expired (D6,
    review R1-1)."""
    context = _mapping(purchase.get("outOfAppPurchaseContext"))
    found = context.get("expiredPurchaseToken")
    return found if is_token(found) else None


def is_test(purchase: dict[str, Any]) -> bool:
    """A license tester's purchase, which charges nothing."""
    return isinstance(purchase.get("testPurchase"), dict)


def order_id(purchase: dict[str, Any], product_id: str) -> str:
    """What names the purchase in a log line, never its token."""
    item = line_item(purchase, product_id) or {}
    return (
        _order(item, "latestSuccessfulOrderId")
        or _order(purchase, "latestOrderId")
        or "(no order id)"
    )


def needs_acknowledgement(purchase: dict[str, Any]) -> bool:
    return (
        purchase.get("acknowledgementState") == ACKNOWLEDGEMENT_PENDING
        and purchase.get("subscriptionState") in _ACKNOWLEDGEABLE
    )


def can_charge(purchase: dict[str, Any], product_id: str) -> bool:
    """Google may still charge it: auto-renew on, in a state that renews."""
    item = line_item(purchase, product_id) or {}
    auto_renew = _mapping(item.get("autoRenewingPlan")).get("autoRenewEnabled")
    return purchase.get("subscriptionState") in _CAN_CHARGE and auto_renew is True


def facts(
    purchase: dict[str, Any], token: str, user_id: uuid.UUID, product_id: str
) -> EntitlementFacts | None:
    """The purchase as `EntitlementFacts`, or None when its state is not one
    Google documents or it is not of `product_id`: nothing is then known
    about it.

    `period_end` is the line item's `expiryTime`, which in the grace period
    Google extends to the grace period's end. `cancel_at_period_end` says
    Google will not charge again: a row `ended` with it false is on hold or
    paused, which Google may still charge."""
    status = _STATUSES.get(purchase.get("subscriptionState"))
    item = line_item(purchase, product_id)
    if status is None or item is None or not is_token(token):
        return None
    return EntitlementFacts(
        source=GOOGLE,
        external_id=token,
        user_id=user_id,
        status=status,
        period_end=_timestamp(item.get("expiryTime")),
        cancel_at_period_end=not can_charge(purchase, product_id),
        started_at=_timestamp(purchase.get("startTime")),
    )


def stored_owner(db: Session, token: str | None) -> uuid.UUID | None:
    if token is None:
        return None
    return db.scalar(
        select(Entitlement.user_id).where(
            Entitlement.source == GOOGLE, Entitlement.external_id == token
        )
    )


def end_replaced(db: Session, token: str | None, read_at: datetime) -> None:
    """Ends the row of the token a purchase replaced, as Google now reads it:
    expired. A read at least as recent of that token wins, as in `apply`. Run
    after `apply`, under the user's lock it took."""
    if token is None:
        return
    db.execute(
        update(Entitlement)
        .where(
            Entitlement.source == GOOGLE,
            Entitlement.external_id == token,
            Entitlement.read_at <= read_at,
        )
        .values(
            status=ENDED,
            cancel_at_period_end=True,
            read_at=read_at,
            updated_at=func.now(),
        )
    )


def _renewing() -> ColumnElement[bool]:
    """A Google subscription that Google may still charge, whatever `summary`
    shows: `cancel_at_period_end` false, by `facts`."""
    return and_(
        Entitlement.source == GOOGLE, Entitlement.cancel_at_period_end.is_(False)
    )


def renewing(db: Session, user_id: uuid.UUID) -> list[str]:
    """The tokens of the account's renewing Google subscriptions, which its
    deletion cancels first."""
    return list(
        db.scalars(
            select(Entitlement.external_id)
            .where(Entitlement.user_id == user_id, _renewing())
            .order_by(Entitlement.external_id)
        )
    )


def renewing_accounts(db: Session, user_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Those of `user_ids` with a renewing Google subscription, in one query,
    for the admin's row."""
    return set(
        db.scalars(
            select(Entitlement.user_id)
            .where(Entitlement.user_id.in_(user_ids), _renewing())
            .distinct()
        )
    )


def _order(value: dict[str, Any], key: str = "orderId") -> str | None:
    found = value.get(key)
    # Google's order ids, `GPA.` and digits: nothing else goes into a log.
    if isinstance(found, str) and re.fullmatch(r"GPA\.[0-9.\-]{1,64}", found):
        return found
    return None


def _timestamp(value: Any) -> datetime | None:
    """Google's dates are RFC 3339, Z-normalised."""
    if not isinstance(value, str):
        return None
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        return None
    return found if found.tzinfo is not None else None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}
