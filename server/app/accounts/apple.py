"""Verifying the identity token a client got from Apple (sign-in plan D14),
and signing the client secret of Apple's token endpoints (iOS app plan D5).

The app holds one verifier in `app.state.apple_verifier`, or None when
APPLE_CLIENT_IDS is empty; tests give it a fake key source, so no test calls
Apple.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, NoReturn, Protocol

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

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
# The client secret: Apple allows up to six months; one is made per call.
_SECRET_ALGORITHM = "ES256"
_SECRET_LIFESPAN_SECONDS = 5 * 60

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
    # The client ID the token was issued to, one of APPLE_CLIENT_IDS: the
    # Services ID on the web and Android, a bundle ID on iOS.
    audience: str


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
        return _identity(claims, nonce, self._audiences)

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


def _identity(claims: Any, nonce: str, audiences: list[str]) -> AppleIdentity:
    sub = claims.get("sub")
    if not isinstance(sub, str) or not sub:
        _refuse("no_subject")
    # The client gave Apple the hexadecimal SHA-256 of the nonce it sends here:
    # a token alone cannot be replayed (D15). Neither value is secret.
    if claims.get("nonce") != hashlib.sha256(nonce.encode()).hexdigest():
        _refuse("nonce")
    return AppleIdentity(
        sub=sub, email=_address(claims), audience=_audience(claims, audiences)
    )


def _audience(claims: Any, audiences: list[str]) -> str:
    # PyJWT has checked that the token names one of ours. Apple names one
    # client; a list is taken at its first that is ours.
    aud = claims["aud"]
    if isinstance(aud, str):
        return aud
    return next(client_id for client_id in aud if client_id in audiences)


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


def load_private_key(text: str) -> ec.EllipticCurvePrivateKey | None:
    """APPLE_PRIVATE_KEY as Apple's .p8 file has it: PEM, with its line breaks
    or on one line of a `.env` with each written `\\n`. None when it is no
    P-256 private key; why is never said, since the text is the secret."""
    pem = text.strip().replace("\\n", "\n")
    try:
        key = serialization.load_pem_private_key(pem.encode(), password=None)
    except Exception:
        return None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        return None
    return key


@dataclass(frozen=True)
class ClientSecretSigner:
    """Signs the client secret of Apple's token endpoints with the Sign in
    with Apple key of the owner's team (iOS app plan D5)."""

    team_id: str
    key_id: str
    key: ec.EllipticCurvePrivateKey = field(repr=False)

    def secret(self, client_id: str) -> str:
        # Apple's clock, not the app's: the secret is checked against it.
        now = int(time.time())
        return jwt.encode(
            {
                "iss": self.team_id,
                "iat": now,
                "exp": now + _SECRET_LIFESPAN_SECONDS,
                "aud": _ISSUER,
                "sub": client_id,
            },
            self.key,
            algorithm=_SECRET_ALGORITHM,
            headers={"kid": self.key_id},
        )


def granted_subject(id_token: Any) -> str | None:
    """The `sub` of the identity token Apple's token endpoint answers with, or
    None. Its signature is not checked: it comes from Apple over TLS, in
    answer to our own request."""
    if not isinstance(id_token, str):
        return None
    try:
        claims = jwt.decode(id_token, options={"verify_signature": False})
    except Exception:
        return None
    sub = claims.get("sub")
    return sub if isinstance(sub, str) and sub else None
