"""The claim tables (reserving plan D1, D2).

Invitee activity lives here and nowhere else: claim writes never touch the
gift, list or occasion rows, so nothing an owner reads moves with it (D3).
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.lists.models import PRICE_PRECISION, PRICE_SCALE

RESERVATION = "reservation"
GROUP = "group"


class GiftClaim(Base):
    """A gift being given: reserved by one giver, or a group gift (D1).

    The gift is the key, so a gift has at most one claim across every
    occasion of its list: of two givers claiming it at the same moment, the
    database lets exactly one in, whatever the code does.
    """

    __tablename__ = "gift_claims"
    __table_args__ = (
        CheckConstraint(f"kind IN ('{RESERVATION}', '{GROUP}')", "kind"),
        # Only a bought claim outlives its occasion (D11).
        CheckConstraint(
            "occasion_id IS NOT NULL OR bought_at IS NOT NULL", "occasion_id"
        ),
    )

    gift_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gifts.id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed: an occasion's claims and its deletion look it up.
    occasion_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("occasions.id", ondelete="SET NULL"), index=True
    )
    kind: Mapped[str] = mapped_column(String(11))
    # Null until bought. Bought is final.
    bought_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ClaimParticipant(Base):
    """A giver in a claim: its reserver, or one of a group gift's (D2).

    Only a group gift's participants pledge, each optionally, in the gift's
    currency at the time they pledged (D9).
    """

    __tablename__ = "claim_participants"
    __table_args__ = (
        CheckConstraint("pledge_amount > 0", "pledge_amount"),
        # An amount always has its currency, and a currency its amount.
        CheckConstraint(
            "(pledge_amount IS NULL) = (pledge_currency IS NULL)", "pledge_currency"
        ),
    )

    gift_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gift_claims.gift_id", ondelete="CASCADE"), primary_key=True
    )
    # Indexed on its own: leaving, removal and account deletion look it up.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    pledge_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(PRICE_PRECISION, PRICE_SCALE)
    )
    pledge_currency: Mapped[str | None] = mapped_column(String(3))
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
