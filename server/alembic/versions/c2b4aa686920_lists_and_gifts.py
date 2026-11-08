"""lists and gifts

Lists, their owners and their gifts (lists plan D1, D3). New tables only, so
the previous release keeps working against it (DevOps plan D15).

Revision ID: c2b4aa686920
Revises: 90de0e6d3c85
Create Date: 2026-11-08 03:28:50.801052

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c2b4aa686920"
down_revision: str | Sequence[str] | None = "90de0e6d3c85"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "lists",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=100), nullable=False),
        sa.Column("recipient_kind", sa.String(length=5), nullable=False),
        sa.Column("recipient_name", sa.String(length=100), nullable=True),
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
        sa.CheckConstraint(
            "(recipient_kind = 'self' AND recipient_name IS NULL)"
            " OR (recipient_kind = 'other' AND recipient_name IS NOT NULL)",
            name=op.f("ck_lists_recipient_name"),
        ),
        sa.CheckConstraint(
            "recipient_kind IN ('self', 'other')",
            name=op.f("ck_lists_recipient_kind"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_lists")),
    )
    op.create_table(
        "gifts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=False),
        sa.Column("links", postgresql.ARRAY(sa.String(length=2048)), nullable=False),
        sa.Column("price_amount", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("price_currency", sa.String(length=3), nullable=True),
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
        sa.CheckConstraint(
            "(price_amount IS NULL) = (price_currency IS NULL)",
            name=op.f("ck_gifts_price_currency"),
        ),
        sa.CheckConstraint("price_amount >= 0", name=op.f("ck_gifts_price_amount")),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["lists.id"],
            name=op.f("fk_gifts_list_id_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_gifts")),
    )
    op.create_index(op.f("ix_gifts_list_id"), "gifts", ["list_id"], unique=False)
    op.create_table(
        "list_owners",
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["lists.id"],
            name=op.f("fk_list_owners_list_id_lists"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_list_owners_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("list_id", "user_id", name=op.f("pk_list_owners")),
    )
    op.create_index(
        op.f("ix_list_owners_user_id"), "list_owners", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_list_owners_user_id"), table_name="list_owners")
    op.drop_table("list_owners")
    op.drop_index(op.f("ix_gifts_list_id"), table_name="gifts")
    op.drop_table("gifts")
    op.drop_table("lists")
