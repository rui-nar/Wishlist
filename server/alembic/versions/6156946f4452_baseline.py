"""baseline

The empty root every later migration descends from: no tables.

Revision ID: 6156946f4452
Revises:
Create Date: 2026-11-07 21:31:39.693479

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "6156946f4452"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
