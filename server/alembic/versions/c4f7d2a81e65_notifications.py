"""notifications

The notification outbox and its deliveries, the users' language and email
switch (comments plan D9, D11, D15, D17, D18); and the claims freed from the
gifts' cascade (D13): the foreign key to `gifts` and the check that an
unbought claim has an occasion go.

Usable by the previous release (DevOps plan D15): new tables, columns with
server defaults, and fewer constraints. It deletes gifts without their claims
then, orphans it cannot see; with no check left, the occasions' `SET NULL`
meets no refusal. Rollback stays image-only.

Revision ID: c4f7d2a81e65
Revises: b7c3e9a14f20
Create Date: 2026-11-09 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4f7d2a81e65"
down_revision: str | Sequence[str] | None = "b7c3e9a14f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notification_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("kind", sa.String(length=17), nullable=False),
        sa.Column("occasion_id", sa.Uuid(), nullable=True),
        sa.Column("gift_id", sa.Uuid(), nullable=True),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "status", sa.String(length=7), server_default="pending", nullable=False
        ),
        sa.Column("reason", sa.String(), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('gift_changed', 'gift_deleted', 'comment_added', "
            "'participants_left', 'gifts_removed')",
            name=op.f("ck_notification_events_kind"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'done', 'failed')",
            name=op.f("ck_notification_events_status"),
        ),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["users.id"],
            name=op.f("fk_notification_events_actor_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notification_events")),
    )
    op.create_index(
        op.f("ix_notification_events_actor_id"),
        "notification_events",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_notification_events_due",
        "notification_events",
        ["next_attempt_at"],
        unique=False,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "email_digests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status", sa.String(length=7), server_default="pending", nullable=False
        ),
        sa.Column("send_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_reason", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'sending', 'sent', 'skipped', 'failed')",
            name=op.f("ck_email_digests_status"),
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_email_digests_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_email_digests_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_email_digests")),
    )
    op.create_index(
        op.f("ix_email_digests_occasion_id"),
        "email_digests",
        ["occasion_id"],
        unique=False,
    )
    op.create_index(
        "ix_email_digests_pending_key",
        "email_digests",
        ["user_id", "occasion_id", "gift_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_email_digests_status_send_after",
        "email_digests",
        ["status", "send_after"],
        unique=False,
    )
    op.create_table(
        "notifications",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("event_id", sa.BigInteger(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("occasion_id", sa.Uuid(), nullable=False),
        sa.Column("gift_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("email_digest_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["email_digest_id"],
            ["email_digests.id"],
            name=op.f("fk_notifications_email_digest_id_email_digests"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["notification_events.id"],
            name=op.f("fk_notifications_event_id_notification_events"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["occasion_id"],
            ["occasions.id"],
            name=op.f("fk_notifications_occasion_id_occasions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_notifications_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_notifications")),
        sa.UniqueConstraint(
            "event_id",
            "user_id",
            "gift_id",
            name=op.f("uq_notifications_event_id_user_id_gift_id"),
        ),
    )
    op.create_index(
        op.f("ix_notifications_email_digest_id"),
        "notifications",
        ["email_digest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_occasion_id"),
        "notifications",
        ["occasion_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_notifications_user_id"), "notifications", ["user_id"], unique=False
    )
    op.add_column(
        "users",
        sa.Column("language", sa.String(length=2), server_default="en", nullable=False),
    )
    op.add_column(
        "users",
        sa.Column(
            "email_notifications",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        op.f("ck_users_language"), "users", "language IN ('en', 'fr')"
    )
    op.drop_constraint(
        op.f("fk_gift_claims_gift_id_gifts"), "gift_claims", type_="foreignkey"
    )
    op.drop_constraint(op.f("ck_gift_claims_occasion_id"), "gift_claims", type_="check")


def downgrade() -> None:
    # Claims of gifts gone, and unbought claims with no occasion: what the
    # restored constraints refuse.
    op.execute(
        "DELETE FROM gift_claims WHERE NOT EXISTS ("
        "SELECT 1 FROM gifts WHERE gifts.id = gift_claims.gift_id)"
    )
    op.execute(
        "DELETE FROM gift_claims WHERE occasion_id IS NULL AND bought_at IS NULL"
    )
    op.create_check_constraint(
        op.f("ck_gift_claims_occasion_id"),
        "gift_claims",
        "occasion_id IS NOT NULL OR bought_at IS NOT NULL",
    )
    op.create_foreign_key(
        op.f("fk_gift_claims_gift_id_gifts"),
        "gift_claims",
        "gifts",
        ["gift_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint(op.f("ck_users_language"), "users", type_="check")
    op.drop_column("users", "email_notifications")
    op.drop_column("users", "language")
    op.drop_index(op.f("ix_notifications_user_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_occasion_id"), table_name="notifications")
    op.drop_index(op.f("ix_notifications_email_digest_id"), table_name="notifications")
    op.drop_table("notifications")
    op.drop_index("ix_email_digests_status_send_after", table_name="email_digests")
    op.drop_index(
        "ix_email_digests_pending_key",
        table_name="email_digests",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(op.f("ix_email_digests_occasion_id"), table_name="email_digests")
    op.drop_table("email_digests")
    op.drop_index(
        "ix_notification_events_due",
        table_name="notification_events",
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.drop_index(
        op.f("ix_notification_events_actor_id"), table_name="notification_events"
    )
    op.drop_table("notification_events")
