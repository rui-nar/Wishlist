"""Stripe's objects into our facts (premium plan D3, D13).

Pure: a subscription or an event as plain dicts in, facts out. An event only
says which subscription to look at; what is recorded comes from reading that
subscription, so ordering and repeats take care of themselves (D13). Every
field is read defensively: a value that is not what Stripe documents counts
as absent.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.billing.entitlements import EntitlementFacts
from app.billing.models import ACTIVE, ENDED, INCOMPLETE, PAST_DUE, STRIPE

_COMPLETED = "checkout.session.completed"
_SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    }
)

_STATUSES = {
    "active": ACTIVE,
    "trialing": ACTIVE,
    "past_due": PAST_DUE,
    "incomplete": INCOMPLETE,
    "incomplete_expired": ENDED,
    "canceled": ENDED,
    "unpaid": ENDED,
    "paused": ENDED,
}

# Stripe's two final states: nothing can bill again. `unpaid` and `paused`
# grant nothing either, but they can still resume.
FINISHED = frozenset({"canceled", "incomplete_expired"})

# `metadata.app` on what our checkout creates, at Stripe for as long as the
# subscriptions sold: later releases must keep reading it.
APP_MARKER = "wishlist"


@dataclass(frozen=True)
class Consent:
    """The buyer's acceptance at checkout, as the session states it (D12)."""

    accepted_at: datetime
    version: str


@dataclass(frozen=True)
class Pointer:
    """Which subscription an event is about, and its consent if it has one."""

    subscription_id: str
    consent: Consent | None


def pointer(event: dict[str, Any]) -> Pointer | None:
    """The subscription this event points at, or None when nothing is to be
    done: a type not handled, or a session that is no subscription."""
    kind = event.get("type")
    data = _mapping(event.get("data"))
    obj = _mapping(data.get("object"))
    if kind == _COMPLETED:
        subscription_id = _object_id(obj.get("subscription"))
        if subscription_id is None:
            return None
        return Pointer(subscription_id, _consent(obj, event.get("created")))
    if kind in _SUBSCRIPTION_EVENTS:
        subscription_id = _object_id(obj.get("id"))
        if subscription_id is None:
            return None
        return Pointer(subscription_id, None)
    return None


def facts(subscription: dict[str, Any], user_id: uuid.UUID) -> EntitlementFacts | None:
    """The subscription as `EntitlementFacts`, or None when its id or status
    is not one Stripe documents: nothing is then known about it (D13)."""
    external_id = _object_id(subscription.get("id"))
    status = _STATUSES.get(_text(subscription.get("status")))
    if external_id is None or status is None:
        return None
    return EntitlementFacts(
        source=STRIPE,
        external_id=external_id,
        user_id=user_id,
        status=status,
        period_end=_period_end(subscription),
        # API versions after the portal's change set `cancel_at` instead of
        # the flag; both say the subscription stops at a date (BILLING.md).
        cancel_at_period_end=subscription.get("cancel_at_period_end") is True
        or _timestamp(subscription.get("cancel_at")) is not None,
        started_at=_timestamp(subscription.get("start_date")),
    )


def is_finished(subscription: dict[str, Any]) -> bool:
    return _text(subscription.get("status")) in FINISHED


def is_ours(subscription: dict[str, Any]) -> bool:
    """Whether Wishlist's checkout sold it: the proof an automatic cancel
    needs, since a Stripe account can hold another app's subscriptions."""
    return _mapping(subscription.get("metadata")).get("app") == APP_MARKER


def metadata_user_id(subscription: dict[str, Any]) -> uuid.UUID | None:
    """The account the checkout named on the subscription, if a valid id."""
    value = _mapping(subscription.get("metadata")).get("user_id")
    try:
        return uuid.UUID(value) if isinstance(value, str) else None
    except ValueError:
        return None


def customer_id(subscription: dict[str, Any]) -> str | None:
    return _object_id(subscription.get("customer"))


def price_id(subscription: dict[str, Any]) -> str | None:
    """The first item's price, in the shape of the API or the older `plan`."""
    for item in _items(subscription):
        for field in ("price", "plan"):
            found = _object_id(_mapping(item.get(field)).get("id"))
            if found:
                return found
    return None


def _consent(session: dict[str, Any], created: Any) -> Consent | None:
    if _mapping(session.get("consent")).get("terms_of_service") != "accepted":
        return None
    accepted_at = _timestamp(created)
    if accepted_at is None:
        return None
    version = _text(_mapping(session.get("metadata")).get("terms_version"))
    return Consent(accepted_at, version or "unknown")


def _period_end(subscription: dict[str, Any]) -> datetime | None:
    """On the subscription until API 2025-03-31, on its items since; both are
    read so that neither an API version nor an old payload loses it."""
    top = _timestamp(subscription.get("current_period_end"))
    if top is not None:
        return top
    ends = [_timestamp(item.get("current_period_end")) for item in _items(subscription)]
    return max((end for end in ends if end is not None), default=None)


def _items(subscription: dict[str, Any]) -> list[dict[str, Any]]:
    data = _mapping(subscription.get("items")).get("data")
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _object_id(value: Any) -> str | None:
    """An id, whether the payload carries it bare or as an expanded object."""
    found = value.get("id") if isinstance(value, dict) else value
    return found if isinstance(found, str) and found else None


def _timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    try:
        return datetime.fromtimestamp(value, UTC)
    except OverflowError, ValueError, OSError:
        return None


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""
