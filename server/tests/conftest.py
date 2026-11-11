"""Shared test setup.

The tests run against a real PostgreSQL (plan D12) named by `DATABASE_URL`,
the same variable the app reads, e.g.
`postgresql+psycopg://shushgift:shushgift@localhost:5432/shushgift_test`.
Point it at a test database, never at a database whose data matters:
`dev.ps1 -Test` and CI set it to theirs. The user needs the CREATEDB privilege
(the official Postgres image's user has it): the migration test runs on a
scratch database it creates and drops.
"""

import copy
import json
import os
import threading
import uuid
from collections.abc import Callable, Collection, Iterator
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.accounts import sessions
from app.billing.stripe_gateway import (
    CheckoutOrder,
    MissingAtStripe,
    Price,
    verify_signature,
)
from app.notifications.email_content import EmailMessage
from app.notifications.mailer import Outcome
from app.settings import Settings

# Checked before anything imports app.main, whose module-level app would fail
# with a less helpful validation error.
if not os.environ.get("DATABASE_URL"):
    pytest.exit(
        "DATABASE_URL is not set: the tests need a PostgreSQL test database",
        returncode=4,
    )

# For the apps built without `make_client`: a test that wants the worker asks
# for it, and none runs against the test database by accident.
os.environ["NOTIFICATIONS_WORKER"] = "false"


@pytest.fixture
def database_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture
def make_client(database_url: str, tmp_path) -> Iterator[Callable[..., TestClient]]:
    """Builds a client for an app with test settings, overridable by keyword.

    MEDIA_DIR defaults to a directory under tmp_path, so no test writes into
    the repository. The worker is off and the mailer a fake: no test reaches
    Brevo (comments plan Conventions).
    """
    from app.main import create_app

    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        values: dict[str, Any] = {
            "database_url": database_url,
            "media_dir": tmp_path / "media",
            "notifications_worker": False,
        } | overrides
        settings = Settings(**values)
        app = create_app(settings)
        app.state.mailer = FakeMailer()
        # Only where the gateway is configured: None is what the routes read
        # as "no gateway" (premium plan D9).
        if app.state.stripe_gateway is not None:
            app.state.stripe_gateway = FakeStripe(settings.stripe_webhook_secret)
        client = TestClient(app)
        client.__enter__()  # runs the lifespan, as uvicorn does
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def billing_on() -> dict[str, Any]:
    """Settings values making `limits_enforced` true, for `make_client` or a
    `model_copy`. Placeholders only: no test reaches Stripe."""
    return {
        "billing_enforce_limits": True,
        "stripe_secret_key": "sk_test_placeholder",
        "stripe_webhook_secret": "whsec_placeholder",
        "stripe_price_id": "price_placeholder",
        "billing_price_amount": "10.00",
        "public_base_url": "https://shushgift.example.test",
    }


class FakeMailer:
    """Stands in for `app.state.mailer`, a BrevoMailer: records every send and
    answers `outcome`, or raises it when it is an exception."""

    def __init__(self) -> None:
        self.outcome: Outcome | Exception = Outcome.SENT
        self.sent: list[tuple[str, str, EmailMessage]] = []
        self._lock = threading.Lock()

    def send(self, to_address: str, to_name: str, message: EmailMessage) -> Outcome:
        with self._lock:
            self.sent.append((to_address, to_name, message))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


@pytest.fixture
def mailer() -> FakeMailer:
    return FakeMailer()


class FakeStripe:
    """Stands in for `app.state.stripe_gateway`, a StripeGateway: no test
    reaches Stripe. Records every call in `calls`; a name in `failures` raises
    that exception; `on_call` runs inside each call, for the concurrency tests.
    The signature check runs for real (premium plan Conventions)."""

    def __init__(self, webhook_secret: str) -> None:
        self.webhook_secret = webhook_secret
        self.calls: list[tuple[str, Any]] = []
        self.failures: dict[str, Exception] = {}
        self.on_call: Callable[[str], None] | None = None
        self.price_answer = Price(
            active=True,
            unit_amount=1000,
            currency="eur",
            interval="year",
            interval_count=1,
            tax_behavior="inclusive",
        )
        self.subscriptions: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _called(self, name: str, *args: Any) -> None:
        with self._lock:
            self.calls.append((name, args))
        if self.on_call is not None:
            self.on_call(name)
        if name in self.failures:
            raise self.failures[name]

    def called(self, name: str) -> list[Any]:
        return [args for called_name, args in self.calls if called_name == name]

    def verify(self, payload: bytes, signature: str | None) -> dict[str, Any]:
        return verify_signature(payload, signature, self.webhook_secret)

    def price(self, price_id: str) -> Price:
        self._called("price", price_id)
        return self.price_answer

    def ensure_customer(self, user_id: uuid.UUID, email: str, name: str) -> str:
        self._called("ensure_customer", user_id, email, name)
        return f"cus_{user_id.hex}"

    def expire_open_sessions(self, customer_id: str) -> None:
        self._called("expire_open_sessions", customer_id)

    def checkout(self, order: CheckoutOrder) -> str:
        self._called("checkout", order)
        return "https://checkout.stripe.test/session"

    def portal(self, customer_id: str, return_url: str) -> str:
        self._called("portal", customer_id, return_url)
        return "https://billing.stripe.test/portal"

    def subscription(self, subscription_id: str) -> dict[str, Any]:
        # Read before `on_call`: a read that stalls has the state of its start.
        answer = copy.deepcopy(self.subscriptions.get(subscription_id))
        self._called("subscription", subscription_id)
        if answer is None:
            raise MissingAtStripe()
        return answer

    def cancel(self, subscription_id: str) -> None:
        self._called("cancel", subscription_id)

    def cancel_all(self, customer_id: str) -> list[str]:
        self._called("cancel_all", customer_id)
        return []

    def add_subscription(
        self,
        subscription_id: str,
        user_id: uuid.UUID | None,
        status: str = "active",
        period_end: datetime | None = None,
        customer: str = "cus_test",
        price: str = "price_placeholder",
    ) -> dict[str, Any]:
        """A subscription as Stripe answers it, its period end on its item."""
        end = period_end or sessions.utc_now() + timedelta(days=365)
        metadata = {} if user_id is None else {"user_id": str(user_id)}
        subscription = {
            "id": subscription_id,
            "status": status,
            "customer": customer,
            "metadata": metadata,
            "cancel_at_period_end": False,
            "cancel_at": None,
            "start_date": int(sessions.utc_now().timestamp()),
            "items": {
                "data": [
                    {
                        "price": {"id": price},
                        "current_period_end": int(end.timestamp()),
                    }
                ]
            },
        }
        self.subscriptions[subscription_id] = subscription
        return subscription

    def deliver(
        self, client: TestClient, event_type: str, obj: dict[str, Any], **event: Any
    ) -> Any:
        """Posts the event to the webhook, signed with the fake's secret."""
        body = json.dumps({"type": event_type, "data": {"object": obj}} | event)
        return client.post(
            "/api/billing/webhook",
            content=body.encode(),
            headers={"Stripe-Signature": self.sign(body)},
        )

    def sign(self, body: str, timestamp: int | None = None) -> str:
        import stripe

        return stripe.WebhookSignature.generate_signature_header(
            body, self.webhook_secret, timestamp=timestamp
        )


class FakeFetcher:
    """Stands in for `app.state.url_fetcher`, a SafeFetcher: answers every
    fetch with `result`, or raises it when it is an exception, and records
    the calls. No endpoint test fetches from the network."""

    def __init__(self) -> None:
        self.result: tuple[bytes, str] | Exception = (b"", "image/png")
        self.calls: list[tuple[str, tuple[str, ...], int]] = []

    def fetch(
        self, url: str, accept: Collection[str], max_bytes: int
    ) -> tuple[bytes, str]:
        self.calls.append((url, tuple(accept), max_bytes))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def url_fetcher(client: TestClient) -> FakeFetcher:
    """The fake fetcher, put in the app of the package's `client` fixture."""
    fake = FakeFetcher()
    client.app.state.url_fetcher = fake
    return fake
