"""The answers of the billing routes (premium plan D11)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.billing.google_events import MAX_TOKEN_LENGTH

Plan = Literal["free", "premium"]

# A signed transaction is a few KiB: its three certificates and its claims.
MAX_SIGNED_LENGTH = 64 * 1024
SubscriptionStatus = Literal["active", "past_due", "canceling"]


class Limits(BaseModel):
    # Null for premium: no limit.
    max_lists: int | None
    max_gifts_per_list: int | None


class Offer(BaseModel):
    amount: str
    currency: str
    interval: Literal["year"]


class AppleOffer(BaseModel):
    """What the iOS app sells (Apple IAP plan D7): the price is StoreKit's."""

    product_id: str


class GoogleOffer(BaseModel):
    """What the Android app sells (Android release plan D7): the price is
    Play's."""

    product_id: str


class LegalLinks(BaseModel):
    terms_url: str | None
    privacy_url: str | None
    withdrawal_url: str | None


class BillingStatus(BaseModel):
    plan: Plan
    source: str | None
    status: SubscriptionStatus | None
    renews_at: datetime | None
    ends_at: datetime | None
    limits: Limits
    enforced: bool
    # Stripe's, for the web and Android.
    offer: Offer | None
    # Apple's, for the iOS app (Apple IAP plan D7).
    apple_offer: AppleOffer | None
    # An Apple subscription may still charge, which only the person can stop
    # (D9): the deletion warns of it.
    apple_renewing: bool
    # Google Play's, for the Android app (Android release plan D7).
    google_offer: GoogleOffer | None
    # A Google subscription may still charge: the deletion cancels it first,
    # and warns of it where it cannot.
    google_renewing: bool
    can_manage: bool
    legal: LegalLinks


class SessionUrl(BaseModel):
    url: str


class AppleTransactionReport(BaseModel):
    """A StoreKit transaction as the iOS app got it (D3), signed by Apple."""

    signed_transaction: str = Field(min_length=1, max_length=MAX_SIGNED_LENGTH)


class GooglePurchaseReport(BaseModel):
    """A Play Billing purchase as the Android app got it (D6): its token,
    which only points at the purchase."""

    purchase_token: str = Field(min_length=1, max_length=MAX_TOKEN_LENGTH)


class BillingRefusal(BaseModel):
    detail: str
    code: str
