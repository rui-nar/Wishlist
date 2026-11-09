"""Request and response bodies of the list, gift, occasion and join endpoints
(lists plan D8).

Responses list their fields explicitly, so a column added later appears in a
response only when a plan adds it here. Request bodies refuse unknown fields:
a list's kind, for one, cannot be sent to `PATCH` (D2).

Owners and invitees get different models. The invitee's (`SharedOccasion`,
`InviteeOccasionView`, `SharedGiftOut`) never carry a join token, a member, a
list id or another occasion: those are in owners' models only.
"""

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.lists.currencies import CURRENCIES
from app.lists.models import (
    GIFT_DESCRIPTION_MAX_LENGTH,
    GIFT_TITLE_MAX_LENGTH,
    JOIN_TOKEN_MAX_LENGTH,
    LINK_MAX_LENGTH,
    OCCASION_NAME_MAX_LENGTH,
    OTHER,
    PRICE_PRECISION,
    PRICE_SCALE,
    RECIPIENT_NAME_MAX_LENGTH,
    SELF,
    TITLE_MAX_LENGTH,
)
from app.media.schemas import ImageOut

MAX_LINKS = 10


def _check_link(value: str) -> str:
    # Stored as given, not normalised: the owner's link is the one opened.
    if any(character.isspace() or not character.isprintable() for character in value):
        raise ValueError("a link has no spaces or control characters")
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("a link is an absolute http or https URL")
    return value


def _check_currency(value: str) -> str:
    if value not in CURRENCIES:
        raise ValueError("an ISO 4217 currency code, in capitals")
    return value


Title = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=TITLE_MAX_LENGTH),
]
RecipientName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=RECIPIENT_NAME_MAX_LENGTH
    ),
]
RecipientKind = Literal["self", "other"]
GiftTitle = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=GIFT_TITLE_MAX_LENGTH
    ),
]
Description = Annotated[str, StringConstraints(max_length=GIFT_DESCRIPTION_MAX_LENGTH)]
Link = Annotated[
    str, StringConstraints(max_length=LINK_MAX_LENGTH), AfterValidator(_check_link)
]
Links = Annotated[list[Link], Field(max_length=MAX_LINKS)]
# Bounded to numeric(12,2), so a larger or more precise value is refused here
# rather than overflowing or being rounded by the database (D3).
Price = Annotated[
    Decimal, Field(ge=0, max_digits=PRICE_PRECISION, decimal_places=PRICE_SCALE)
]
Currency = Annotated[str, AfterValidator(_check_currency)]
OccasionName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=OCCASION_NAME_MAX_LENGTH
    ),
]
# Capped, so an oversized token is refused before it is looked up (D5).
JoinToken = Annotated[
    str, StringConstraints(min_length=1, max_length=JOIN_TOKEN_MAX_LENGTH)
]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ListCreate(_Body):
    title: Title
    recipient_kind: RecipientKind
    recipient_name: RecipientName | None = None

    @model_validator(mode="after")
    def _recipient(self) -> ListCreate:
        if self.recipient_kind == OTHER and self.recipient_name is None:
            raise ValueError("a list for someone else needs the recipient's name")
        if self.recipient_kind == SELF and self.recipient_name is not None:
            raise ValueError("a list for me has no recipient name")
        return self


# In the update bodies a field left out is unchanged. A field whose type does
# not allow None (a title) refuses an explicit null: the default is never
# validated, a sent value always is.


class ListUpdate(_Body):
    title: Title = None  # type: ignore[assignment]
    # Checked against the list's kind by the endpoint.
    recipient_name: RecipientName | None = None


class GiftCreate(_Body):
    title: GiftTitle
    description: Description = ""
    links: Links = []
    price_amount: Price | None = None
    price_currency: Currency | None = None
    # A pending image of the caller, attached by the save (gift images D1).
    image_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _price(self) -> GiftCreate:
        if (self.price_amount is None) != (self.price_currency is None):
            raise ValueError("a price has both an amount and a currency")
        return self


class GiftUpdate(_Body):
    title: GiftTitle = None  # type: ignore[assignment]
    description: Description = None  # type: ignore[assignment]
    links: Links = None  # type: ignore[assignment]
    # Checked together with the stored price by the endpoint.
    price_amount: Price | None = None
    price_currency: Currency | None = None
    # An id attaches that pending image in place of the current one, null
    # removes the current one (gift images D11).
    image_id: uuid.UUID | None = None


class OccasionCreate(_Body):
    name: OccasionName
    date: dt.date


class OccasionUpdate(_Body):
    name: OccasionName = None  # type: ignore[assignment]
    date: dt.date = None  # type: ignore[assignment]


class JoinRequest(_Body):
    # In the body, never in the URL, so no access log records it (D5).
    token: JoinToken


class GiftOut(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID
    title: str
    description: str
    links: list[str]
    # A JSON string ("149.00"), so no client reads it as a binary float.
    price_amount: Decimal | None
    price_currency: str | None
    # Its paths are the owners' (gift images D7).
    image: ImageOut | None


class ListOut(BaseModel):
    id: uuid.UUID
    title: str
    recipient_kind: RecipientKind
    recipient_name: str | None


class OccasionOut(BaseModel):
    """An occasion as its list's owners see it."""

    id: uuid.UUID
    list_id: uuid.UUID
    name: str
    date: dt.date
    # The client builds the link from it (D5); null when there is none.
    join_token: str | None
    member_count: int


class ListSummary(ListOut):
    gift_count: int
    occasion_count: int


class ListDetail(ListOut):
    # Oldest first (D3).
    gifts: list[GiftOut]
    # By date.
    occasions: list[OccasionOut]


class OwnerOccasionView(OccasionOut):
    role: Literal["owner"]
    list: ListOut
    gifts: list[GiftOut]


class MemberOut(BaseModel):
    """Someone who joined an occasion, or whom its owner removed from it."""

    user_id: uuid.UUID
    display_name: str
    # Removed by an owner: no link lets them back until they are allowed again.
    removed: bool


class SharedGiftOut(BaseModel):
    """A gift as an invitee sees it: no list id."""

    id: uuid.UUID
    title: str
    description: str
    links: list[str]
    price_amount: Decimal | None
    price_currency: str | None
    # Its paths go through the occasion the gift is shown in (gift images D7).
    image: ImageOut | None


class SharedOccasion(BaseModel):
    """An occasion as one of its invitees sees it (D8)."""

    id: uuid.UUID
    name: str
    date: dt.date
    list_title: str
    # The list's `recipient_name`, or its owners' names for a "for me" list.
    recipient_name: str
    owner_names: list[str]


class InviteeOccasionView(SharedOccasion):
    role: Literal["invitee"]
    gifts: list[SharedGiftOut]


# `GET /api/occasions/{id}`: one model per role, told apart by `role`.
OccasionView = Annotated[
    OwnerOccasionView | InviteeOccasionView, Field(discriminator="role")
]


class JoinPreview(BaseModel):
    """What a link would join, for the confirmation screen (D5, D6)."""

    name: str
    date: dt.date
    list_title: str
    recipient_name: str
    owner_names: list[str]
    role: Literal["owner", "member", "none"]
    # The list to open instead, for an owner; null otherwise.
    list_id: uuid.UUID | None
    # The occasion already joined, for a member; null otherwise.
    occasion_id: uuid.UUID | None


class Joined(BaseModel):
    occasion_id: uuid.UUID
