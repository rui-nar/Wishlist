"""Response bodies of the hidden-gift endpoints (hidden gifts plan D7).

Givers only ever get these. Fields are listed explicitly, with no user id and
no timestamp: `author` is a name, `mine` says whether the caller added it.
Requests use the bodies of list gifts, `GiftCreate` and `GiftUpdate`.
"""

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from app.media.schemas import ImageOut

NOT_AUTHOR = "not_author"
RefusalCode = Literal["not_author", "bought", "passed"]


class HiddenGiftOut(BaseModel):
    id: uuid.UUID
    title: str
    description: str
    links: list[str]
    # A JSON string ("149.00"), so no client reads it as a binary float.
    price_amount: Decimal | None
    price_currency: str | None
    # Its paths go through the occasion (gift images D7).
    image: ImageOut | None
    # Null once its author's account is deleted (D8).
    author: str | None
    # The caller added it.
    mine: bool


class HiddenGiftRefusal(BaseModel):
    """The body of a 403 or a 409 from a hidden-gift endpoint."""

    detail: str
    code: RefusalCode
