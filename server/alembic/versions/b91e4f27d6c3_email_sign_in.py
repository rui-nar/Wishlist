"""email sign-in

The password credentials, the email links and the sign-in limits (sign-in plan
D3).

Usable by the previous release (DevOps plan D15): new tables only, which it
ignores. Rollback stays image-only. A downgrade drops all three: email accounts
could then no longer sign in, and their other rows stay.

Revision ID: b91e4f27d6c3
Revises: d8a3f6b2c914
Create Date: 2026-11-10 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b91e4f27d6c3"
down_revision: str | Sequence[str] | None = "d8a3f6b2c914"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_password_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_password_credentials")),
    )
    op.create_table(
        "email_links",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("address", sa.String(), nullable=False),
        sa.Column("purpose", sa.String(length=6), nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status", sa.String(length=7), server_default="pending", nullable=False
        ),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "language IN ('en', 'fr')", name=op.f("ck_email_links_language")
        ),
        sa.CheckConstraint(
            "purpose IN ('create', 'reset')", name=op.f("ck_email_links_purpose")
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'skipped', 'failed')",
            name=op.f("ck_email_links_status"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_links")),
    )
    op.create_index(
        op.f("ix_email_links_address"), "email_links", ["address"], unique=False
    )
    op.create_index(
        "ix_email_links_status_created_at",
        "email_links",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "auth_throttle",
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key_hash", name=op.f("pk_auth_throttle")),
    )


def downgrade() -> None:
    op.drop_table("auth_throttle")
    op.drop_index("ix_email_links_status_created_at", table_name="email_links")
    op.drop_index(op.f("ix_email_links_address"), table_name="email_links")
    op.drop_table("email_links")
    op.drop_table("password_credentials")
