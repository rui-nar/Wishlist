"""Request and response bodies of the comment endpoints (comments plan D5).

Givers only ever get these. Fields are listed explicitly, and no user id
appears: `mine` says which comment is the caller's (D3).
"""

import unicodedata
import uuid
from datetime import datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict

from app.comments.models import COMMENT_MAX_LENGTH


def _check_body(value: str) -> str:
    """Plain text, 1 to 2000 code points once trimmed (D2). Control characters
    other than a line feed and a tab are refused, and so are lone surrogates,
    which JSON can carry: PostgreSQL rejects NUL in text and UTF-8 cannot
    encode a surrogate, either of which would otherwise be a 500. Python
    strings count code points, as `varchar` does."""
    if any(unicodedata.category(c) in ("Cc", "Cs") and c not in "\n\t" for c in value):
        raise ValueError("a comment has no control characters")
    trimmed = value.strip()
    if not 1 <= len(trimmed) <= COMMENT_MAX_LENGTH:
        raise ValueError(f"a comment has 1 to {COMMENT_MAX_LENGTH} characters")
    return trimmed


CommentBody = Annotated[str, AfterValidator(_check_body)]


class CommentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: CommentBody


class CommentOut(BaseModel):
    id: uuid.UUID
    # Null once the author's account is deleted (D3).
    author_name: str | None
    # The caller.
    mine: bool
    body: str
    created_at: datetime
    edited: bool


class GiftThread(BaseModel):
    following: bool
    # Oldest first (D5).
    comments: list[CommentOut]
