"""Request and response bodies of the list and gift endpoints (lists plan D8).

Responses list their fields explicitly, so a column added later appears in a
response only when a plan adds it here. Request bodies refuse unknown fields:
a list's kind, for one, cannot be sent to `PATCH` (D2).
"""

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
    LINK_MAX_LENGTH,
    OTHER,
    PRICE_PRECISION,
    PRICE_SCALE,
    RECIPIENT_NAME_MAX_LENGTH,
    SELF,
    TITLE_MAX_LENGTH,
)

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


class GiftOut(BaseModel):
    id: uuid.UUID
    list_id: uuid.UUID
    title: str
    description: str
    links: list[str]
    # A JSON string ("149.00"), so no client reads it as a binary float.
    price_amount: Decimal | None
    price_currency: str | None


class ListOut(BaseModel):
    id: uuid.UUID
    title: str
    recipient_kind: RecipientKind
    recipient_name: str | None


class ListSummary(ListOut):
    gift_count: int


class ListDetail(ListOut):
    # Oldest first (D3).
    gifts: list[GiftOut]
