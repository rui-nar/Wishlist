"""Email addresses and the tokens of email links (sign-in plan D4, D7).

A token is `<link id>.<signature>`: the row id's 16 bytes and the HMAC-SHA256 of
`email-link:<id as text>` with NOTIFICATION_SECRET, each in unpadded base64url.
Nothing secret is stored: the worker builds it from the row, and a copy of the
database forges nothing. The prefix keeps it apart from the unsubscribe tokens,
which use the same secret.
"""

import base64
import hashlib
import hmac
import re
import uuid

# Exactly one @, no whitespace or control character, at most 254 characters
# (D4). Nothing provider-specific, such as Gmail's dots.
_LOCAL_OR_DOMAIN = r"[^@\s\x00-\x1f\x7f-\x9f]+"
_ADDRESS = re.compile(rf"(?=.{{1,254}}\Z){_LOCAL_OR_DOMAIN}@{_LOCAL_OR_DOMAIN}")

# 22 characters for 16 bytes, 43 for 32.
_TOKEN = re.compile(r"([A-Za-z0-9_-]{22})\.[A-Za-z0-9_-]{43}")


def normalise(address: str) -> str | None:
    """The address as stored and compared; None when it cannot be one."""
    # Lowered before the checks: lowering can change the length.
    normalised = address.strip().lower()
    return normalised if _ADDRESS.fullmatch(normalised) else None


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_token(secret: str, link_id: uuid.UUID) -> str:
    signature = hmac.new(
        secret.encode(), f"email-link:{link_id}".encode(), hashlib.sha256
    ).digest()
    return f"{_encode(link_id.bytes)}.{_encode(signature)}"


def read_token(secret: str, token: str) -> uuid.UUID | None:
    """The link a token was made for; None for anything else, always when the
    secret is unset."""
    found = _TOKEN.fullmatch(token)
    if not secret or found is None:
        return None
    link_id = uuid.UUID(bytes=base64.urlsafe_b64decode(found[1] + "=="))
    # The whole token against its only valid form, not the signature alone:
    # base64 leaves unused bits in a last character, and a token with those
    # changed would decode to the same bytes.
    if not hmac.compare_digest(make_token(secret, link_id), token):
        return None
    return link_id
