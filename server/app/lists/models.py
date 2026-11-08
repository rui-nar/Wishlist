"""The list tables (lists plan D1, D3, D4).

Keys are random UUIDs, as for accounts, so no identifier reveals how many
lists, gifts or occasions exist.
"""

import datetime as dt
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TITLE_MAX_LENGTH = 100
RECIPIENT_NAME_MAX_LENGTH = 100
GIFT_TITLE_MAX_LENGTH = 200
GIFT_DESCRIPTION_MAX_LENGTH = 2000
LINK_MAX_LENGTH = 2048
# numeric(12,2): ten integer digits and two decimals (D3).
PRICE_PRECISION = 12
PRICE_SCALE = 2
OCCASION_NAME_MAX_LENGTH = 100
# Join tokens are secrets.token_urlsafe(16), 22 characters; requests may carry
# up to this many, so a longer value is refused before any lookup (D5).
JOIN_TOKEN_MAX_LENGTH = 64

SELF = "self"
OTHER = "other"


class List(Base):
    """A wish list. Its owners are in `list_owners`, never in a column (D1)."""

    __tablename__ = "lists"
    __table_args__ = (
        CheckConstraint(f"recipient_kind IN ('{SELF}', '{OTHER}')", "recipient_kind"),
        # "For me" has no recipient name; "for someone else" always has one.
        CheckConstraint(
            f"(recipient_kind = '{SELF}' AND recipient_name IS NULL)"
            f" OR (recipient_kind = '{OTHER}' AND recipient_name IS NOT NULL)",
            "recipient_name",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(TITLE_MAX_LENGTH))
    # Chosen at creation and never changed through the API (D2).
    recipient_kind: Mapped[str] = mapped_column(String(5))
    recipient_name: Mapped[str | None] = mapped_column(
        String(RECIPIENT_NAME_MAX_LENGTH)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ListOwner(Base):
    """An owner of a list. One per list today; co-owners are a later plan (D1)."""

    __tablename__ = "list_owners"

    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed on its own: "the lists I own" and account deletion look it up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )


class Gift(Base):
    """A gift wish on a list (D3)."""

    __tablename__ = "gifts"
    __table_args__ = (
        CheckConstraint("price_amount >= 0", "price_amount"),
        # An amount always has its currency, and a currency its amount.
        CheckConstraint(
            "(price_amount IS NULL) = (price_currency IS NULL)", "price_currency"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(GIFT_TITLE_MAX_LENGTH))
    description: Mapped[str] = mapped_column(String(GIFT_DESCRIPTION_MAX_LENGTH))
    # Shop links, in the order the owner gave them.
    links: Mapped[list[str]] = mapped_column(ARRAY(String(LINK_MAX_LENGTH)))
    price_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE)
    )
    price_currency: Mapped[str | None] = mapped_column(String(3))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Occasion(Base):
    """An occasion a list is shared for; invitees belong to it (D4)."""

    __tablename__ = "occasions"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    list_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("lists.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(OCCASION_NAME_MAX_LENGTH))
    # A calendar date, no time of day.
    date: Mapped[dt.date]
    # The share link's token, stored as is so the owner can copy the link
    # again (D5). Null: no link, nobody can join. Shown to owners only.
    join_token: Mapped[str | None] = mapped_column(
        String(JOIN_TOKEN_MAX_LENGTH), unique=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OccasionMember(Base):
    """An invitee of an occasion: someone who joined it by its link (D4, D5)."""

    __tablename__ = "occasion_members"

    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed on its own: "shared with me" looks it up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class OccasionRemoval(Base):
    """Someone an owner removed from an occasion (D4).

    A removal is effective on its own: while the row exists, no link, current
    or old, lets them join again. Allowing them again deletes it; leaving on
    one's own never writes one.
    """

    __tablename__ = "occasion_removals"

    occasion_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("occasions.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed on its own: account deletion cascades through it.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    removed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
