"""The image tables (gift images plan D2).

An image row is the only way to a file: files are named by the row's id
(D3), and the purge keeps a file as long as a row has its id (D9).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# A file stem is an image id's hex (D3).
STEM_LENGTH = 32


class Image(Base):
    """An uploaded image, processed and stored as two files (D3, D4).

    Pending while `attached_at` is null: readable by its uploader only and
    attachable to a gift. Once attached, `attached_at` is never cleared, so an
    image no gift points at any more is detached, not pending again (review
    R1-6).
    """

    __tablename__ = "images"

    # Random, also the file name (D3).
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # SET NULL, not CASCADE: an image a co-owner uploaded stays on the gift
    # when that co-owner deletes their account (D2).
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    # Of the full version.
    width: Mapped[int]
    height: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # Set when first attached to a gift, never cleared (review R1-6).
    attached_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class MediaOrphan(Base):
    """A file stem with no image row, and since when: the purge's memory (D9)."""

    __tablename__ = "media_orphans"

    name: Mapped[str] = mapped_column(String(STEM_LENGTH), primary_key=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
