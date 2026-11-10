"""Stripe, behind one module (premium plan D10).

The only module that imports the SDK, and lazily: an environment without keys
never loads it. An answer can be late, wrong, missing or hostile, so everything
leaves here as a small value or a typed exception: no key, email, body or
Stripe message goes into a log line or an exception, only ids and fixed words.
"""

import contextlib
import json
import logging
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from app.billing.stripe_events import APP_MARKER, FINISHED

_log = logging.getLogger(__name__)

# One call takes at most (2 + 1) x 15 = 45 s, the SDK's defaults 240 s (D10).
HTTP_TIMEOUT_SECONDS = 15
MAX_NETWORK_RETRIES = 2
SIGNATURE_TOLERANCE_SECONDS = 300


class GatewayError(Exception):
    """Stripe's answer, reduced to its meaning: its text stays out."""


class GatewayUnavailable(GatewayError):
    """Stripe failed or refused; retrying later is safe."""


class MissingAtStripe(GatewayError):
    """Stripe has no such object, or a key for another account is in use."""


class TermsUrlMissing(GatewayError):
    """The Stripe account has no terms of service URL, so no checkout can
    succeed until the owner sets it (D12)."""


class InvalidWebhook(Exception):
    """Not a body signed with our secret within the tolerance."""


@dataclass(frozen=True)
class Price:
    active: bool
    unit_amount: int | None
    currency: str
    interval: str | None
    interval_count: int | None
    tax_behavior: str | None


@dataclass(frozen=True)
class CheckoutOrder:
    """What one Checkout session sells, to whom (D12)."""

    user_id: uuid.UUID
    customer_id: str
    price_id: str
    terms_version: str
    locale: str
    consent_text: str
    success_url: str
    cancel_url: str
    automatic_tax: bool


def checkout_params(order: CheckoutOrder) -> dict[str, Any]:
    """The session's parameters, exactly D12's."""
    user_id = str(order.user_id)
    params: dict[str, Any] = {
        "mode": "subscription",
        "line_items": [{"price": order.price_id, "quantity": 1}],
        "customer": order.customer_id,
        "client_reference_id": user_id,
        "subscription_data": {"metadata": {"user_id": user_id, "app": APP_MARKER}},
        "metadata": {"terms_version": order.terms_version},
        "locale": order.locale,
        "consent_collection": {"terms_of_service": "required"},
        "custom_text": {"terms_of_service_acceptance": {"message": order.consent_text}},
        "success_url": order.success_url,
        "cancel_url": order.cancel_url,
    }
    if order.automatic_tax:
        params |= {
            "automatic_tax": {"enabled": True},
            "billing_address_collection": "required",
            "customer_update": {"address": "auto", "name": "auto"},
        }
    return params


def verify_signature(
    payload: bytes, signature: str | None, secret: str
) -> dict[str, Any]:
    """The event, once the signature is verified (D13). No network: the SDK
    only compares an HMAC. Why it failed is nobody's business."""
    import stripe

    try:
        stripe.Webhook.construct_event(
            payload, signature, secret, tolerance=SIGNATURE_TOLERANCE_SECONDS
        )
        # Plain dicts for the translator: the SDK's object is not one.
        event = json.loads(payload)
    except Exception:
        raise InvalidWebhook() from None
    if not isinstance(event, dict):
        raise InvalidWebhook()
    return event


class StripeGateway:
    """Constructed once, only when the gateway is configured (D9)."""

    def __init__(self, secret_key: str, webhook_secret: str) -> None:
        import stripe

        self._stripe = stripe
        self._webhook_secret = webhook_secret
        self._client = stripe.StripeClient(
            secret_key,
            http_client=stripe.RequestsClient(timeout=HTTP_TIMEOUT_SECONDS),
            max_network_retries=MAX_NETWORK_RETRIES,
        )

    def verify(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        return verify_signature(payload, signature, self._webhook_secret)

    def price(self, price_id: str) -> Price:
        with self._translated("price"):
            price = self._client.v1.prices.retrieve(price_id).to_dict()
        recurring = price.get("recurring") or {}
        return Price(
            active=price.get("active") is True,
            unit_amount=price.get("unit_amount"),
            currency=str(price.get("currency") or ""),
            interval=recurring.get("interval"),
            interval_count=recurring.get("interval_count"),
            tax_behavior=price.get("tax_behavior"),
        )

    def ensure_customer(self, user_id: uuid.UUID, email: str, name: str) -> str:
        """The customer for this user: the key makes a concurrent or repeated
        call answer the same one (D12)."""
        with self._translated("customer"):
            customer = self._client.v1.customers.create(
                {
                    "email": email,
                    "name": name,
                    "metadata": {"user_id": str(user_id), "app": APP_MARKER},
                },
                {"idempotency_key": f"wishlist-customer-{user_id}"},
            )
        return customer.id

    def expire_open_sessions(self, customer_id: str) -> None:
        sessions = self._client.v1.checkout.sessions
        with self._translated("sessions"):
            listed = sessions.list(
                {"customer": customer_id, "status": "open", "limit": 100}
            )
            for session in listed.auto_paging_iter():
                self._expire(session.id)

    def _expire(self, session_id: str) -> None:
        sessions = self._client.v1.checkout.sessions
        try:
            sessions.expire(session_id)
        except self._stripe.InvalidRequestError:
            # Completed or expired since it was listed: fine if it no longer
            # can be paid.
            if sessions.retrieve(session_id).to_dict().get("status") == "open":
                raise

    def checkout(self, order: CheckoutOrder) -> str:
        try:
            session = self._client.v1.checkout.sessions.create(checkout_params(order))
        except self._stripe.StripeError as exc:
            if _blames_the_terms_url(exc):
                raise TermsUrlMissing() from None
            raise self._translation("checkout", exc) from None
        url = session.to_dict().get("url")
        if not url:
            _log.warning("stripe: checkout: answer without a url")
            raise GatewayUnavailable()
        return url

    def portal(self, customer_id: str, return_url: str) -> str:
        with self._translated("portal"):
            session = self._client.v1.billing_portal.sessions.create(
                {"customer": customer_id, "return_url": return_url}
            )
        url = session.to_dict().get("url")
        if not url:
            _log.warning("stripe: portal: answer without a url")
            raise GatewayUnavailable()
        return url

    def subscription(self, subscription_id: str) -> dict[str, Any]:
        """The subscription as Stripe has it now, as plain dicts: the
        translator reads it (D13)."""
        with self._translated("subscription"):
            return self._client.v1.subscriptions.retrieve(subscription_id).to_dict()

    def cancel(self, subscription_id: str) -> None:
        """Cancels at once. One that has already ended is done: a refusal is a
        failure only if it can still bill."""
        subscriptions = self._client.v1.subscriptions
        with self._translated("cancel"):
            try:
                subscriptions.cancel(subscription_id)
            except self._stripe.InvalidRequestError:
                status = subscriptions.retrieve(subscription_id).to_dict().get("status")
                if status not in FINISHED:
                    raise

    def cancel_all(self, customer_id: str) -> list[str]:
        """Stops everything a customer could still be charged for, asking
        Stripe rather than our rows (D15): open sessions expired, every
        subscription not ended cancelled at once. The ids cancelled."""
        self.expire_open_sessions(customer_id)
        with self._translated("cancel_all"):
            listed = self._client.v1.subscriptions.list(
                {"customer": customer_id, "status": "all", "limit": 100}
            )
            running = [
                subscription.id
                for subscription in listed.auto_paging_iter()
                if subscription.status not in FINISHED
            ]
        for subscription_id in running:
            self.cancel(subscription_id)
        return running

    @contextlib.contextmanager
    def _translated(self, action: str) -> Iterator[None]:
        try:
            yield
        except self._stripe.StripeError as exc:
            raise self._translation(action, exc) from None

    def _translation(self, action: str, exc: Exception) -> GatewayError:
        name = type(exc).__name__
        if getattr(exc, "code", None) == "resource_missing":
            _log.warning("stripe: %s: not found", action)
            return MissingAtStripe()
        if isinstance(
            exc, self._stripe.AuthenticationError | self._stripe.PermissionError
        ):
            # Not a blip: nothing works until the key is fixed.
            _log.error("stripe: %s: the key was refused (%s)", action, name)
        else:
            _log.warning("stripe: %s: %s", action, name)
        return GatewayUnavailable()


def _blames_the_terms_url(exc: Exception) -> bool:
    """Stripe has no error code for this, so its parameter or its words
    (BILLING.md, Stripe setup step 5)."""
    param = str(getattr(exc, "param", "") or "")
    return param.startswith("consent_collection") or (
        "terms of service" in str(exc).lower()
    )
