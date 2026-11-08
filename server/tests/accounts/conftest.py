"""Setup for the account tests.

They run on their own scratch database, migrated to head once per test run and
emptied after each test: the tables come from the migrations themselves, and
another run against the shared test database cannot see or disturb their rows.
"""

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient
from google.auth import crypt, jwt
from sqlalchemy import Engine, create_engine, make_url, text

from app.accounts.google import GoogleIdentity, GoogleVerifier, InvalidGoogleToken

SERVER_DIR = Path(__file__).resolve().parents[2]
WEB_CLIENT_ID = "web-client.apps.googleusercontent.com"


@pytest.fixture(scope="session")
def accounts_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"wishlist_accounts_{uuid.uuid4().hex[:12]}"
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
def database_url(accounts_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return accounts_database_url


@pytest.fixture(scope="session")
def engine(accounts_database_url: str) -> Iterator[Engine]:
    engine = create_engine(accounts_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, user_identities, sessions"))


class FakeGoogle:
    """Stands in for GoogleVerifier: knows the tokens it was told about."""

    def __init__(self) -> None:
        self.identities: dict[str, GoogleIdentity] = {}
        # Called with the token before it is looked up; lets a test hold
        # concurrent sign-ins at the same point.
        self.before_verify: Callable[[str], None] = lambda token: None
        self._lock = threading.Lock()

    def issue(self, sub: str, email: str = "", name: str = "") -> str:
        """A new token for this Google account, as Google would mint one."""
        token = f"fake-id-token-{uuid.uuid4().hex}"
        with self._lock:
            self.identities[token] = GoogleIdentity(
                sub=sub,
                email=email or f"{sub}@example.com",
                name=name or f"Name of {sub}",
            )
        return token

    def verify(self, id_token: str) -> GoogleIdentity:
        self.before_verify(id_token)
        with self._lock:
            identity = self.identities.get(id_token)
        if identity is None:
            raise InvalidGoogleToken("signature")
        return identity


class FakeClock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@pytest.fixture
def google() -> FakeGoogle:
    return FakeGoogle()


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def client(make_client, google: FakeGoogle, clock: FakeClock) -> TestClient:
    client = make_client(google_client_ids=WEB_CLIENT_ID)
    client.app.state.google_verifier = google
    client.app.state.clock = clock
    return client


@pytest.fixture
def sign_in(client: TestClient, google: FakeGoogle) -> Callable[..., dict]:
    """Signs in through the endpoint; returns the response body."""

    def sign_in(sub: str = "google-sub-1", email: str = "", name: str = "") -> dict:
        response = client.post(
            "/api/auth/google", json={"id_token": google.issue(sub, email, name)}
        )
        assert response.status_code == 200, response.text
        return response.json()

    return sign_in


class GoogleKeys:
    """Google's side of a real verification, without Google.

    Signs ID tokens with a key of its own and serves its certificate as the
    transport GoogleVerifier fetches Google's certificates with, so the real
    verification code runs and no test calls Google.
    """

    KEY_ID = "test-key"
    CLIENT_ID = WEB_CLIENT_ID

    def __init__(self) -> None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
        now = datetime.now(UTC)
        certificate = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        self._certificates = {
            self.KEY_ID: certificate.public_bytes(serialization.Encoding.PEM).decode()
        }
        self._signer = crypt.RSASigner.from_string(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ),
            key_id=self.KEY_ID,
        )

    def __call__(self, url: str, method: str = "GET", **kwargs: Any) -> Any:
        return SimpleNamespace(status=200, data=json.dumps(self._certificates).encode())

    def token(self, **claims: Any) -> str:
        """A signed ID token for WEB_CLIENT_ID, valid now unless overridden."""
        now = int(time.time())
        payload = {
            "iss": "https://accounts.google.com",
            "aud": WEB_CLIENT_ID,
            "sub": "google-sub-1",
            "email": "ada@example.com",
            "email_verified": True,
            "name": "Ada Lovelace",
            "iat": now,
            "exp": now + 3600,
        } | claims
        return jwt.encode(self._signer, payload).decode()

    def verifier(self, audiences: list[str] | None = None) -> GoogleVerifier:
        return GoogleVerifier(audiences or [WEB_CLIENT_ID], request=self)


@pytest.fixture(scope="session")
def google_keys() -> GoogleKeys:
    return GoogleKeys()
