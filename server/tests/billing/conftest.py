"""Setup for the billing tests.

Like the notification tests, they run on their own scratch database, migrated
to head once per test run and emptied after each test. Users are created
directly in the database with a session each.
"""

import json
import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from apple_fakes import APP_APPLE_ID, BUNDLE_ID, PRODUCT_ID, FakeApple, build_apple_pki
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from fastapi.testclient import TestClient
from google_fakes import (
    AUDIENCE,
    PACKAGE,
    PUSH_ACCOUNT,
    FakeGoogle,
    GoogleKeys,
    private_pem,
)
from google_fakes import PRODUCT_ID as GOOGLE_PRODUCT_ID
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User
from app.billing.apple_events import PRODUCTION, SANDBOX

SERVER_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def billing_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"wishlist_billing_{uuid.uuid4().hex[:12]}"
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        url = (
            make_url(base_url).set(database=name).render_as_string(hide_password=False)
        )
        upgrade = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=SERVER_DIR,
            env=os.environ | {"DATABASE_URL": url},
            capture_output=True,
            text=True,
        )
        assert upgrade.returncode == 0, upgrade.stderr
        yield url
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


@pytest.fixture
def database_url(billing_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return billing_database_url


@pytest.fixture(scope="session")
def engine(billing_database_url: str) -> Iterator[Engine]:
    engine = create_engine(billing_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users CASCADE"))


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(engine: Engine) -> Callable[[], Account]:
    """A user with a live session."""

    def make() -> Account:
        with Session(engine) as db, db.begin():
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Ada")
            db.add(user)
            db.flush()
            token = sessions.create(db, user.id, sessions.utc_now())
            user_id = user.id
        return Account(id=user_id, token=token)

    return make


@pytest.fixture(scope="session")
def apple_pki():
    return build_apple_pki()


@pytest.fixture(scope="session")
def apple_private_key() -> str:
    """An In-App Purchase key's text, for settings: generated, never Apple's."""
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.fixture
def apple_on(apple_private_key: str) -> dict[str, Any]:
    """Settings values that make the Apple gateway (Apple IAP plan D7), for
    `make_client`. Placeholders, and a generated key."""
    return {
        "apple_product_id": PRODUCT_ID,
        "apple_bundle_id": BUNDLE_ID,
        "apple_iap_issuer_id": "issuer-placeholder",
        "apple_iap_key_id": "KEYPLACEHOLDER",
        "apple_iap_private_key": apple_private_key,
        "apple_app_apple_id": str(APP_APPLE_ID),
    }


@pytest.fixture
def make_apple_client(
    make_client: Callable[..., TestClient], apple_on: dict[str, Any], apple_pki
) -> Callable[..., TestClient]:
    """A client whose Apple gateway is a `FakeApple` accepting the
    environments its settings do (D6): no test reaches Apple."""

    def make(**overrides: Any) -> TestClient:
        client = make_client(**apple_on | overrides)
        if client.app.state.apple_gateway is not None:
            production = client.app.state.settings.app_env == "production"
            client.app.state.apple_gateway = FakeApple(
                apple_pki, (PRODUCTION, SANDBOX) if production else (SANDBOX,)
            )
        return client

    return make


@pytest.fixture(scope="session")
def google_keys() -> GoogleKeys:
    return GoogleKeys()


@pytest.fixture(scope="session")
def google_service_account_json() -> str:
    """A service account's JSON key, for settings: generated, never Google's.
    Loading it reaches nothing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return json.dumps(
        {
            "type": "service_account",
            "project_id": "example-project",
            "private_key_id": "0123456789abcdef",
            "private_key": private_pem(key),
            "client_email": "play-api@example-project.iam.gserviceaccount.com",
            "client_id": "123456789",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


@pytest.fixture
def google_on(google_service_account_json: str) -> dict[str, Any]:
    """Settings values that make the Google gateway (Android release plan
    D6), for `make_client`. Placeholders, and a generated key."""
    return {
        "google_play_product_id": GOOGLE_PRODUCT_ID,
        "google_play_package_name": PACKAGE,
        "google_play_service_account_json": google_service_account_json,
        "google_play_pubsub_audience": AUDIENCE,
        "google_play_pubsub_service_account": PUSH_ACCOUNT,
    }


@pytest.fixture
def make_google_client(
    make_client: Callable[..., TestClient], google_on: dict[str, Any], google_keys
) -> Callable[..., TestClient]:
    """A client whose Google gateway is a `FakeGoogle`: no test reaches
    Google."""

    def make(**overrides: Any) -> TestClient:
        client = make_client(**google_on | overrides)
        if client.app.state.google_gateway is not None:
            client.app.state.google_gateway = FakeGoogle(google_keys)
        return client

    return make
