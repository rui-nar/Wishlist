"""The account tables (accounts plan D3).

Keys are random UUIDs, so no identifier reveals how many users exist.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

LINK_CREATE = "create"
LINK_RESET = "reset"

LINK_PENDING = "pending"
LINK_SENDING = "sending"
LINK_SENT = "sent"
LINK_SKIPPED = "skipped"
LINK_FAILED = "failed"


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


class PasswordCredential(Base):
    """The password of an account whose identity has provider `email` and the
    normalised address as subject (sign-in plan D3)."""

    __tablename__ = "password_credentials"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class EmailLink(Base):
    """A link mailed to an address to create an account or reset a password
    (sign-in plan D3). Not tied to `users`: it exists before any account does,
    so an unverified address never reaches `users` (D2)."""

    __tablename__ = "email_links"
    __table_args__ = (
        CheckConstraint("language IN ('en', 'fr')", "language"),
        CheckConstraint(f"purpose IN ('{LINK_CREATE}', '{LINK_RESET}')", "purpose"),
        CheckConstraint(
            f"status IN ('{LINK_PENDING}', '{LINK_SENDING}', '{LINK_SENT}', "
            f"'{LINK_SKIPPED}', '{LINK_FAILED}')",
            "status",
        ),
        # The worker's next batch, as for the digests.
        Index("ix_email_links_status_created_at", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Normalised (D4). Indexed: a used link ends the address's others (D9), and
    # deleting an account deletes them.
    address: Mapped[str] = mapped_column(String, index=True)
    purpose: Mapped[str] = mapped_column(String(6))
    language: Mapped[str] = mapped_column(String(2))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(7), server_default=LINK_PENDING)
    # When a worker took it to send.
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(server_default="0")
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthThrottle(Base):
    """One counter of the sign-in limits (sign-in plan D12): only the hash of
    what it counts, so no address or IP is stored."""

    __tablename__ = "auth_throttle"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int]


class AppleToken(Base):
    """The refresh token Apple gave for an account's sign-in to one client ID,
    revoked when the account is deleted (iOS app plan D5). A secret: never
    logged, and emptied on VAL when it is seeded from PROD."""

    __tablename__ = "apple_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    # The Services ID or a bundle ID: Apple revokes a token only for its own.
    client_id: Mapped[str] = mapped_column(String, primary_key=True)
    refresh_token: Mapped[str] = mapped_column(String)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
