"""billing

The purchases and the providers' customers (premium plan D1).

Usable by the previous release (DevOps plan D15): new tables only, which it
ignores. Rollback stays image-only. A downgrade drops both, losing the local
status and consent records; Stripe remains the source of both.

Revision ID: d8a3f6b2c914
Revises: c4f7d2a81e65
Create Date: 2026-11-10 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8a3f6b2c914"
down_revision: str | Sequence[str] | None = "c4f7d2a81e65"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCES = "source IN ('stripe', 'apple', 'google')"


def upgrade() -> None:
    op.create_table(
        "entitlements",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=6), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=10), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("terms_accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terms_version", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_SOURCES, name=op.f("ck_entitlements_source")),
        sa.CheckConstraint(
            "status IN ('active', 'past_due', 'incomplete', 'ended')",
            name=op.f("ck_entitlements_status"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_entitlements_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entitlements")),
        sa.UniqueConstraint(
            "source",
            "external_id",
            name=op.f("uq_entitlements_source_external_id"),
        ),
    )
    op.create_index(
        op.f("ix_entitlements_user_id"), "entitlements", ["user_id"], unique=False
    )
    op.create_table(
        "billing_customers",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.String(length=6), nullable=False),
        sa.Column("customer_id", sa.String(length=255), nullable=False),
        sa.CheckConstraint(_SOURCES, name=op.f("ck_billing_customers_source")),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_billing_customers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "source", name=op.f("pk_billing_customers")),
        sa.UniqueConstraint(
            "source",
            "customer_id",
            name=op.f("uq_billing_customers_source_customer_id"),
        ),
    )


def downgrade() -> None:
    op.drop_table("billing_customers")
    op.drop_index(op.f("ix_entitlements_user_id"), table_name="entitlements")
    op.drop_table("entitlements")
