"""reserving

Gift claims and their participants: reservations, group gifts and pledges
(reserving plan D1, D2). New tables only, so the previous release keeps
working against it (DevOps plan D15).

Revision ID: 33d8218ddbae
Revises: 655e9747d91f
Create Date: 2026-11-08 20:37:35.231996

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "33d8218ddbae"
down_revision: str | Sequence[str] | None = "655e9747d91f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "gift_claims",
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column("occasion_id", sa.Uuid(), nullable=True),
        sa.Column("kind", sa.String(length=11), nullable=False),
        sa.Column("bought_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('reservation', 'group')", name=op.f("ck_gift_claims_kind")
        ),
        sa.CheckConstraint(
            "occasion_id IS NOT NULL OR bought_at IS NOT NULL",
            name=op.f("ck_gift_claims_occasion_id"),
        ),
        sa.ForeignKeyConstraint(
            ["gift_id"],
            ["gifts.id"],
            name=op.f("fk_gift_claims_gift_id_gifts"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_gift_claims_occasion_id_occasions"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("gift_id", name=op.f("pk_gift_claims")),
    )
    op.create_index(
        op.f("ix_gift_claims_occasion_id"), "gift_claims", ["occasion_id"], unique=False
    )
    op.create_table(
        "claim_participants",
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("pledge_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("pledge_currency", sa.String(length=3), nullable=True),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(pledge_amount IS NULL) = (pledge_currency IS NULL)",
            name=op.f("ck_claim_participants_pledge_currency"),
        ),
        sa.CheckConstraint(
            "pledge_amount > 0", name=op.f("ck_claim_participants_pledge_amount")
        ),
        sa.ForeignKeyConstraint(
            ["gift_id"],
            ["gift_claims.gift_id"],
            name=op.f("fk_claim_participants_gift_id_gift_claims"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_claim_participants_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "gift_id", "user_id", name=op.f("pk_claim_participants")
        ),
    )
    op.create_index(
        op.f("ix_claim_participants_user_id"),
        "claim_participants",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_claim_participants_user_id"), table_name="claim_participants"
    )
    op.drop_table("claim_participants")
    op.drop_index(op.f("ix_gift_claims_occasion_id"), table_name="gift_claims")
    op.drop_table("gift_claims")
