"""Request and response bodies of the claims endpoints (reserving plan D6).

Givers only ever get these; no owner response carries any of them (D5).
Fields are listed explicitly, and no user id appears: `mine` says which
participant is the caller.
"""

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.lists.models import PRICE_PRECISION, PRICE_SCALE

RESERVED = "reserved"
GROUP = "group"
TAKEN = "taken"

BOUGHT = "bought"
PASSED = "passed"
ConflictCode = Literal["taken", "bought", "passed"]

# Bounded as prices are, to numeric(12,2), and never zero (D9).
PledgeAmount = Annotated[
    Decimal, Field(gt=0, max_digits=PRICE_PRECISION, decimal_places=PRICE_SCALE)
]


class PledgeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # In the gift's currency; none when the gift has no price (D9). Null
    # joins without saying how much.
    amount: PledgeAmount | None = None


class ParticipantOut(BaseModel):
    display_name: str
    # The caller.
    mine: bool
    # A JSON string ("50.00"), in its own currency: the gift's when pledged.
    pledge_amount: Decimal | None
    pledge_currency: str | None


class GiftClaimOut(BaseModel):
    gift_id: uuid.UUID
    # `taken`: held by a claim of another occasion, or bought in another or a
    # deleted one; by whom, where and whether bought are not said.
    state: Literal["reserved", "group", "taken"]
    # Always false for `taken`.
    bought: bool
    # By when they joined, then by name; always empty for `taken`.
    participants: list[ParticipantOut]


class OccasionClaims(BaseModel):
    # The occasion's date has passed (D8): the client offers no action.
    passed: bool
    # One per gift of the list with a live claim, oldest gift first; a gift
    # absent from it is free.
    gifts: list[GiftClaimOut]


class ClaimConflict(BaseModel):
    """The body of a 409 from a claims endpoint."""

    detail: str
    code: ConflictCode
