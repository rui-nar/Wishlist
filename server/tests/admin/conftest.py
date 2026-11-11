"""Setup for the admin tests.

They run on their own scratch database, like the media tests: migrated to head
once per test run and emptied after each test.
"""

import os
import subprocess
import sys
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User

SERVER_DIR = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)


@pytest.fixture(scope="session")
def admin_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"shushgift_admin_{uuid.uuid4().hex[:12]}"
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
def database_url(admin_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return admin_database_url


@pytest.fixture(scope="session")
def engine(admin_database_url: str) -> Iterator[Engine]:
    engine = create_engine(admin_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    # CASCADE: sessions, entitlements, admin_actions and the rest refer to it.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, admin_actions CASCADE"))


@dataclass(frozen=True)
class Account:
    id: uuid.UUID
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def now() -> datetime:
    """The time of every test app's clock, and the default sign-in time."""
    return NOW


@pytest.fixture
def make_account(engine: Engine) -> Callable[..., Account]:
    """A user with a session created at `signed_in_at`."""

    def make(signed_in_at: datetime = NOW) -> Account:
        with Session(engine) as db, db.begin():
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="U")
            db.add(user)
            db.flush()
            token = sessions.create(db, user.id, signed_in_at)
            user_id = user.id
        return Account(id=user_id, token=token)

    return make


@pytest.fixture
def set_email(engine: Engine) -> Callable[[uuid.UUID, str], None]:
    def set_(user_id: uuid.UUID, email: str) -> None:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE users SET email = :email WHERE id = :id"),
                {"email": email, "id": user_id},
            )

    return set_


@pytest.fixture
def admin(make_account: Callable[..., Account]) -> Account:
    return make_account()


@pytest.fixture
def client(make_client: Callable[..., Any], admin: Account, now: datetime) -> Any:
    """An app whose one admin is `admin`, on the clock `now`."""
    client = make_client(admin_user_ids=str(admin.id))
    client.app.state.clock = lambda: now
    return client
