"""admin panel

The photo sizes, the audit of admin changes, and the `manual` source of
entitlements (admin panel plan D4, D7, D8).

Usable by the previous release (DevOps plan D15): it ignores the new column
and table, and honours a `manual` entitlement, since what grants premium does
not read the source. Rollback stays image-only. A downgrade deletes the
`manual` rows first, so the narrower CHECKs hold again: an admin's grants are
lost, and the audit and the measured sizes with them.

Revision ID: f3a9c1d7e2b4
Revises: b91e4f27d6c3
Create Date: 2026-11-10 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f3a9c1d7e2b4"
down_revision: str | Sequence[str] | None = "b91e4f27d6c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SOURCE_TABLES = ("entitlements", "billing_customers")
_SOURCES = "source IN ('stripe', 'apple', 'google', 'manual')"
_PREVIOUS_SOURCES = "source IN ('stripe', 'apple', 'google')"


def upgrade() -> None:
    op.add_column("images", sa.Column("bytes", sa.BigInteger(), nullable=True))
    op.create_table(
        "admin_actions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("admin_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("detail", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["admin_user_id"],
            ["users.id"],
            name=op.f("fk_admin_actions_admin_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_admin_actions")),
    )
    op.create_index(
        op.f("ix_admin_actions_admin_user_id"),
        "admin_actions",
        ["admin_user_id"],
        unique=False,
    )
    for table in _SOURCE_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_source"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_source"), table, _SOURCES)


def downgrade() -> None:
    for table in _SOURCE_TABLES:
        op.execute(sa.text(f"DELETE FROM {table} WHERE source = 'manual'"))
        op.drop_constraint(op.f(f"ck_{table}_source"), table, type_="check")
        op.create_check_constraint(op.f(f"ck_{table}_source"), table, _PREVIOUS_SOURCES)
    op.drop_index(op.f("ix_admin_actions_admin_user_id"), table_name="admin_actions")
    op.drop_table("admin_actions")
    op.drop_column("images", "bytes")
