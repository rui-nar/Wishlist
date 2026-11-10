"""Verifying the identity token a client got from Apple (sign-in plan D14).

The app holds one verifier in `app.state.apple_verifier`, or None when
APPLE_CLIENT_IDS is empty; tests give it a fake key source, so no test calls
Apple.
"""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, NoReturn, Protocol

import jwt

from app.accounts import email_links

_log = logging.getLogger(__name__)

_ISSUER = "https://appleid.apple.com"
_KEYS_URL = "https://appleid.apple.com/auth/keys"
_ALGORITHM = "RS256"
_TIMEOUT_SECONDS = 5
# Apple changes its keys rarely, and a token signed with a new one makes the
# client look again, at most every 30 s (PyJWT's cooldown): a made-up key ID
# cannot make every sign-in call Apple.
_KEYS_LIFESPAN_SECONDS = 60 * 60
_CLOCK_SKEW_SECONDS = 10

# Most specific first: an invalid signature is also a DecodeError. Only these
# labels are logged, never the message: PyJWT's can quote the token's header.
_FAILURE_REASONS = (
    (jwt.ExpiredSignatureError, "expired"),
    (jwt.ImmatureSignatureError, "too_early"),
    (jwt.InvalidAudienceError, "audience"),
    (jwt.InvalidIssuerError, "issuer"),
    (jwt.InvalidAlgorithmError, "algorithm"),
    (jwt.InvalidSignatureError, "signature"),
    (jwt.MissingRequiredClaimError, "missing_claim"),
    (jwt.InvalidKeyError, "key"),
    (jwt.DecodeError, "malformed"),
)


@dataclass(frozen=True)
class AppleIdentity:
    sub: str
    # Apple does not send it every time (D15). Verified and normalised.
    email: str | None


class InvalidAppleToken(Exception):
    """The token was refused. Carries a fixed reason label, never token text."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class AppleKeysUnavailable(Exception):
    """Apple's keys could not be had: nothing is known about the token."""


class KeySource(Protocol):
    def key(self, kid: str) -> Any | None:
        """The public key with this ID; None when Apple has no such key. Raises
        `AppleKeysUnavailable` when Apple's keys cannot be had."""


class AppleKeys:
    """Apple's public keys, cached by PyJWT's client."""

    def __init__(self, client: jwt.PyJWKClient | None = None) -> None:
        self._client = client or jwt.PyJWKClient(
            _KEYS_URL, lifespan=_KEYS_LIFESPAN_SECONDS, timeout=_TIMEOUT_SECONDS
        )

    def key(self, kid: str) -> Any | None:
        try:
            # On its own first: PyJWT raises the same error for a key Apple
            # does not have and for an answer without keys, and only the first
            # is the token's fault.
            self._client.get_signing_keys()
            try:
                return self._client.get_signing_key(kid).key
            except jwt.PyJWKClientConnectionError:
                raise
            except jwt.PyJWKClientError:
                return None
        except Exception as exc:
            # Late, wrong or hostile, Apple's answer says nothing of the token.
            _log.warning("Apple keys unavailable: %s", type(exc).__name__)
            raise AppleKeysUnavailable from None


class AppleVerifier:
    def __init__(self, audiences: list[str], keys: KeySource | None = None) -> None:
        self._audiences = audiences
        self._keys = keys or AppleKeys()

    def verify(self, id_token: str, nonce: str) -> AppleIdentity:
        try:
            claims = jwt.decode(
                id_token,
                self._key_of(id_token),
                algorithms=[_ALGORITHM],
                audience=self._audiences,
                issuer=_ISSUER,
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": ["iss", "aud", "exp", "iat", "sub"]},
            )
        except AppleKeysUnavailable:
            raise
        except Exception as exc:
            # Every other failure is a refusal, whatever a malformed token
            # makes the decoding raise.
            reason = _failure_reason(exc)
            _log.warning(
                "Apple ID token refused: %s (reason=%s)", type(exc).__name__, reason
            )
            # from None: a traceback logged further up must not carry the
            # original message either.
            raise InvalidAppleToken(reason) from None
        return _identity(claims, nonce)

    def _key_of(self, id_token: str) -> Any:
        header = jwt.get_unverified_header(id_token)
        # Before any lookup, so that `none` or HS256 costs no call to Apple.
        # `algorithms` above is what guards the verification itself.
        if header.get("alg") != _ALGORITHM:
            raise jwt.InvalidAlgorithmError
        kid = header.get("kid")
        key = self._keys.key(kid) if kid else None
        if key is None:
            raise jwt.InvalidKeyError
        return key


def _identity(claims: Any, nonce: str) -> AppleIdentity:
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        _refuse("no_subject")
    # The client gave Apple the hexadecimal SHA-256 of the nonce it sends here:
    # a token alone cannot be replayed (D15). Neither value is secret.
    if claims.get("nonce") != hashlib.sha256(nonce.encode()).hexdigest():
        _refuse("nonce")
    return AppleIdentity(sub=sub, email=_address(claims))


def _address(claims: Any) -> str | None:
    email = claims.get("email")
    if email is None:
        return None
    # An unverified address could be anyone's, and it is shown to other users.
    # Apple sends either a boolean or the string "true".
    verified = claims.get("email_verified")
    if verified is not True and verified != "true":
        _refuse("email_not_verified")
    address = email_links.normalise(email) if isinstance(email, str) else None
    if address is None:
        _refuse("bad_address")
    return address


def _refuse(reason: str) -> NoReturn:
    _log.warning("Apple ID token refused (reason=%s)", reason)
    raise InvalidAppleToken(reason)


def _failure_reason(exc: Exception) -> str:
    for kind, reason in _FAILURE_REASONS:
        if isinstance(exc, kind):
            return reason
    return "other"
