"""comments

Comment threads and following under a gift of an occasion (comments plan D1,
D4). New tables only, so the previous release keeps working against it
(DevOps plan D15).

Revision ID: b7c3e9a14f20
Revises: e5d38ed51007
Create Date: 2026-11-09 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7c3e9a14f20"
down_revision: str | Sequence[str] | None = "e5d38ed51007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "comments",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=True),
        sa.Column("body", sa.String(length=2000), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_comments_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["author_id"],
            ["users.id"],
            name=op.f("fk_comments_author_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_comments")),
    )
    op.create_index(
        op.f("ix_comments_author_id"), "comments", ["author_id"], unique=False
    )
    op.create_index(
        "ix_comments_thread",
        "comments",
        ["occasion_id", "gift_id", "created_at"],
        unique=False,
    )
    op.create_table(
        "gift_follows",
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("following", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_gift_follows_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_gift_follows_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "occasion_id", "gift_id", "user_id", name=op.f("pk_gift_follows")
        ),
    )
    op.create_index(
        op.f("ix_gift_follows_user_id"), "gift_follows", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_gift_follows_user_id"), table_name="gift_follows")
    op.drop_table("gift_follows")
    op.drop_index("ix_comments_thread", table_name="comments")
    op.drop_index(op.f("ix_comments_author_id"), table_name="comments")
    op.drop_table("comments")
