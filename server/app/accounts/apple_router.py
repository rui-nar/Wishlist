"""Signing in with Apple (sign-in plan D15, D16)."""

import logging
from urllib.parse import parse_qsl, quote, urlencode

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from app.accounts import apple_tokens, identities, sessions
from app.accounts.apple import AppleIdentity, AppleKeysUnavailable, InvalidAppleToken
from app.accounts.models import User
from app.accounts.schemas import (
    DISPLAY_NAME_MAX_LENGTH,
    ID_TOKEN_MAX_LENGTH,
    DisplayName,
    SignedIn,
    UserOut,
)
from app.db import DbSession

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["accounts"])

# Random text the client makes up; the limit also makes pydantic refuse a lone
# surrogate, which could not be hashed.
_NONCE_MAX_LENGTH = 256
# Apple's codes are a short run of printable ASCII; the limit leaves room
# (iOS app plan D5).
_CODE_MAX_LENGTH = 512
_CODE_PATTERN = r"^[!-~]+$"
_RELAY_SUFFIX = "@privaterelay.appleid.com"
_RELAY_NAME = "Apple user"
# Apple's form is about 2 KiB; what comes back goes into a response header.
_MAX_CALLBACK_BYTES = 8 * 1024
_MAX_CALLBACK_FIELDS = 16


class AppleSignIn(BaseModel):
    id_token: str = Field(min_length=1, max_length=ID_TOKEN_MAX_LENGTH)
    nonce: str = Field(min_length=1, max_length=_NONCE_MAX_LENGTH)
    # Apple gives it to the client at the first authorisation only.
    name: DisplayName | None = None
    # Exchanged for the token revoked at the account's deletion (iOS app plan
    # D5). Older clients send none.
    authorization_code: str | None = Field(
        default=None, max_length=_CODE_MAX_LENGTH, pattern=_CODE_PATTERN
    )


def _refused() -> HTTPException:
    # One body for every failure.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Apple ID token"
    )


@router.post(
    "/auth/apple",
    responses={502: {"description": "Apple's keys could not be fetched"}},
)
def sign_in_with_apple(body: AppleSignIn, request: Request, db: DbSession) -> SignedIn:
    verifier = request.app.state.apple_verifier
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Apple sign-in is not configured",
        )
    try:
        identity = verifier.verify(body.id_token, body.nonce)
    except InvalidAppleToken:
        # The verifier has logged the reason; the client gets a fixed answer.
        raise _refused() from None
    except AppleKeysUnavailable:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Apple could not be reached",
        ) from None
    refresh_token = _exchanged(request, body.authorization_code, identity)
    try:
        user = identities.user_for(
            db,
            identities.APPLE,
            identity.sub,
            identity.email,
            body.name or _default_name(identity.email),
            # Apple gives the name once: a later sign-in must not lose it (D15).
            refresh_name=False,
        )
    except identities.AddressRequired:
        _log.warning("Apple ID token refused (reason=no_address)")
        raise _refused() from None
    now = request.app.state.clock()
    if refresh_token is not None:
        apple_tokens.store(db, user.id, identity.audience, refresh_token, now)
    token = sessions.create(db, user.id, now)
    return SignedIn(token=token, user=_user_out(user))


def _exchanged(
    request: Request, code: str | None, identity: AppleIdentity
) -> str | None:
    """The refresh token of the sign-in's code, or None (D5). Asked before the
    account is looked up and locked: a deletion of the account never waits on
    Apple here."""
    tokens = request.app.state.apple_tokens
    if code is None or tokens is None:
        return None
    settings = request.app.state.settings
    # Only the web flow, of the Services ID, has a redirect URI; Apple wants it
    # again with that flow's code. The native sheet's has none.
    redirect_uri = (
        settings.apple_redirect_uri
        if identity.audience == settings.apple_audiences[0]
        else None
    )
    return apple_tokens.exchange_code(tokens, code, identity, redirect_uri)


@router.post("/auth/apple/callback", status_code=status.HTTP_303_SEE_OTHER)
async def apple_callback(request: Request) -> RedirectResponse:
    """Hands Apple's answer to the Android app (D16). Changes nothing here: the
    token it carries is verified only by `sign_in_with_apple`.

    The form is read by hand: Starlette's parser needs python-multipart, which
    only this route would use.
    """
    package = request.app.state.settings.apple_android_package.strip()
    if not package:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Apple sign-in is not configured",
        )
    # Every value percent-encoded, `#` and `;` included: nothing in the form
    # can reach the fragment, where the package is named. `%20` rather than
    # `+`, which not every reader of a URL decodes as a space.
    query = urlencode(await _callback_fields(request), quote_via=quote)
    return RedirectResponse(
        f"intent://callback?{query}"
        f"#Intent;package={package};scheme=signinwithapple;end",
        status_code=status.HTTP_303_SEE_OTHER,
    )


async def _callback_fields(request: Request) -> list[tuple[str, str]]:
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > _MAX_CALLBACK_BYTES:
        raise _bad_callback()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > _MAX_CALLBACK_BYTES:
            raise _bad_callback()
    try:
        fields = parse_qsl(
            body.decode(),
            keep_blank_values=True,
            strict_parsing=True,
            errors="strict",
            max_num_fields=_MAX_CALLBACK_FIELDS,
        )
    except ValueError:
        raise _bad_callback() from None
    if not fields:
        raise _bad_callback()
    return fields


def _bad_callback() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail="Malformed Apple callback"
    )


def _default_name(address: str | None) -> str:
    # With no address, no account can be made: the name is never used.
    if address is None or address.endswith(_RELAY_SUFFIX):
        return _RELAY_NAME
    return address.partition("@")[0][:DISPLAY_NAME_MAX_LENGTH]


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
