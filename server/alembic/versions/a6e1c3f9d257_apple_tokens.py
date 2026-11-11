"""apple tokens

The refresh tokens Apple gives at sign-in, revoked when the account is deleted
(iOS app plan D5).

Usable by the previous release (DevOps plan D15): a new table only, which it
ignores. Rollback stays image-only. A downgrade drops it: the accounts it held
tokens for get one again at their next sign-in, and cannot be revoked until
then.

Revision ID: a6e1c3f9d257
Revises: f3a9c1d7e2b4
Create Date: 2026-11-11 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6e1c3f9d257"
down_revision: str | Sequence[str] | None = "f3a9c1d7e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "apple_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("refresh_token", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_apple_tokens_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "client_id", name=op.f("pk_apple_tokens")),
    )


def downgrade() -> None:
    op.drop_table("apple_tokens")
