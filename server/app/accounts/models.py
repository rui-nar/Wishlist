"""The account tables (accounts plan D3).

Keys are random UUIDs, so no identifier reveals how many users exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("language IN ('en', 'fr')", "language"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Copied from the identity provider at each sign-in, for display only: an
    # account is never found by its email (D1).
    email: Mapped[str] = mapped_column(String)
    display_name: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    # The language of their emails, reported by the client (comments plan D17).
    language: Mapped[str] = mapped_column(String(2), server_default="en")
    # On by default (comments plan D18).
    email_notifications: Mapped[bool] = mapped_column(server_default=true())


class UserIdentity(Base):
    """A way to sign in to a user's account: Google now, Apple and email later.

    Its own table so a new provider adds rows, not columns of `users`.
    """

    __tablename__ = "user_identities"
    # The constraint that decides between two concurrent first sign-ins.
    __table_args__ = (UniqueConstraint("provider", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(String)
    # The provider's stable account identifier (Google's `sub` claim).
    subject: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UserSession(Base):
    """A signed-in client (D4). Only the SHA-256 of its token is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
