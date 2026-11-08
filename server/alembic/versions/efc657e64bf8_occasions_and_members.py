"""occasions and members

Occasions a list is shared for, their join tokens, the invitees who joined
them and the people their owners removed (lists plan D4, D5). New tables
only, so the previous release keeps working against it (DevOps plan D15).

Revision ID: efc657e64bf8
Revises: c2b4aa686920
Create Date: 2026-11-08 03:53:35.124260

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "efc657e64bf8"
down_revision: str | Sequence[str] | None = "c2b4aa686920"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "occasions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("list_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("join_token", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["list_id"],
            ["lists.id"],
            name=op.f("fk_occasions_list_id_lists"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_occasions")),
        sa.UniqueConstraint("join_token", name=op.f("uq_occasions_join_token")),
    )
    op.create_index(
        op.f("ix_occasions_list_id"), "occasions", ["list_id"], unique=False
    )
    op.create_table(
        "occasion_members",
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_occasion_members_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_occasion_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "occasion_id", "user_id", name=op.f("pk_occasion_members")
        ),
    )
    op.create_index(
        op.f("ix_occasion_members_user_id"),
        "occasion_members",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "occasion_removals",
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "removed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_occasion_removals_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_occasion_removals_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "occasion_id", "user_id", name=op.f("pk_occasion_removals")
        ),
    )
    op.create_index(
        op.f("ix_occasion_removals_user_id"),
        "occasion_removals",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_occasion_removals_user_id"), table_name="occasion_removals")
    op.drop_table("occasion_removals")
    op.drop_index(op.f("ix_occasion_members_user_id"), table_name="occasion_members")
    op.drop_table("occasion_members")
    op.drop_index(op.f("ix_occasions_list_id"), table_name="occasions")
    op.drop_table("occasions")
