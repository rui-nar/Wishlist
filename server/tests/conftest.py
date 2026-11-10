"""Shared test setup.

The tests run against a real PostgreSQL (plan D12) named by `DATABASE_URL`,
the same variable the app reads, e.g.
`postgresql+psycopg://wishlist:wishlist@localhost:5432/wishlist_test`.
Point it at a test database, never at a database whose data matters:
`dev.ps1 -Test` and CI set it to theirs. The user needs the CREATEDB privilege
(the official Postgres image's user has it): the migration test runs on a
scratch database it creates and drops.
"""

import os
import threading
from collections.abc import Callable, Collection, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

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
        app = create_app(Settings(**values))
        app.state.mailer = FakeMailer()
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
        "public_base_url": "https://wishlist.example.test",
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
