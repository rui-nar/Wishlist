"""google tokens

`entitlements.external_id` widened to text: a Google Play purchase token can
be longer than 255 characters (Android release plan D6, review R1-5).

Usable by the previous release (DevOps plan D15): it reads and writes the
column as a string, whatever its length limit. Rollback stays image-only. A
downgrade deletes the rows whose id no longer fits, Google purchases only,
so the narrower column holds again: Google remains the source of each, and
the app's next report or notification records it once upgraded again.

Revision ID: c7e2f9a4d531
Revises: a6e1c3f9d257
Create Date: 2026-11-11 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2f9a4d531"
down_revision: str | Sequence[str] | None = "a6e1c3f9d257"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "entitlements",
        "external_id",
        existing_type=sa.String(length=255),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM entitlements WHERE length(external_id) > 255"))
    op.alter_column(
        "entitlements",
        "external_id",
        existing_type=sa.Text(),
        type_=sa.String(length=255),
        existing_nullable=False,
    )
