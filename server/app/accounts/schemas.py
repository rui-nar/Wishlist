"""Request and response bodies of the account endpoints (accounts plan D7)."""

import re
import uuid
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

from app.accounts import email_links, passwords

# Google ID tokens are about 1 KiB; the limit bounds what is handed to the
# verifier.
ID_TOKEN_MAX_LENGTH = 4 * 1024

# Longer than any address `email_links.normalise` accepts, with room for the
# spaces it strips; the limit bounds what reaches its regex.
EMAIL_MAX_LENGTH = 320
# A link's token is 66 characters; anything else short of this is an answer
# of the route (410), not a malformed request.
LINK_TOKEN_MAX_LENGTH = 1024
DISPLAY_NAME_MAX_LENGTH = 100

# C0, DEL, C1, the line and paragraph separators, and the bidirectional
# overrides, which would turn other people's names around on their screens.
# Joiners and non-breaking spaces are text, and stay (`email_content`).
_UNPRINTABLE = re.compile(r"[\x00-\x1f\x7f-\x9f -‮⁦-⁩]")


def _email(value: str) -> str:
    normalised = email_links.normalise(value)
    if normalised is None:
        raise ValueError("not an email address")
    return normalised


def _display_name(value: str) -> str:
    # Typed by anyone, and shown on other users' screens and in emails
    # (sign-in plan D13).
    trimmed = value.strip()
    if (
        not 1 <= len(trimmed) <= DISPLAY_NAME_MAX_LENGTH
        or _UNPRINTABLE.search(trimmed) is not None
    ):
        raise ValueError("not a display name")
    return trimmed


# The address as stored and compared (D4).
EmailAddress = Annotated[
    str, Field(max_length=EMAIL_MAX_LENGTH), AfterValidator(_email)
]
# A limit on the raw value: without one, a lone surrogate would get past the
# validator and reach the database.
DisplayName = Annotated[
    str, Field(max_length=4 * DISPLAY_NAME_MAX_LENGTH), AfterValidator(_display_name)
]


class GoogleSignIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=ID_TOKEN_MAX_LENGTH)


class EmailStart(BaseModel):
    email: EmailAddress
    language: Literal["en", "fr"]


class EmailComplete(BaseModel):
    token: str = Field(min_length=1, max_length=LINK_TOKEN_MAX_LENGTH)
    password: str = Field(
        min_length=passwords.MIN_LENGTH, max_length=passwords.MAX_LENGTH
    )
    display_name: DisplayName | None = None


class EmailSignIn(BaseModel):
    email: EmailAddress
    # No minimum: only what chooses a password is held to the rules.
    password: str = Field(min_length=1, max_length=passwords.MAX_LENGTH)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class Me(UserOut):
    """`GET /api/me`: the client shows the admin panel's entry by it (admin
    panel plan D2). Sign-in's answers do not carry it: the client asks here."""

    is_admin: bool


class SignedIn(BaseModel):
    token: str
    user: UserOut
