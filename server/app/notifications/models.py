"""The notification tables (comments plan D9, D11, D15).

An event says what happened, written in the transaction that caused it. A
notification says who is told, written later by the worker. Each email digest
groups a person's notifications about a gift. None has a foreign key to
`gifts` (D13): the worker reads these after the gift has gone.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

GIFT_CHANGED = "gift_changed"
GIFT_DELETED = "gift_deleted"
COMMENT_ADDED = "comment_added"
PARTICIPANTS_LEFT = "participants_left"
GIFTS_REMOVED = "gifts_removed"

_PENDING = "pending"
_DUE = text(f"status = '{_PENDING}'")


class NotificationEvent(Base):
    """Something that happened, in the outbox: inserted by the request that
    caused it, in its transaction, so it exists if and only if its cause
    committed (D9). The payload holds no personal data: names are read at
    send time."""

    __tablename__ = "notification_events"
    __table_args__ = (
        CheckConstraint(
            f"kind IN ('{GIFT_CHANGED}', '{GIFT_DELETED}', '{COMMENT_ADDED}', "
            f"'{PARTICIPANTS_LEFT}', '{GIFTS_REMOVED}')",
            "kind",
        ),
        CheckConstraint(f"status IN ('{_PENDING}', 'done', 'failed')", "status"),
        # The worker's next batch (D16).
        Index("ix_notification_events_due", "next_attempt_at", postgresql_where=_DUE),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    kind: Mapped[str] = mapped_column(String(17))
    occasion_id: Mapped[uuid.UUID | None]
    gift_id: Mapped[uuid.UUID | None]
    # Null once their account is deleted, so a name is never sent afterwards
    # (D14). Indexed: that deletion looks it up.
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    status: Mapped[str] = mapped_column(String(7), server_default=_PENDING)
    # A fixed word, why it ended as it did (D9, D11).
    reason: Mapped[str | None] = mapped_column(String)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class EmailDigest(Base):
    """The email that groups a person's notifications about a gift in an
    occasion (D15). At most one is pending for each."""

    __tablename__ = "email_digests"
    __table_args__ = (
        CheckConstraint(
            f"status IN ('{_PENDING}', 'sending', 'sent', 'skipped', 'failed')",
            "status",
        ),
        Index(
            "ix_email_digests_pending_key",
            "user_id",
            "occasion_id",
            "gift_id",
            unique=True,
            postgresql_where=_DUE,
        ),
        Index("ix_email_digests_status_send_after", "status", "send_after"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE")
    )
    # Indexed: deleting an occasion looks it up.
    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), index=True
    )
    gift_id: Mapped[uuid.UUID]
    status: Mapped[str] = mapped_column(String(7), server_default=_PENDING)
    send_after: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(server_default="0")
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When a worker took it to send.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # A fixed word (D15).
    skip_reason: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Notification(Base):
    """This happened, for this person, about this gift in this occasion:
    whatever channel delivers it (D11).

    Fanning an event out twice inserts nothing twice. The gift is part of
    that key: an event listing several gifts tells one person of each.
    """

    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("event_id", "user_id", "gift_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    event_id: Mapped[int] = mapped_column(
        ForeignKey("notification_events.id", ondelete="CASCADE")
    )
    # Indexed, as the two below: deleting each of them looks it up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), index=True
    )
    gift_id: Mapped[uuid.UUID]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    email_digest_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("email_digests.id", ondelete="SET NULL"), index=True
    )
