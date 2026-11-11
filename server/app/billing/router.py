"""The billing routes: the plan, Stripe's Checkout and Portal, and its webhook
(premium plan D11 to D14); Apple's purchases and notifications (Apple IAP
plan D3, D4).

No row lock is ever held across a call to Stripe or Apple: checkout, portal
and Apple's transactions authenticate with `unlocked_session` and lock the
user only after their last call, and the webhook and Apple's notifications
read the subscription before their first write. A refusal is returned, not
raised, so it keeps its `code`.
"""

import json
import logging
import uuid
from datetime import datetime, timedelta
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
from app.billing import apple_events, stripe_events
from app.billing.apple_events import SANDBOX
from app.billing.apple_gateway import AppleError, InvalidSignedData, MissingAtApple
from app.billing.entitlements import (
    GRACE,
    Applied,
    apply,
    is_premium,
    record_consent,
    summary,
)
from app.billing.models import (
    ACTIVE,
    APPLE,
    PAST_DUE,
    STRIPE,
    BillingCustomer,
    Entitlement,
)
from app.billing.schemas import (
    AppleOffer,
    AppleTransactionReport,
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

# Often enough to be seen, rarely enough that a public route cannot flood the log.
BAD_SIGNATURE_WARNING_INTERVAL = timedelta(minutes=1)

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
INVALID_TRANSACTION = "invalid_transaction"
OTHER_ACCOUNT = "other_account"
OTHER_PRODUCT = "other_product"
SANDBOX_REFUSED = "sandbox_refused"
UNKNOWN_TRANSACTION = "unknown_transaction"

_REFUSALS: dict[str, tuple[int, str]] = {
    ALREADY_PREMIUM: (status.HTTP_409_CONFLICT, "Already premium"),
    NO_SUBSCRIPTION: (status.HTTP_409_CONFLICT, "No subscription"),
    BILLING_UNAVAILABLE: (status.HTTP_502_BAD_GATEWAY, "Billing is unavailable"),
    BILLING_MISCONFIGURED: (
        status.HTTP_503_SERVICE_UNAVAILABLE,
        "Billing is misconfigured",
    ),
    INVALID_TRANSACTION: (status.HTTP_400_BAD_REQUEST, "Invalid transaction"),
    OTHER_ACCOUNT: (status.HTTP_409_CONFLICT, "Another account's purchase"),
    OTHER_PRODUCT: (status.HTTP_409_CONFLICT, "Not the product sold"),
    SANDBOX_REFUSED: (status.HTTP_409_CONFLICT, "Sandbox purchases are refused"),
    UNKNOWN_TRANSACTION: (status.HTTP_409_CONFLICT, "Unknown to Apple"),
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
        apple_offer=_apple_offer(request),
        apple_renewing=bool(apple_events.renewing(db, user.id)),
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
        _warn_of_bad_signature(request)
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


@router.post(
    "/apple/transactions",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={400: _REFUSAL, 409: _REFUSAL, 502: _REFUSAL},
)
def apple_transaction(
    request: Request,
    report: AppleTransactionReport,
    session: UnlockedSession,
    db: DbSession,
) -> Response:
    """A purchase or a restore on iPhone (Apple IAP plan D3). The transaction
    only says which subscription; what is recorded is Apple's answer for it.
    Recorded whatever the plan: a purchase made is never dropped."""
    settings: Settings = request.app.state.settings
    gateway = request.app.state.apple_gateway
    if gateway is None:
        raise not_found()
    try:
        reported = gateway.transaction(report.signed_transaction)
    except InvalidSignedData:
        return _refusal(INVALID_TRANSACTION)
    except AppleError:
        return _refusal(BILLING_UNAVAILABLE)
    external_id = apple_events.original_transaction_id(reported)
    where = apple_events.environment(reported)
    if external_id is None or where is None:
        return _refusal(INVALID_TRANSACTION)
    # Before Apple is asked: a refusal costs no call.
    refused = _apple_refusal(
        settings,
        reported,
        session.user_id,
        external_id,
        apple_events.account_token(reported),
    )
    if refused is not None:
        return _refusal(refused)
    # Before the read, so a later handler always wins (premium plan D13).
    read_at = request.app.state.clock()
    try:
        subscription = gateway.subscription(external_id, where)
    except MissingAtApple:
        _log.warning("apple: transaction %s is unknown to Apple", external_id)
        return _refusal(UNKNOWN_TRANSACTION)
    except AppleError:
        return _refusal(BILLING_UNAVAILABLE)
    # Whose the subscription is now, as for a notification (D4, review R2-1):
    # the latest token, else the stored row's account; with neither, the
    # reported transaction's, which is this account.
    owner = (
        apple_events.account_token(subscription.transaction)
        or _stored_owner(db, external_id)
        or session.user_id
    )
    refused = _apple_refusal(
        settings, subscription.transaction, session.user_id, external_id, owner
    )
    if refused is not None:
        return _refusal(refused)
    facts = apple_events.facts(subscription, session.user_id)
    if facts is None:
        # Apple answered what it does not document: the app retries later.
        _log.error("apple: subscription %s could not be read", external_id)
        return _refusal(BILLING_UNAVAILABLE)
    lock_signed_in(request, db, session)
    apply(db, facts, read_at)
    return _no_content()


# No session: Apple's signature speaks for Apple.
@router.post(
    "/apple/notifications",
    responses={400: {"description": "Invalid"}, 502: _REFUSAL},
)
async def apple_notification(request: Request, db: DbSession) -> Response:
    """App Store Server Notifications V2 (D4): verified, then trusted only as a
    pointer to the subscription, read back from Apple. Answered 200 whenever
    Apple's retrying would change nothing."""
    gateway = request.app.state.apple_gateway
    if gateway is None:
        raise not_found()
    signed = _signed_payload(await _capped_body(request))
    if signed is None:
        raise _invalid_notification()
    try:
        # Off the event loop: checking a certificate's revocation asks Apple.
        notification = await run_in_threadpool(gateway.notification, signed)
    except InvalidSignedData:
        _warn_of_bad_apple_signature(request)
        raise _invalid_notification() from None
    except AppleError:
        return _refusal(BILLING_UNAVAILABLE)
    return await run_in_threadpool(_handle_notification, request, db, notification)


def _handle_notification(
    request: Request, db: Session, notification: dict[str, Any]
) -> Response:
    settings: Settings = request.app.state.settings
    gateway = request.app.state.apple_gateway
    signed = apple_events.signed_transaction(notification)
    if signed is None:
        return _ok()
    try:
        pointed = gateway.transaction(signed)
    except InvalidSignedData:
        _log.error("apple: a notification's transaction failed its signature check")
        return _ok()
    except AppleError:
        return _refusal(BILLING_UNAVAILABLE)
    external_id = apple_events.original_transaction_id(pointed)
    where = apple_events.environment(pointed)
    if external_id is None or where is None:
        _log.error("apple: a notification points at no subscription")
        return _ok()
    read_at = request.app.state.clock()
    try:
        subscription = gateway.subscription(external_id, where)
    except MissingAtApple:
        _log.warning("apple: subscription %s is unknown to Apple", external_id)
        return _ok()
    except AppleError:
        return _refusal(BILLING_UNAVAILABLE)
    user_id = _apple_owner(db, subscription.transaction, external_id)
    if user_id is None:
        _log.warning("apple: subscription %s of no known account", external_id)
        return _ok()
    if not _sold_here(settings, subscription.transaction):
        _log.warning("apple: subscription %s is of another product", external_id)
        return _ok()
    if _sandbox_refused(settings, subscription.transaction, user_id):
        _log.warning(
            "apple: Sandbox subscription %s refused for account %s",
            external_id,
            user_id,
        )
        return _ok()
    facts = apple_events.facts(subscription, user_id)
    if facts is None:
        _log.error("apple: subscription %s could not be read", external_id)
        return _ok()
    if apply(db, facts, read_at) is Applied.USER_GONE:
        # Apple gives the server no way to cancel it (D9).
        _log.warning("apple: subscription %s of a gone account", external_id)
    return _ok()


def _apple_refusal(
    settings: Settings,
    transaction: dict[str, Any],
    user_id: uuid.UUID,
    external_id: str,
    owner: uuid.UUID | None,
) -> str | None:
    """Why this transaction may not grant Premium to this account, whose it is
    being `owner` (D2, D3, D6), logged with ids only, or None."""
    if not _sold_here(settings, transaction):
        _log.warning("apple: transaction %s is of another product", external_id)
        return OTHER_PRODUCT
    if owner != user_id:
        _log.warning(
            "apple: transaction %s names another account (%s)",
            external_id,
            owner or "none",
        )
        return OTHER_ACCOUNT
    if _sandbox_refused(settings, transaction, user_id):
        _log.warning(
            "apple: Sandbox transaction %s refused for account %s",
            external_id,
            user_id,
        )
        return SANDBOX_REFUSED
    return None


def _sold_here(settings: Settings, transaction: dict[str, Any]) -> bool:
    return apple_events.is_subscription(transaction) and (
        apple_events.product_id(transaction) == settings.apple_product_id.strip()
    )


def _sandbox_refused(
    settings: Settings, transaction: dict[str, Any], user_id: uuid.UUID
) -> bool:
    """D6: production takes a Sandbox purchase from a listed account only, so
    that a tester's free purchase grants nothing there. Elsewhere the gateway
    accepts Sandbox only."""
    return (
        settings.app_env == "production"
        and apple_events.environment(transaction) == SANDBOX
        and user_id not in settings.apple_sandbox_ids
    )


def _apple_owner(
    db: Session, transaction: dict[str, Any], external_id: str
) -> uuid.UUID | None:
    """Whose the subscription is (D4, review R1-2): the latest transaction's
    token when it names an existing account; only when it carries none, the
    account the stored row names."""
    token = apple_events.account_token(transaction)
    if token is not None:
        return db.scalar(select(User.id).where(User.id == token))
    return _stored_owner(db, external_id)


def _stored_owner(db: Session, external_id: str) -> uuid.UUID | None:
    return db.scalar(
        select(Entitlement.user_id).where(
            Entitlement.source == APPLE, Entitlement.external_id == external_id
        )
    )


def _signed_payload(body: bytes | None) -> str | None:
    """`signedPayload` of a notification's body, or None for anything else."""
    if body is None:
        return None
    try:
        decoded = json.loads(body)
    except ValueError, RecursionError:
        return None
    found = decoded.get("signedPayload") if isinstance(decoded, dict) else None
    return found if isinstance(found, str) and found else None


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


def _apple_offer(request: Request) -> AppleOffer | None:
    """Apart from Stripe's (D7): the gateway exists only once every variable
    is set and the key loads."""
    if request.app.state.apple_gateway is None:
        return None
    settings: Settings = request.app.state.settings
    return AppleOffer(product_id=settings.apple_product_id.strip())


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


def _warn_of_bad_signature(request: Request) -> None:
    """A wrong STRIPE_WEBHOOK_SECRET leaves every buyer unrecorded, and this is
    its only trace on the server. Fixed words, nothing from the request. Runs
    on the event loop with no await, so two requests cannot both pass."""
    state = request.app.state
    now = state.clock()
    last = getattr(state, "bad_signature_warned_at", None)
    if last is not None and now - last < BAD_SIGNATURE_WARNING_INTERVAL:
        return
    state.bad_signature_warned_at = now
    _log.warning(
        "stripe: a webhook failed its signature check: if every event does,"
        " check STRIPE_WEBHOOK_SECRET"
    )


def _warn_of_bad_apple_signature(request: Request) -> None:
    """As `_warn_of_bad_signature`: a wrong APPLE_BUNDLE_ID or
    APPLE_APP_APPLE_ID leaves every renewal unrecorded."""
    state = request.app.state
    now = state.clock()
    last = getattr(state, "bad_apple_signature_warned_at", None)
    if last is not None and now - last < BAD_SIGNATURE_WARNING_INTERVAL:
        return
    state.bad_apple_signature_warned_at = now
    _log.warning(
        "apple: a notification failed its check: if every one does, check"
        " APPLE_BUNDLE_ID, APPLE_APP_APPLE_ID and the URL's environment"
    )


def _invalid_webhook() -> HTTPException:
    # One body for every case, so nothing says what was wrong.
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid webhook"
    )


def _invalid_notification() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid notification"
    )


def _no_content() -> Response:
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _ok() -> Response:
    # What Apple takes for delivered (D4).
    return Response(status_code=status.HTTP_200_OK)


def _refusal(code: str) -> JSONResponse:
    status_code, detail = _REFUSALS[code]
    return JSONResponse(
        status_code=status_code, content={"detail": detail, "code": code}
    )
