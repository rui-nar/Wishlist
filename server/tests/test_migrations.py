import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text

SERVER_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture
def empty_database_url(database_url: str):
    """A freshly created database, dropped afterwards."""
    name = f"wishlist_migrations_{uuid.uuid4().hex[:12]}"
    admin = create_engine(database_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{name}"'))
        yield (
            make_url(database_url)
            .set(database=name)
            .render_as_string(hide_password=False)
        )
        with admin.connect() as connection:
            connection.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
    finally:
        admin.dispose()


def alembic(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    # The CLI as CI and the image run it, so env.py reads DATABASE_URL itself.
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=SERVER_DIR,
        env=os.environ | {"DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )


def test_upgrade_head_then_check_on_an_empty_database(empty_database_url):
    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr
