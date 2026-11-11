"""Request and response bodies of the admin routes (admin panel plan D5, D6,
D8, D9)."""

import datetime as dt
import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.accounts.schemas import EMAIL_MAX_LENGTH
from app.billing.schemas import Plan


class AdminPlan(BaseModel):
    """The plan as `GET /api/billing` reads it for that person."""

    plan: Plan
    source: str | None
    # When it renews or ends; null on the free plan.
    until: datetime | None


class AdminPhotos(BaseModel):
    """The photos the person sent that a list's owners can see (D7)."""

    count: int
    # Of the photos measured so far.
    bytes: int
    # Some of them are not measured yet (`purge.fill_sizes`).
    measuring: bool


class AdminSubscription(BaseModel):
    """The person's Stripe, Apple or Google subscription, apart from a grant by
    hand: no id, no customer and no amount. An Apple one in billing retry, which
    grants nothing but which Apple may still charge (Apple IAP plan D9), reads
    `past_due` with no date, as does a Google one on hold or paused (Android
    release plan D6)."""

    # `active`, `past_due`, `canceling` (set to stop at `period_end`),
    # `incomplete`, `ended`, or `no_news`: `active` or `past_due` past its
    # grace, so its events were lost while Stripe may still bill it.
    status: str
    started_at: datetime | None
    # When it renews while `active` or `past_due`, when it ends while
    # `canceling`, the last date Stripe gave while `no_news`; null when
    # `incomplete` or `ended`, since Stripe's period end is not when it ended.
    period_end: datetime | None


class ManualGrant(BaseModel):
    period_end: datetime


class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime
    # The providers of their identities, sorted.
    sign_in: list[str]
    # The effective plan, whatever its source.
    plan: AdminPlan
    # The one in force, else the latest; null if they never subscribed. Shown
    # apart from `manual_grant`: neither hides the other.
    subscription: AdminSubscription | None
    # The same for Apple, in its own block (Apple IAP plan D9): the server
    # cannot cancel it, so deleting the account warns of it.
    apple_subscription: AdminSubscription | None
    # Any Apple subscription of theirs that Apple may still charge, whichever
    # the block shows: the admin's deletion warns of it (review R2-2).
    apple_renewing: bool
    # The same for Google Play, in its own block (Android release plan D8):
    # deleting the account cancels it first.
    google_subscription: AdminSubscription | None
    # Any Google subscription of theirs that Google may still charge.
    google_renewing: bool
    # The admin's grant still active, if any, so it can be ended (D8).
    manual_grant: ManualGrant | None
    lists_owned: int
    photos: AdminPhotos


class AdminUsersPage(BaseModel):
    users: list[AdminUserRow]
    # Null on the last page.
    next_cursor: str | None


class AdminList(BaseModel):
    """Counts only (D6): nothing about any gift, claim or invitee."""

    id: uuid.UUID
    title: str
    created_at: datetime
    gift_count: int
    owner_count: int


class AdminUserDetail(AdminUserRow):
    lists: list[AdminList]


class PremiumGrant(BaseModel):
    # One year ahead when left out; at most 10 years ahead (D8).
    period_end: dt.date | None = None


class AccountDeletion(BaseModel):
    # The account's address, typed by the admin to confirm (D9).
    email: str = Field(max_length=EMAIL_MAX_LENGTH)


class AdminRefusal(BaseModel):
    detail: str
    code: str
