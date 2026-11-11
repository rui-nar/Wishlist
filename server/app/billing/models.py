"""The purchase tables (premium plan D1).

An entitlement is one purchase, from any source: nothing here knows a
provider, and premium is computed from these rows, never stored (D2, D3).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

STRIPE = "stripe"
APPLE = "apple"
GOOGLE = "google"
# Granted by an admin (admin panel plan D8): no provider stands behind it, and
# its `external_id` is a new uuid.
MANUAL = "manual"

ACTIVE = "active"
PAST_DUE = "past_due"
INCOMPLETE = "incomplete"
ENDED = "ended"

_SOURCES = f"source IN ('{STRIPE}', '{APPLE}', '{GOOGLE}', '{MANUAL}')"


class Entitlement(Base):
    """One purchase: a Stripe subscription, a store's subscription, or an
    admin's grant."""

    __tablename__ = "entitlements"
    __table_args__ = (
        CheckConstraint(_SOURCES, "source"),
        CheckConstraint(
            f"status IN ('{ACTIVE}', '{PAST_DUE}', '{INCOMPLETE}', '{ENDED}')",
            "status",
        ),
        UniqueConstraint("source", "external_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(6))
    # The Stripe subscription id, Apple's original transaction id or Google's
    # purchase token, which can be longer than 255 characters (Android release
    # plan D6, review R1-5).
    external_id: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(10))
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_at_period_end: Mapped[bool]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When this state was read from the provider (D13): an older read never
    # overwrites a newer one.
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # The consent proof (D12).
    terms_accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    terms_version: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class BillingCustomer(Base):
    """A person's customer at a provider, which exists before any purchase
    (D12)."""

    __tablename__ = "billing_customers"
    __table_args__ = (
        CheckConstraint(_SOURCES, "source"),
        UniqueConstraint("source", "customer_id"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    source: Mapped[str] = mapped_column(String(6), primary_key=True)
    customer_id: Mapped[str] = mapped_column(String(255))
