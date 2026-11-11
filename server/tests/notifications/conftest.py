"""Setup for the notification tests.

Like the list tests, they run on their own scratch database, migrated to head
once per test run and emptied after each test. Users are created directly in
the database with a session each.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User

SERVER_DIR = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def notifications_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"shushgift_notifications_{uuid.uuid4().hex[:12]}"
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
def database_url(notifications_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return notifications_database_url


@pytest.fixture(scope="session")
def engine(notifications_database_url: str) -> Iterator[Engine]:
    engine = create_engine(notifications_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        # The worker sweeps whole tables, so nothing stays for the next test.
        connection.execute(text("TRUNCATE users, lists, gift_claims CASCADE"))


@pytest.fixture
def secret() -> str:
    return "a-test-notification-secret"


@pytest.fixture
def client(make_client, secret: str) -> TestClient:
    return make_client(notification_secret=secret)


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(engine: Engine) -> Callable[[], Account]:
    """A user with a live session, its preferences left to their defaults."""

    def make() -> Account:
        with Session(engine) as db, db.begin():
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="Ada")
            db.add(user)
            db.flush()
            token = sessions.create(db, user.id, sessions.utc_now())
            user_id = user.id
        return Account(id=user_id, token=token)

    return make
