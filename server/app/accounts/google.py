"""Verifying the ID token a client got from Google (accounts plan D2).

The app holds one verifier in `app.state.google_verifier`, or None when
GOOGLE_CLIENT_IDS is empty; tests replace it with a fake, so no test calls
Google.
"""

import logging
from dataclasses import dataclass
from typing import Any, NoReturn

from google.auth import transport
from google.auth.transport import requests as google_requests
from google.oauth2.id_token import verify_oauth2_token

_log = logging.getLogger(__name__)

# Google mints ID tokens against its own clock. Without a tolerance, a server
# whose clock lags by even a second rejects fresh tokens as "used too early".
# Ten seconds absorbs normal NTP drift without meaningfully weakening
# verification (TraxJourney api/auth.py).
_CLOCK_SKEW_SECONDS = 10

# google-auth's exception types do not separate the failure reasons (expired,
# too early and wrong audience are all ValueError), and its messages quote the
# posted token on malformed input. So the reason is looked up by keyword and
# only this fixed label is logged, never the message text (TraxJourney #510).
_FAILURE_REASONS = (
    ("expired", "expired"),
    ("too early", "too_early"),
    ("audience", "audience"),
    ("issuer", "issuer"),
    ("signature", "signature"),
    ("segment", "malformed"),
    ("certificates", "certificates_unavailable"),
)

# One transport for the process: its requests.Session keeps the connection to
# Google's certificate endpoint open between sign-ins. It does not cache the
# certificates themselves (review R1-1, deferred).
_google_request = google_requests.Request()


@dataclass(frozen=True)
class GoogleIdentity:
    sub: str
    email: str
    name: str


class InvalidGoogleToken(Exception):
    """The token was refused. Carries a fixed reason label, never token text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class GoogleVerifier:
    def __init__(
        self,
        audiences: list[str],
        request: transport.Request = _google_request,
    ) -> None:
        self._audiences = audiences
        self._request = request

    def verify(self, id_token: str) -> GoogleIdentity:
        try:
            claims = verify_oauth2_token(
                id_token,
                self._request,
                # google-auth accepts a list: the token's audience must be one
                # of them.
                self._audiences,
                clock_skew_in_seconds=_CLOCK_SKEW_SECONDS,
            )
        except Exception as exc:
            # Every failure is a refusal: google-auth raises ValueError, its
            # own GoogleAuthError and TransportError, and whatever a malformed
            # token makes its decoding raise.
            reason = _failure_reason(exc)
            _log.warning(
                "Google ID token refused: %s (reason=%s)", type(exc).__name__, reason
            )
            # from None: a traceback logged further up must not carry the
            # original message either.
            raise InvalidGoogleToken(reason) from None
        return _identity(claims)


def _identity(claims: Any) -> GoogleIdentity:
    sub = claims.get("sub")
    email = claims.get("email")
    if not isinstance(sub, str) or not sub:
        _refuse("no_subject")
    # An unverified address could be anyone's, and it is shown to other users.
    # Google sends a boolean; older tokens carried the string "true".
    verified = claims.get("email_verified")
    verified = verified is True or verified == "true"
    if not verified or not isinstance(email, str) or not email:
        _refuse("email_not_verified")
    name = claims.get("name")
    if not isinstance(name, str) or not name.strip():
        name = email.split("@")[0]
    return GoogleIdentity(sub=sub, email=email, name=name.strip())


def _refuse(reason: str) -> NoReturn:
    _log.warning("Google ID token refused (reason=%s)", reason)
    raise InvalidGoogleToken(reason)


def _failure_reason(exc: Exception) -> str:
    message = str(exc).lower()
    for keyword, reason in _FAILURE_REASONS:
        if keyword in message:
            return reason
    return "other"
