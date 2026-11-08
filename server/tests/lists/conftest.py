"""Setup for the list tests.

Like the account tests, they run on their own scratch database, migrated to
head once per test run and emptied after each test. Users are created directly
in the database with a session each: how they signed in is the account tests'
business, not these.
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
def lists_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"wishlist_lists_{uuid.uuid4().hex[:12]}"
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
def database_url(lists_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return lists_database_url


@pytest.fixture(scope="session")
def engine(lists_database_url: str) -> Iterator[Engine]:
    engine = create_engine(lists_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    # CASCADE empties every table that refers to these, including the ones
    # later plans add under lists.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, lists CASCADE"))


@pytest.fixture
def client(make_client) -> TestClient:
    return make_client()


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(engine: Engine) -> Callable[..., Account]:
    """A user with a live session."""

    def make(name: str = "Ada") -> Account:
        with Session(engine) as db, db.begin():
            user = User(email=f"{uuid.uuid4().hex}@example.com", display_name=name)
            db.add(user)
            db.flush()
            token = sessions.create(db, user.id, sessions.utc_now())
            user_id = str(user.id)
        return Account(id=user_id, name=name, token=token)

    return make


@pytest.fixture
def rows(engine: Engine) -> Callable[..., int]:
    """How many rows of a table match `column = value`, or all its rows."""

    def rows(table: str, column: str | None = None, value: object = None) -> int:
        where = f" WHERE {column} = :value" if column else ""
        with engine.connect() as connection:
            return connection.scalar(
                text(f"SELECT count(*) FROM {table}{where}"), {"value": value}
            )

    return rows
