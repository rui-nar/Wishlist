"""The comment and follow tables (comments plan D1, D4).

Both key on a gift id with no foreign key to `gifts` (D13): a thread is "the
comments of (occasion, gift)", and a gift deleted or replaced takes its
thread out of reach through `giving_gift`, whose 404 answers every route.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

COMMENT_MAX_LENGTH = 2000


class Comment(Base):
    """A comment of a thread: a gift in one occasion (D1)."""

    __tablename__ = "comments"
    __table_args__ = (
        # A thread reads oldest first (D5).
        Index("ix_comments_thread", "occasion_id", "gift_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE")
    )
    gift_id: Mapped[uuid.UUID]
    # Its author; null once their account is deleted (D3).
    author_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    body: Mapped[str] = mapped_column(String(COMMENT_MAX_LENGTH))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Null until edited.
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GiftFollow(Base):
    """Whether a giver follows a gift of an occasion (D4).

    The row is kept with `following = false` on an explicit unfollow: a
    later comment or pledge does not follow again, the person said stop.
    """

    __tablename__ = "gift_follows"

    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), primary_key=True
    )
    gift_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    # Indexed on its own: leaving and account deletion look it up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    following: Mapped[bool]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
