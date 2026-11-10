"""The answers of the billing routes (premium plan D11)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Plan = Literal["free", "premium"]
SubscriptionStatus = Literal["active", "past_due", "canceling"]


class Limits(BaseModel):
    # Null for premium: no limit.
    max_lists: int | None
    max_gifts_per_list: int | None


class Offer(BaseModel):
    amount: str
    currency: str
    interval: Literal["year"]


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
    offer: Offer | None
    can_manage: bool
    legal: LegalLinks


class SessionUrl(BaseModel):
    url: str


class BillingRefusal(BaseModel):
    detail: str
    code: str
