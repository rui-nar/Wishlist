"""The billing routes: the plan, Stripe's Checkout and Portal, and its webhook
(premium plan D11 to D14).

No row lock is ever held across a call to Stripe: checkout and portal
authenticate with `unlocked_session` and lock the user only after their
last Stripe call, and the webhook reads the subscription before its first
write. A refusal is returned, not raised, so it keeps its `code`.
"""

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser, UnlockedSession, lock_signed_in
from app.accounts.models import User
from app.billing import stripe_events
from app.billing.entitlements import (
    GRACE,
    Applied,
    apply,
    is_premium,
    record_consent,
    summary,
)
from app.billing.models import ACTIVE, PAST_DUE, STRIPE, BillingCustomer, Entitlement
from app.billing.schemas import (
    BillingRefusal,
    BillingStatus,
    LegalLinks,
    Limits,
    Offer,
    SessionUrl,
)
from app.billing.stripe_gateway import (
    CheckoutOrder,
    GatewayError,
    InvalidWebhook,
    MissingAtStripe,
    Price,
    StripeGateway,
    TermsUrlMissing,
)
from app.db import DbSession
from app.lists.access import not_found
from app.settings import Settings

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/billing", tags=["billing"])

# Stripe's events are a few kilobytes.
MAX_WEBHOOK_BYTES = 1024 * 1024

# Outside production, what checkout shows when the owner has set no text
# (D17). In production nothing is sold without the owner's own (D16), so these
# are never shown there: `billing_selling` is false.
TEST_CONSENT_TEXT = (
    "[TEST ONLY - placeholder, not legal text] I accept the terms of this test."
)
TEST_TERMS_VERSION = "test-placeholder"

ALREADY_PREMIUM = "already_premium"
NO_SUBSCRIPTION = "no_subscription"
BILLING_UNAVAILABLE = "billing_unavailable"
BILLING_MISCONFIGURED = "billing_misconfigured"

_REFUSALS: dict[str, tuple[int, str]] = {
    ALREADY_PREMIUM: (status.HTTP_409_CONFLICT, "Already premium"),
    NO_SUBSCRIPTION: (status.HTTP_409_CONFLICT, "No subscription"),
    BILLING_UNAVAILABLE: (status.HTTP_502_BAD_GATEWAY, "Billing is unavailable"),
    BILLING_MISCONFIGURED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Billing is misconfigured",
    ),
}

_REFUSAL = {"model": BillingRefusal}


@router.get("")
def billing_status(request: Request, user: CurrentUser, db: DbSession) -> BillingStatus:
    settings: Settings = request.app.state.settings
    state = summary(db, user.id, request.app.state.clock())
    premium = state.plan == "premium"
    return BillingStatus(
        plan=state.plan,
        source=state.source,
        status=state.status,
        renews_at=state.renews_at,
        ends_at=state.ends_at,
        limits=Limits(
            max_lists=None if premium else settings.free_max_lists,
            max_gifts_per_list=None if premium else settings.free_max_gifts_per_list,
        ),
        enforced=settings.limits_enforced,
        offer=_offer(settings),
        can_manage=_can_manage(request, db, user.id),
        legal=LegalLinks(
            terms_url=settings.legal_terms_url.strip() or None,
            privacy_url=settings.legal_privacy_url.strip() or None,
            withdrawal_url=settings.legal_withdrawal_url.strip() or None,
        ),
    )


@router.post(
    "/checkout",
    response_model=SessionUrl,
    responses={409: _REFUSAL, 502: _REFUSAL, 503: _REFUSAL},
)
def checkout(
    request: Request, session: UnlockedSession, db: DbSession
) -> SessionUrl | JSONResponse:
    settings: Settings = request.app.state.settings
    gateway = request.app.state.stripe_gateway
    if gateway is None or not settings.billing_selling:
        raise not_found()
    user = db.get(User, session.user_id)
    if user is None:
        raise not_found()
    if is_premium(db, user.id, request.app.state.clock()):
        return _refusal(ALREADY_PREMIUM)
    price_id = settings.stripe_price_id.strip()
    base = settings.public_base_url.strip().rstrip("/")
    try:
        wrong = _misconfigured_variable(gateway.price(price_id), settings)
    except MissingAtStripe:
        wrong = "STRIPE_PRICE_ID"
    except GatewayError:
        return _refusal(BILLING_UNAVAILABLE)
    if wrong is not None:
        # The app never advertises a price other than the one charged (D12).
        _log.error("billing: the price at Stripe does not match %s", wrong)
        return _refusal(BILLING_MISCONFIGURED)
    stored = _stored_customer(db, user.id)
    try:
        customer_id = stored or gateway.ensure_customer(
            user.id, user.email, user.display_name
        )
        gateway.expire_open_sessions(customer_id)
        url = gateway.checkout(
            CheckoutOrder(
                user_id=user.id,
                customer_id=customer_id,
                price_id=price_id,
                terms_version=(
                    settings.billing_terms_version.strip() or TEST_TERMS_VERSION
                ),
                locale=user.language,
                consent_text=_consent_text(settings, user.language),
                success_url=f"{base}/account/plan?checkout=success",
                cancel_url=f"{base}/account/plan?checkout=cancelled",
                automatic_tax=settings.stripe_automatic_tax,
            )
        )
    except TermsUrlMissing:
        _log.error(
            "billing: Stripe refused checkout because the account has no terms of"
            " service URL. Set it in the Stripe dashboard: Settings > Public details"
            " > Terms of service. No checkout can succeed until then."
        )
        return _refusal(BILLING_MISCONFIGURED)
    except GatewayError:
        return _refusal(BILLING_UNAVAILABLE)
    # Stored only now, under this request's one short lock: if a call before
    # this failed, the customer's idempotency key gives a retry the same one.
    lock_signed_in(request, db, session)
    if stored is None:
        db.execute(
            insert(BillingCustomer)
            .values(user_id=user.id, source=STRIPE, customer_id=customer_id)
            .on_conflict_do_nothing()
        )
    return SessionUrl(url=url)


@router.post(
    "/portal",
    response_model=SessionUrl,
    responses={409: _REFUSAL, 502: _REFUSAL},
)
def portal(
    request: Request, session: UnlockedSession, db: DbSession
) -> SessionUrl | JSONResponse:
    settings: Settings = request.app.state.settings
    gateway = request.app.state.stripe_gateway
    base = settings.public_base_url.strip().rstrip("/")
    if gateway is None or not base:
        raise not_found()
    customer_id = _stored_customer(db, session.user_id)
    if customer_id is None:
        return _refusal(NO_SUBSCRIPTION)
    try:
        url = gateway.portal(customer_id, f"{base}/account/plan")
    except GatewayError:
        return _refusal(BILLING_UNAVAILABLE)
    lock_signed_in(request, db, session)
    return SessionUrl(url=url)


# No session: the signature speaks for Stripe.
@router.post(
    "/webhook",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={400: {"description": "Invalid"}, 502: _REFUSAL},
)
async def webhook(request: Request, db: DbSession) -> Response:
    """Stripe's events (D13). Depends on the gateway alone, not on selling:
    renewals keep being recorded with the offer withdrawn."""
    gateway = request.app.state.stripe_gateway
    if gateway is None:
        raise not_found()
    body = await _capped_body(request)
    if body is None:
        raise _invalid_webhook()
    try:
        event = gateway.verify(body, request.headers.get("stripe-signature"))
    except InvalidWebhook:
        raise _invalid_webhook() from None
    return await run_in_threadpool(_handle_event, request, db, event)


def _handle_event(request: Request, db: Session, event: dict[str, Any]) -> Response:
    pointer = stripe_events.pointer(event)
    if pointer is None:
        return _no_content()
    settings: Settings = request.app.state.settings
    gateway = request.app.state.stripe_gateway
    # Before the read, so a later handler always wins (D13).
    read_at = request.app.state.clock()
    try:
        subscription = gateway.subscription(pointer.subscription_id)
    except GatewayError:
        return _refusal(BILLING_UNAVAILABLE)
    user_id = stripe_events.metadata_user_id(subscription) or _customer_owner(
        db, stripe_events.customer_id(subscription)
    )
    if user_id is None:
        _log.warning(
            "stripe: subscription %s of no known user", pointer.subscription_id
        )
        return _no_content()
    facts = stripe_events.facts(subscription, user_id)
    if facts is None:
        _log.error("stripe: subscription %s could not be read", pointer.subscription_id)
        return _no_content()
    if apply(db, facts, read_at) is Applied.USER_GONE:
        return _cancel_orphan(gateway, subscription, facts.external_id)
    price = settings.stripe_price_id.strip()
    if price and stripe_events.price_id(subscription) != price:
        _log.warning("stripe: subscription %s has another price", facts.external_id)
    if pointer.consent is not None:
        record_consent(
            db,
            STRIPE,
            facts.external_id,
            pointer.consent.accepted_at,
            pointer.consent.version,
        )
    _warn_if_two_in_force(db, user_id, facts.external_id, read_at)
    return _no_content()


def _cancel_orphan(
    gateway: StripeGateway, subscription: dict[str, Any], external_id: str
) -> Response:
    """The purchase outlived its account (D15): no charge may follow. Only
    one proven ours is ever cancelled: a Stripe account can be shared."""
    if not stripe_events.is_ours(subscription):
        _log.warning("stripe: subscription %s of no known user", external_id)
        return _no_content()
    if stripe_events.is_finished(subscription):
        return _no_content()
    _log.warning("stripe: cancelling subscription %s of a gone account", external_id)
    try:
        gateway.cancel(external_id)
    except GatewayError:
        return _refusal(BILLING_UNAVAILABLE)
    return _no_content()


def _warn_if_two_in_force(
    db: Session, user_id: uuid.UUID, external_id: str, now: datetime
) -> None:
    """Two tabs paying in the same moment can only be caught here (D12): the
    owner refunds one by hand."""
    in_force = db.scalar(
        select(func.count())
        .select_from(Entitlement)
        .where(
            Entitlement.user_id == user_id,
            Entitlement.source == STRIPE,
            Entitlement.status.in_((ACTIVE, PAST_DUE)),
            Entitlement.period_end > now - GRACE,
        )
    )
    if in_force and in_force > 1:
        _log.error(
            "stripe: %d subscriptions in force for one customer, including %s",
            in_force,
            external_id,
        )


def _customer_owner(db: Session, customer_id: str | None) -> uuid.UUID | None:
    if customer_id is None:
        return None
    return db.scalar(
        select(BillingCustomer.user_id).where(
            BillingCustomer.source == STRIPE,
            BillingCustomer.customer_id == customer_id,
        )
    )


def _stored_customer(db: Session, user_id: uuid.UUID) -> str | None:
    return db.scalar(
        select(BillingCustomer.customer_id).where(
            BillingCustomer.user_id == user_id, BillingCustomer.source == STRIPE
        )
    )


def _can_manage(request: Request, db: Session, user_id: uuid.UUID) -> bool:
    settings: Settings = request.app.state.settings
    return (
        request.app.state.stripe_gateway is not None
        and bool(settings.public_base_url.strip().rstrip("/"))
        and _stored_customer(db, user_id) is not None
    )


def _offer(settings: Settings) -> Offer | None:
    if not settings.billing_selling:
        return None
    return Offer(
        amount=f"{settings.billing_price:.2f}",
        currency=settings.billing_price_currency.strip().upper(),
        interval="year",
    )


def _misconfigured_variable(price: Price, settings: Settings) -> str | None:
    """The variable that does not match the price at Stripe, if any (D12)."""
    if (
        not price.active
        or price.interval != "year"
        or price.interval_count != 1
        or price.tax_behavior != "inclusive"
    ):
        return "STRIPE_PRICE_ID"
    if price.currency.lower() != settings.billing_price_currency.strip().lower():
        return "BILLING_PRICE_CURRENCY"
    if (
        price.unit_amount is None
        or Decimal(price.unit_amount) / 100 != settings.billing_price
    ):
        return "BILLING_PRICE_AMOUNT"
    return None


def _consent_text(settings: Settings, language: str) -> str:
    text = {
        "en": settings.billing_consent_text_en,
        "fr": settings.billing_consent_text_fr,
    }[language]
    return text.strip() or TEST_CONSENT_TEXT


async def _capped_body(request: Request) -> bytes | None:
    """The body, or None beyond MAX_WEBHOOK_BYTES: before reading when
    Content-Length says so, else as soon as the stream passes it."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_WEBHOOK_BYTES:
        return None
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_WEBHOOK_BYTES:
            return None
    return bytes(body)


def _invalid_webhook() -> HTTPException:
    # One body for every case, so nothing says what was wrong.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook"
    )


def _no_content() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _refusal(code: str) -> JSONResponse:
    status_code, detail = _REFUSALS[code]
    return JSONResponse(
        status_code=status_code, content={"detail": detail, "code": code}
    )
