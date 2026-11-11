"""Setup for the media tests.

The pipeline tests (`test_images.py`) need no database. The endpoint tests run
on their own scratch database, like the list tests: migrated to head once per
test run and emptied after each test that uses it.
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
def media_database_url() -> Iterator[str]:
    base_url = os.environ["DATABASE_URL"]
    name = f"shushgift_media_{uuid.uuid4().hex[:12]}"
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
def database_url(media_database_url: str) -> str:
    """Overrides the shared fixture: make_client's apps use the scratch database."""
    return media_database_url


@pytest.fixture(scope="session")
def engine(media_database_url: str) -> Iterator[Engine]:
    engine = create_engine(media_database_url)
    yield engine
    engine.dispose()


@pytest.fixture
def empty_tables(engine: Engine) -> Iterator[None]:
    yield
    # CASCADE: images, gifts and the rest refer to these.
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, lists, images, media_orphans CASCADE"))


@pytest.fixture
def client(make_client, empty_tables) -> TestClient:
    return make_client()


@pytest.fixture
def media_dir(client: TestClient) -> Path:
    return client.app.state.settings.media_dir


@dataclass(frozen=True)
class Account:
    id: str
    name: str
    token: str

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


@pytest.fixture
def make_account(engine: Engine, empty_tables) -> Callable[..., Account]:
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
