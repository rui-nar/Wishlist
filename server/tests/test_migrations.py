import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, make_url, text
from sqlalchemy.exc import IntegrityError

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


def _insert_a_purchase(connection, user: uuid.UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO entitlements (id, user_id, source, external_id, status,"
            " cancel_at_period_end, read_at)"
            " VALUES (:id, :user, 'stripe', :external, 'active', false, now())"
        ),
        {"id": uuid.uuid4(), "user": user, "external": f"sub_{user}"},
    )
    connection.execute(
        text(
            "INSERT INTO billing_customers (user_id, source, customer_id)"
            " VALUES (:user, 'stripe', :customer)"
        ),
        {"user": user, "customer": f"cus_{user}"},
    )


def _insert_user(connection, user: uuid.UUID) -> None:
    connection.execute(
        text("INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'U')"),
        {"id": user, "email": f"{user}@example.com"},
    )


def test_the_billing_revision_upgrades_and_downgrades_with_rows_present(
    empty_database_url,
):
    """Premium plan, Boundaries crossed: new tables only, so an account made
    before the revision stays through it, and a downgrade loses only them."""
    before = alembic(empty_database_url, "upgrade", "c4f7d2a81e65")
    assert before.returncode == 0, before.stderr
    user = uuid.uuid4()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_user(connection, user)
    engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_a_purchase(connection, user)
    engine.dispose()

    downgrade = alembic(empty_database_url, "downgrade", "c4f7d2a81e65")
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert connection.scalar(text("SELECT to_regclass('entitlements')")) is None
            assert (
                connection.scalar(text("SELECT to_regclass('billing_customers')"))
                is None
            )
    finally:
        engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr


def test_deleting_an_account_deletes_its_purchases_and_no_others(empty_database_url):
    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    deleted, kept = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            for user in (deleted, kept):
                _insert_user(connection, user)
                _insert_a_purchase(connection, user)

            connection.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": deleted}
            )

        with engine.connect() as connection:
            for table in ("entitlements", "billing_customers"):
                owners = connection.scalars(text(f"SELECT user_id FROM {table}"))
                assert list(owners) == [kept]
    finally:
        engine.dispose()


SIGN_IN_TABLES = ("password_credentials", "email_links", "auth_throttle")


def _insert_sign_in_rows(connection, user: uuid.UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO password_credentials (user_id, password_hash, updated_at)"
            " VALUES (:user, 'hash', now())"
        ),
        {"user": user},
    )
    connection.execute(
        text(
            "INSERT INTO email_links (id, address, purpose, language, created_at,"
            " expires_at) VALUES (:id, :address, 'create', 'en', now(), now())"
        ),
        {"id": uuid.uuid4(), "address": f"{user}@example.com"},
    )
    connection.execute(
        text(
            "INSERT INTO auth_throttle (key_hash, window_started_at, count)"
            " VALUES (:key, now(), 1)"
        ),
        {"key": user.hex},
    )


def test_the_email_sign_in_revision_upgrades_and_downgrades_with_rows_present(
    empty_database_url,
):
    """Sign-in plan, Boundaries crossed: new tables only, so an account made
    before the revision stays through it, and a downgrade loses only them."""
    before = alembic(empty_database_url, "upgrade", "d8a3f6b2c914")
    assert before.returncode == 0, before.stderr
    user = uuid.uuid4()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_user(connection, user)
    engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_sign_in_rows(connection, user)
    engine.dispose()

    downgrade = alembic(empty_database_url, "downgrade", "d8a3f6b2c914")
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            for table in SIGN_IN_TABLES:
                assert connection.scalar(text(f"SELECT to_regclass('{table}')")) is None
    finally:
        engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr


def test_deleting_an_account_deletes_its_password_and_no_others(empty_database_url):
    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    deleted, kept = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            for user in (deleted, kept):
                _insert_user(connection, user)
                _insert_sign_in_rows(connection, user)

            connection.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": deleted}
            )

        with engine.connect() as connection:
            owners = connection.scalars(
                text("SELECT user_id FROM password_credentials")
            )
            assert list(owners) == [kept]
    finally:
        engine.dispose()


def test_the_comments_revision_makes_claim_holders_follow_their_gifts(
    empty_database_url,
):
    """Review R7-1: every participant of a claim with an occasion follows its
    gift, and nobody else does: not the owner, not an invitee with no claim,
    not the buyer of a gift whose occasion was deleted."""
    before = alembic(empty_database_url, "upgrade", "e5d38ed51007")
    assert before.returncode == 0, before.stderr
    owner, invitee, reserver, pledger, joiner, buyer = (uuid.uuid4() for _ in range(6))
    list_id, occasion, reserved, group, bought = (uuid.uuid4() for _ in range(5))
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, email, display_name) VALUES (:id, :email, 'U')"
            ),
            [
                {"id": user, "email": f"{user}@example.com"}
                for user in (owner, invitee, reserver, pledger, joiner, buyer)
            ],
        )
        connection.execute(
            text(
                "INSERT INTO lists (id, title, recipient_kind)"
                " VALUES (:id, 'L', 'self')"
            ),
            {"id": list_id},
        )
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": list_id, "user": owner},
        )
        connection.execute(
            text(
                "INSERT INTO occasions (id, list_id, name, date)"
                " VALUES (:id, :list, 'O', '2099-12-25')"
            ),
            {"id": occasion, "list": list_id},
        )
        connection.execute(
            text(
                "INSERT INTO occasion_members (occasion_id, user_id)"
                " VALUES (:occasion, :user)"
            ),
            [
                {"occasion": occasion, "user": user}
                for user in (invitee, reserver, pledger, joiner)
            ],
        )
        connection.execute(
            text(
                "INSERT INTO gifts (id, list_id, title, description, links)"
                " VALUES (:id, :list, 'G', '', '{}')"
            ),
            [{"id": gift, "list": list_id} for gift in (reserved, group, bought)],
        )
        connection.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind, bought_at)"
                " VALUES (:reserved, :occasion, 'reservation', NULL),"
                " (:group, :occasion, 'group', NULL),"
                " (:bought, NULL, 'reservation', now())"
            ),
            {
                "reserved": reserved,
                "group": group,
                "bought": bought,
                "occasion": occasion,
            },
        )
        connection.execute(
            text(
                "INSERT INTO claim_participants (gift_id, user_id)"
                " VALUES (:gift, :user)"
            ),
            [
                {"gift": reserved, "user": reserver},
                {"gift": group, "user": pledger},
                {"gift": group, "user": joiner},
                {"gift": bought, "user": buyer},
            ],
        )
    engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            follows = connection.execute(
                text(
                    "SELECT occasion_id, gift_id, user_id, following FROM gift_follows"
                )
            )
            assert {tuple(row) for row in follows} == {
                (occasion, reserved, reserver, True),
                (occasion, group, pledger, True),
                (occasion, group, joiner, True),
            }
    finally:
        engine.dispose()
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr


def test_the_comments_revision_follows_nothing_when_nothing_is_claimed(
    empty_database_url,
):
    before = alembic(empty_database_url, "upgrade", "e5d38ed51007")
    assert before.returncode == 0, before.stderr

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM gift_follows")) == 0
    finally:
        engine.dispose()


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


def test_the_admin_panel_revision_upgrades_and_downgrades_with_a_manual_row(
    empty_database_url,
):
    """Admin panel plan, Boundaries crossed: an image made before the revision
    gets a null size, a `manual` entitlement is accepted, and a downgrade
    deletes the `manual` rows only, so the narrower CHECKs hold again."""
    before = alembic(empty_database_url, "upgrade", "b91e4f27d6c3")
    assert before.returncode == 0, before.stderr
    user, image = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_user(connection, user)
        _insert_a_purchase(connection, user)
        connection.execute(
            text(
                "INSERT INTO images (id, uploaded_by, width, height)"
                " VALUES (:id, :user, 10, 10)"
            ),
            {"id": image, "user": user},
        )
    engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT bytes FROM images")) is None
        connection.execute(
            text(
                "INSERT INTO entitlements (id, user_id, source, external_id, status,"
                " period_end, cancel_at_period_end, read_at) VALUES (:id, :user,"
                " 'manual', :external, 'active', now() + interval '1 year', false,"
                " now())"
            ),
            {"id": uuid.uuid4(), "user": user, "external": str(uuid.uuid4())},
        )
        connection.execute(
            text(
                "INSERT INTO admin_actions (id, admin_user_id, action,"
                " target_user_id, detail) VALUES (:id, :user, 'grant_premium',"
                " :user, '{}')"
            ),
            {"id": uuid.uuid4(), "user": user},
        )
    engine.dispose()

    downgrade = alembic(empty_database_url, "downgrade", "b91e4f27d6c3")
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            sources = connection.scalars(text("SELECT source FROM entitlements"))
            assert list(sources) == ["stripe"]
            assert connection.scalar(text("SELECT count(*) FROM images")) == 1
            assert (
                connection.scalar(text("SELECT to_regclass('admin_actions')")) is None
            )
            column = connection.scalar(
                text(
                    "SELECT count(*) FROM information_schema.columns"
                    " WHERE table_name = 'images' AND column_name = 'bytes'"
                )
            )
            assert column == 0
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO billing_customers (user_id, source, customer_id)"
                    " VALUES (:user, 'manual', 'x')"
                ),
                {"user": user},
            )
    finally:
        engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr


def _insert_an_apple_token(connection, user: uuid.UUID) -> None:
    connection.execute(
        text(
            "INSERT INTO apple_tokens (user_id, client_id, refresh_token, updated_at)"
            " VALUES (:user, 'com.example.wishlist', :token, now())"
        ),
        {"user": user, "token": f"r{user.hex}"},
    )


def test_the_apple_tokens_revision_upgrades_and_downgrades_with_rows_present(
    empty_database_url,
):
    """iOS app plan, Boundaries crossed: a new table only, so an account made
    before the revision stays through it, and a downgrade loses only it."""
    before = alembic(empty_database_url, "upgrade", "f3a9c1d7e2b4")
    assert before.returncode == 0, before.stderr
    user = uuid.uuid4()
    engine = create_engine(empty_database_url)
    with engine.begin() as connection:
        _insert_user(connection, user)
    engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            _insert_an_apple_token(connection, user)
        # One per account and client.
        with pytest.raises(IntegrityError), engine.begin() as connection:
            _insert_an_apple_token(connection, user)
    finally:
        engine.dispose()

    downgrade = alembic(empty_database_url, "downgrade", "f3a9c1d7e2b4")
    assert downgrade.returncode == 0, downgrade.stderr

    engine = create_engine(empty_database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM users")) == 1
            assert connection.scalar(text("SELECT to_regclass('apple_tokens')")) is None
    finally:
        engine.dispose()

    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    check = alembic(empty_database_url, "check")
    assert check.returncode == 0, check.stderr


def test_deleting_an_account_deletes_its_apple_tokens_and_no_others(
    empty_database_url,
):
    upgrade = alembic(empty_database_url, "upgrade", "head")
    assert upgrade.returncode == 0, upgrade.stderr
    deleted, kept = uuid.uuid4(), uuid.uuid4()
    engine = create_engine(empty_database_url)
    try:
        with engine.begin() as connection:
            for user in (deleted, kept):
                _insert_user(connection, user)
                _insert_an_apple_token(connection, user)

            connection.execute(
                text("DELETE FROM users WHERE id = :id"), {"id": deleted}
            )

        with engine.connect() as connection:
            owners = connection.scalars(text("SELECT user_id FROM apple_tokens"))
            assert list(owners) == [kept]
    finally:
        engine.dispose()
