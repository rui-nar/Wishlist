import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, make_url, text

SERVER_DIR = Path(__file__).resolve().parent.parent
HEAD = ScriptDirectory.from_config(
    Config(str(SERVER_DIR / "alembic.ini"))
).get_current_head()
# A revision id no script of this image has: the database is ahead (D13).
FUTURE_REVISION = "ffffffffffff"


@pytest.fixture
def scratch_database_url(database_url: str):
    """A freshly created database, dropped afterwards (as test_migrations.py)."""
    name = f"shushgift_migrate_{uuid.uuid4().hex[:12]}"
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


def migrate(database_url: str) -> subprocess.CompletedProcess[str]:
    # The command the entrypoint runs, from server/ as in the image.
    return subprocess.run(
        [sys.executable, "-m", "app.migrate"],
        cwd=SERVER_DIR,
        env=os.environ | {"DATABASE_URL": database_url},
        capture_output=True,
        text=True,
    )


def versions(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            return list(
                connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalars()
            )
    finally:
        engine.dispose()


def test_an_empty_database_is_upgraded_to_head(scratch_database_url):
    result = migrate(scratch_database_url)

    assert result.returncode == 0, result.stderr
    assert versions(scratch_database_url) == [HEAD]


def test_a_database_at_head_is_left_unchanged(scratch_database_url):
    assert migrate(scratch_database_url).returncode == 0

    result = migrate(scratch_database_url)

    assert result.returncode == 0, result.stderr
    assert "Running upgrade" not in result.stderr
    assert "WARNING" not in result.stderr
    assert versions(scratch_database_url) == [HEAD]


def test_a_database_ahead_of_the_image_starts_without_migrating(
    scratch_database_url,
):
    assert migrate(scratch_database_url).returncode == 0
    engine = create_engine(scratch_database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE alembic_version SET version_num = :revision"),
                {"revision": FUTURE_REVISION},
            )
    finally:
        engine.dispose()

    result = migrate(scratch_database_url)

    assert result.returncode == 0, result.stderr
    warnings = [line for line in result.stderr.splitlines() if "WARNING" in line]
    assert warnings == [
        f"WARNING [app.migrate] database at revision {FUTURE_REVISION}, unknown "
        f"to this image (head {HEAD}): starting without migrating; see "
        "docs/DEPLOYMENT.md Rollback"
    ]
    assert versions(scratch_database_url) == [FUTURE_REVISION]


def test_any_other_failure_exits_non_zero(database_url):
    missing = (
        make_url(database_url)
        .set(database=f"shushgift_missing_{uuid.uuid4().hex[:12]}")
        .render_as_string(hide_password=False)
    )

    result = migrate(missing)

    assert result.returncode != 0
