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


class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime
    # The providers of their identities, sorted.
    sign_in: list[str]
    plan: AdminPlan
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


class ManualGrant(BaseModel):
    period_end: datetime


class AdminUserDetail(AdminUserRow):
    lists: list[AdminList]
    # The admin's grant still active, if any, so it can be ended (D8).
    manual_grant: ManualGrant | None


class PremiumGrant(BaseModel):
    # One year ahead when left out; at most 10 years ahead (D8).
    period_end: dt.date | None = None


class AccountDeletion(BaseModel):
    # The account's address, typed by the admin to confirm (D9).
    email: str = Field(max_length=EMAIL_MAX_LENGTH)


class AdminRefusal(BaseModel):
    detail: str
    code: str
