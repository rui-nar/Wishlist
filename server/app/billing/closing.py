"""Stopping an account's billing before the account goes (premium plan D15)."""

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.models import ENDED, STRIPE, BillingCustomer, Entitlement
from app.billing.stripe_gateway import GatewayError, StripeGateway

_log = logging.getLogger(__name__)

# The right of withdrawal: inside it, the owner refunds by hand (D19).
WITHDRAWAL = timedelta(days=14)


def stop_billing(
    db: Session, gateway: StripeGateway | None, user_id: uuid.UUID, now: datetime
) -> set[str] | JSONResponse:
    """The subscriptions dealt with, once nothing can charge this account any
    more, for `report_late_purchases`; else the refusal to answer, with nothing
    changed: retrying is safe.

    The caller holds no lock: this asks Stripe, for up to 45 s a call. Stripe
    is asked rather than our rows, which can be late, and every row it did not
    answer for is then cancelled by its own id; with no gateway, only our rows
    can say that nothing bills. A failure to find the customer is a failure
    like any other (review R1-5): a key for another Stripe account answers the
    same.
    """
    # Before Stripe is called: a row that appears after this was not dealt with.
    billable = _billable(db, user_id)
    cancelled: list[str] = []
    if gateway is None:
        if billable:
            _log.error(
                "billing: account %s not deleted: a purchase may still bill and"
                " the gateway is not configured",
                user_id,
            )
            return _refusal(status.HTTP_409_CONFLICT)
    else:
        customer_id = db.scalar(
            select(BillingCustomer.customer_id).where(
                BillingCustomer.user_id == user_id, BillingCustomer.source == STRIPE
            )
        )
        try:
            if customer_id is not None:
                cancelled = gateway.cancel_all(customer_id)
            # A purchase recorded with no customer stored, or on another
            # customer (review R7-1): only its own id can stop it before its
            # next renewal.
            for external_id in billable:
                if external_id not in cancelled:
                    gateway.cancel(external_id)
                    cancelled.append(external_id)
        except GatewayError:
            return _refusal(status.HTTP_502_BAD_GATEWAY)
    _warn_of_refunds(db, user_id, cancelled, now)
    return set(cancelled)


def report_late_purchases(
    db: Session, user_id: uuid.UUID, dealt_with: set[str]
) -> None:
    """Names each subscription recorded between `stop_billing` and the user's
    lock (review R6-1), which no Stripe call covered. Run under that lock, so
    every webhook that found the user has committed. The deletion goes on: the
    owner cancels by hand."""
    for external_id in _billable(db, user_id):
        if external_id not in dealt_with:
            _log.error(
                "billing: subscription %s of account %s was recorded during its"
                " deletion and not cancelled: cancel it at Stripe",
                external_id,
                user_id,
            )


def _billable(db: Session, user_id: uuid.UUID) -> list[str]:
    """The Stripe subscriptions our rows say can still charge this account."""
    return list(
        db.scalars(
            select(Entitlement.external_id)
            .where(
                Entitlement.user_id == user_id,
                Entitlement.source == STRIPE,
                Entitlement.status != ENDED,
            )
            .order_by(Entitlement.external_id)
        )
    )


def _warn_of_refunds(
    db: Session, user_id: uuid.UUID, cancelled: list[str], now: datetime
) -> None:
    """Names each subscription the owner may have to refund (D19): from our
    rows as well as from what was just cancelled, so a retry after a partial
    failure still names the ones its first attempt cancelled. A subscription
    with no known start counts as recent: its event has not arrived yet."""
    rows = db.execute(
        select(Entitlement.external_id, Entitlement.started_at).where(
            Entitlement.user_id == user_id, Entitlement.source == STRIPE
        )
    )
    started = {external_id: start for external_id, start in rows}
    for external_id in sorted(set(started) | set(cancelled)):
        start = started.get(external_id)
        if start is None or now - start <= WITHDRAWAL:
            _log.warning(
                "billing: subscription %s of a deleted account started within"
                " the withdrawal period: check whether a refund is due",
                external_id,
            )


def _refusal(status_code: int) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": "Billing is unavailable", "code": "billing_unavailable"},
    )
