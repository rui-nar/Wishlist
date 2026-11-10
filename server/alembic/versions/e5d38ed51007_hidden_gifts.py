"""hidden gifts

Hidden, revealed and received gifts (hidden gifts plan D1, D3, D5): a hidden
or revealed gift has no `list_id` and names its list in `for_list_id`, with
its occasion and author; any gift may be marked received; an occasion keeps
the latest date it had, so moving it earlier never brings a reveal forward.
Every existing row is valid as is: no data migration.

The previous release keeps working against this schema (DevOps plan D15): it
reads gifts by `list_id`, which hidden and revealed gifts do not have, so it
never shows one; received gifts show on the list again during a rollback.

Downgrade loses data: it deletes every hidden and revealed gift (any gift
with no `list_id`), with its claims, before `list_id` becomes required again;
received marks and occasions' latest dates are dropped with their columns.

Revision ID: e5d38ed51007
Revises: 33d8218ddbae
Create Date: 2026-11-09 07:26:49.413300

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d38ed51007"
down_revision: str | Sequence[str] | None = "33d8218ddbae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("gifts", sa.Column("for_list_id", sa.Uuid(), nullable=True))
    op.add_column("gifts", sa.Column("hidden_occasion_id", sa.Uuid(), nullable=True))
    op.add_column("gifts", sa.Column("hidden_by", sa.Uuid(), nullable=True))
    op.add_column(
        "gifts", sa.Column("received_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.alter_column("gifts", "list_id", existing_type=sa.UUID(), nullable=True)
    op.create_index(
        op.f("ix_gifts_for_list_id"), "gifts", ["for_list_id"], unique=False
    )
    op.create_index(op.f("ix_gifts_hidden_by"), "gifts", ["hidden_by"], unique=False)
    op.create_index(
        op.f("ix_gifts_hidden_occasion_id"),
        "gifts",
        ["hidden_occasion_id"],
        unique=False,
    )
    op.create_foreign_key(
        op.f("fk_gifts_hidden_by_users"),
        "gifts",
        "users",
        ["hidden_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_gifts_for_list_id_lists"),
        "gifts",
        "lists",
        ["for_list_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_gifts_hidden_occasion_id_occasions"),
        "gifts",
        "occasions",
        ["hidden_occasion_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        op.f("ck_gifts_list_reference"),
        "gifts",
        "(list_id IS NULL) <> (for_list_id IS NULL)",
    )
    op.create_check_constraint(
        op.f("ck_gifts_hidden_occasion_id"),
        "gifts",
        "hidden_occasion_id IS NULL OR for_list_id IS NOT NULL",
    )
    op.create_check_constraint(
        op.f("ck_gifts_hidden_by"),
        "gifts",
        "hidden_by IS NULL OR for_list_id IS NOT NULL",
    )
    op.add_column("occasions", sa.Column("latest_date", sa.Date(), nullable=True))


def downgrade() -> None:
    # Hidden and revealed gifts cannot be kept: their claims first, then the
    # rows (stated in the docstring).
    op.execute(
        "DELETE FROM gift_claims WHERE gift_id IN"
        " (SELECT id FROM gifts WHERE list_id IS NULL)"
    )
    op.execute("DELETE FROM gifts WHERE list_id IS NULL")
    op.drop_column("occasions", "latest_date")
    op.drop_constraint(op.f("ck_gifts_hidden_by"), "gifts", type_="check")
    op.drop_constraint(op.f("ck_gifts_hidden_occasion_id"), "gifts", type_="check")
    op.drop_constraint(op.f("ck_gifts_list_reference"), "gifts", type_="check")
    op.drop_constraint(
        op.f("fk_gifts_hidden_occasion_id_occasions"), "gifts", type_="foreignkey"
    )
    op.drop_constraint(op.f("fk_gifts_for_list_id_lists"), "gifts", type_="foreignkey")
    op.drop_constraint(op.f("fk_gifts_hidden_by_users"), "gifts", type_="foreignkey")
    op.drop_index(op.f("ix_gifts_hidden_occasion_id"), table_name="gifts")
    op.drop_index(op.f("ix_gifts_hidden_by"), table_name="gifts")
    op.drop_index(op.f("ix_gifts_for_list_id"), table_name="gifts")
    op.alter_column("gifts", "list_id", existing_type=sa.UUID(), nullable=False)
    op.drop_column("gifts", "received_at")
    op.drop_column("gifts", "hidden_by")
    op.drop_column("gifts", "hidden_occasion_id")
    op.drop_column("gifts", "for_list_id")
