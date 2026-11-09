"""The token of an email's unsubscribe link (comments plan D18).

`v1.<user id>.<signature>`: the user id's 16 bytes and the HMAC-SHA256 of
`unsubscribe:v1:<user id as text>`, each in unpadded base64url. It stays in
inboxes and never expires, so this format is a contract with every email ever
sent: a later format gets a new version prefix, and `v1` stays accepted.
"""

import base64
import hashlib
import hmac
import re
import uuid

# 22 characters for 16 bytes, 43 for 32.
_TOKEN = re.compile(r"v1\.([A-Za-z0-9_-]{22})\.[A-Za-z0-9_-]{43}")


def _encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def make_token(secret: str, user_id: uuid.UUID) -> str:
    signature = hmac.new(
        secret.encode(), f"unsubscribe:v1:{user_id}".encode(), hashlib.sha256
    ).digest()
    return f"v1.{_encode(user_id.bytes)}.{_encode(signature)}"


def read_token(secret: str, token: str) -> uuid.UUID | None:
    """The account a token was made for; None for anything else, always when
    the secret is unset."""
    found = _TOKEN.fullmatch(token)
    if not secret or found is None:
        return None
    user_id = uuid.UUID(bytes=base64.urlsafe_b64decode(found[1] + "=="))
    # The whole token against its only valid form, not the signature alone:
    # base64 leaves unused bits in a last character, and a token with those
    # changed would decode to the same bytes.
    if not hmac.compare_digest(make_token(secret, user_id), token):
        return None
    return user_id
