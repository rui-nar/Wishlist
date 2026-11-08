"""Request and response bodies of the account endpoints (accounts plan D7)."""

import uuid

from pydantic import BaseModel, Field

# Google ID tokens are about 1 KiB; the limit bounds what is handed to the
# verifier.
ID_TOKEN_MAX_LENGTH = 4 * 1024


class GoogleSignIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=ID_TOKEN_MAX_LENGTH)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str


class SignedIn(BaseModel):
    token: str
    user: UserOut
