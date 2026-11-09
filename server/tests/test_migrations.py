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


def test_downgrading_the_notifications_revision_clears_what_it_allowed(
    empty_database_url,
):
    """Comments plan, Boundaries crossed: orphaned claims and unbought claims
    with no occasion are deleted, the foreign key and the check restored, and
    a bought claim with no occasion, valid in both, stays."""
    assert alembic(empty_database_url, "upgrade", "head").returncode == 0
    orphan, unbought, bought = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    list_id = uuid.uuid4()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO lists (id, title, recipient_kind)"
                " VALUES (:id, 'L', 'self')"
            ),
            {"id": list_id},
        )
        connection.execute(
            text(
                "INSERT INTO gifts (id, list_id, title, description, links)"
                " VALUES (:unbought, :list, 'U', '', '{}'),"
                " (:bought, :list, 'B', '', '{}')"
            ),
            {"unbought": unbought, "bought": bought, "list": list_id},
        )
        connection.execute(
            text(
                "INSERT INTO gift_claims (gift_id, kind, bought_at) VALUES"
                " (:orphan, 'reservation', now()),"
                " (:unbought, 'reservation', NULL),"
                " (:bought, 'reservation', now())"
            ),
            {"orphan": orphan, "unbought": unbought, "bought": bought},
        )
    engine.dispose()

    downgrade = alembic(empty_database_url, "downgrade", "b7c3e9a14f20")
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            remaining = connection.scalars(text("SELECT gift_id FROM gift_claims"))
            assert list(remaining) == [bought]
            restored = connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint WHERE conname IN"
                    " ('fk_gift_claims_gift_id_gifts', 'ck_gift_claims_occasion_id')"
                    " ORDER BY conname"
                )
            )
            assert list(restored) == [
                "ck_gift_claims_occasion_id",
                "fk_gift_claims_gift_id_gifts",
            ]
            tables = connection.scalar(
                text("SELECT to_regclass('notification_events') IS NULL")
            )
            assert tables is True
    finally:
        engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr
