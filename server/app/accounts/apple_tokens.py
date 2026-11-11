"""Apple's token endpoints, behind one module (iOS app plan D5).

At sign-in, the one-time authorization code a client got from Apple is
exchanged for a refresh token; when the account is deleted, that token is
revoked, as Apple requires of an app offering Sign in with Apple. An answer can
be late, wrong or hostile, so it leaves here as a value or an `AppleTokenError`
with a fixed label: no key, client secret, code or token goes into a log line
or an exception.

The app holds one client in `app.state.apple_tokens`, or None while revocation
is off; tests replace it with a fake or give this one a recording transport, so
none reaches Apple.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.accounts.apple import (
    AppleIdentity,
    ClientSecretSigner,
    granted_subject,
    load_private_key,
)
from app.accounts.models import AppleToken
from app.settings import Settings

_log = logging.getLogger(__name__)

TOKEN_URL = "https://appleid.apple.com/auth/token"
REVOKE_URL = "https://appleid.apple.com/auth/revoke"
# A call takes at most 5 + 10 s: a sign-in or a deletion waits on it.
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
# A real answer is a few KiB.
MAX_RESPONSE_BYTES = 64 * 1024
# Apple's error codes. Any other text of an answer is not repeated.
_APPLE_ERRORS = frozenset(
    {
        "invalid_request",
        "invalid_client",
        "invalid_grant",
        "unauthorized_client",
        "unsupported_grant_type",
        "invalid_scope",
    }
)


class AppleTokenError(Exception):
    """Apple refused or failed. Carries a fixed label, never Apple's text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Grant:
    """What a code was exchanged for."""

    refresh_token: str = field(repr=False)
    # The Apple account it was granted for, from Apple's own identity token.
    subject: str | None


class AppleTokens:
    """Constructed once, only when revocation is configured. A client per
    call: one at a sign-in that sends a code, a few at a deletion."""

    def __init__(
        self, signer: ClientSecretSigner, transport: httpx.BaseTransport | None = None
    ) -> None:
        self._signer = signer
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=CONNECT_TIMEOUT,
            read=READ_TIMEOUT,
            write=READ_TIMEOUT,
            pool=CONNECT_TIMEOUT,
        )

    def exchange(self, code: str, client_id: str, redirect_uri: str | None) -> Grant:
        """`client_id` is the one the code was issued to; `redirect_uri` the
        web flow's, which Apple wants again with a code from that flow."""
        form = {
            "client_id": client_id,
            "client_secret": self._signer.secret(client_id),
            "code": code,
            "grant_type": "authorization_code",
        }
        if redirect_uri is not None:
            form["redirect_uri"] = redirect_uri
        answer = self._post(TOKEN_URL, form)
        refresh_token = answer.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise AppleTokenError("no_refresh_token")
        return Grant(refresh_token, granted_subject(answer.get("id_token")))

    def revoke(self, refresh_token: str, client_id: str) -> None:
        self._post(
            REVOKE_URL,
            {
                "client_id": client_id,
                "client_secret": self._signer.secret(client_id),
                "token": refresh_token,
                "token_type_hint": "refresh_token",
            },
        )

    def _post(self, url: str, form: dict[str, str]) -> dict:
        try:
            # trust_env=False: no proxy or CA bundle from the environment.
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                with client.stream(
                    "POST",
                    url,
                    data=form,
                    headers={
                        "Accept": "application/json",
                        "Accept-Encoding": "identity",
                    },
                ) as response:
                    return _answer(response)
        except httpx.HTTPError as exc:
            raise AppleTokenError(f"transport:{type(exc).__name__}") from None


def _answer(response: httpx.Response) -> dict:
    body = bytearray()
    for chunk in response.iter_bytes():
        body += chunk
        if len(body) > MAX_RESPONSE_BYTES:
            raise AppleTokenError("oversized")
    try:
        # Revoking answers 200 with nothing.
        data = json.loads(bytes(body)) if body.strip() else {}
    except ValueError, RecursionError:
        data = None
    if response.status_code != 200:
        error = data.get("error") if isinstance(data, dict) else None
        if error in _APPLE_ERRORS:
            raise AppleTokenError(f"error:{error}")
        raise AppleTokenError(f"status:{response.status_code}")
    if not isinstance(data, dict):
        raise AppleTokenError("malformed")
    return data


def _reason(exc: Exception) -> str:
    # Anything but our own error is named by its type: its text may quote
    # what was sent.
    if isinstance(exc, AppleTokenError):
        return exc.reason
    return f"error:{type(exc).__name__}"


def signer_from(settings: Settings) -> tuple[ClientSecretSigner | None, list[str]]:
    """The signer, or None and the variables that keep revocation off, missing
    or unloadable, by the name the operator sets."""
    team_id = settings.apple_team_id.strip()
    key_id = settings.apple_key_id.strip()
    text = settings.apple_private_key
    key = load_private_key(text) if text.strip() else None
    gaps = [
        name
        for name, value in (
            ("APPLE_TEAM_ID", team_id),
            ("APPLE_KEY_ID", key_id),
            ("APPLE_PRIVATE_KEY", key),
        )
        if not value
    ]
    if gaps or key is None:
        return None, gaps
    return ClientSecretSigner(team_id, key_id, key), []


def exchange_code(
    tokens: AppleTokens,
    code: str,
    identity: AppleIdentity,
    redirect_uri: str | None,
) -> str | None:
    """The refresh token of a sign-in's code, or None: a failure is logged and
    the sign-in goes on (D5). The code is untrusted: one issued to another
    client is refused by Apple, and one of another Apple account is dropped
    here, since its token is not this account's to keep or to revoke."""
    try:
        grant = tokens.exchange(code, identity.audience, redirect_uri)
    except Exception as exc:
        # Whatever went wrong, the person signed in.
        _log.warning("apple: code not exchanged (reason=%s)", _reason(exc))
        return None
    if grant.subject != identity.sub:
        _log.warning("apple: code not exchanged (reason=subject)")
        return None
    return grant.refresh_token


def store(
    db: Session, user_id: uuid.UUID, client_id: str, refresh_token: str, now: datetime
) -> None:
    """Keeps the token, in place of the one of an earlier sign-in to the same
    client. A failure is logged and the sign-in goes on; the database's message
    is not, since it would quote the token."""
    values = insert(AppleToken).values(
        user_id=user_id,
        client_id=client_id,
        refresh_token=refresh_token,
        updated_at=now,
    )
    statement = values.on_conflict_do_update(
        index_elements=[AppleToken.user_id, AppleToken.client_id],
        set_={
            "refresh_token": values.excluded.refresh_token,
            "updated_at": values.excluded.updated_at,
        },
    )
    try:
        with db.begin_nested():
            db.execute(statement)
    except SQLAlchemyError as exc:
        _log.warning(
            "apple: token of account %s not stored (%s)", user_id, type(exc).__name__
        )


def revoke_all(db: Session, tokens: AppleTokens | None, user_id: uuid.UUID) -> set[str]:
    """Revokes every token kept for the account, before its deletion takes any
    lock: Apple is asked for up to 15 s a token. A failure is logged and the
    deletion goes on (D5): the person asked to be deleted, and without the
    token no later attempt is possible. The tokens dealt with, for
    `report_late_tokens`."""
    rows = db.execute(
        select(AppleToken.client_id, AppleToken.refresh_token)
        .where(AppleToken.user_id == user_id)
        .order_by(AppleToken.client_id)
    ).all()
    for client_id, refresh_token in rows:
        if tokens is None:
            _log.warning(
                "apple: token of account %s for %s not revoked (reason=off)",
                user_id,
                client_id,
            )
            continue
        try:
            tokens.revoke(refresh_token, client_id)
        except Exception as exc:
            _log.warning(
                "apple: token of account %s for %s not revoked (reason=%s)",
                user_id,
                client_id,
                _reason(exc),
            )
    return {refresh_token for _, refresh_token in rows}


def report_late_tokens(db: Session, user_id: uuid.UUID, dealt_with: set[str]) -> None:
    """Names each token stored by a sign-in between `revoke_all` and the
    user's lock, which goes with the account unrevoked. Run under that lock,
    so every such sign-in has committed. Compared here, not in SQL: a failed
    statement's message would quote its parameters."""
    rows = db.execute(
        select(AppleToken.client_id, AppleToken.refresh_token)
        .where(AppleToken.user_id == user_id)
        .order_by(AppleToken.client_id)
    )
    for client_id, refresh_token in rows:
        if refresh_token in dealt_with:
            continue
        _log.warning(
            "apple: token of account %s for %s was stored during its deletion"
            " and not revoked",
            user_id,
            client_id,
        )
