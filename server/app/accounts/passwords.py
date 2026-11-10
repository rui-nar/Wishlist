"""Hashing passwords (sign-in plan D11). The only module that imports argon2.

Argon2id at OWASP's minimum: 19 MiB, 2 passes, 1 lane. At most `_MAX_HASHING`
run at once, as the VPS is shared: 40 API threads at the library's 64 MiB
would take 2.5 GB.
"""

import secrets
import threading

from argon2 import PasswordHasher, Type
from argon2.exceptions import InvalidHashError, VerificationError

# In characters, no composition rules (NIST SP 800-63B).
MIN_LENGTH = 10
MAX_LENGTH = 128

_MAX_HASHING = 4

_hasher = PasswordHasher(
    time_cost=2, memory_cost=19 * 1024, parallelism=1, type=Type.ID
)
_slots = threading.BoundedSemaphore(_MAX_HASHING)

# At import, not at first use: the first unknown address must not take longer
# than the others (D10). Never compared with a password anyone holds.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe())


def hash(password: str) -> str:
    with _slots:
        return _hasher.hash(password)


def verify(stored_hash: str, password: str) -> bool:
    with _slots:
        try:
            return _hasher.verify(stored_hash, password)
        except VerificationError, InvalidHashError:
            return False


def needs_rehash(stored_hash: str) -> bool:
    """True when the hash was made with other parameters than today's (D11)."""
    return _hasher.check_needs_rehash(stored_hash)


def dummy_verify(password: str) -> None:
    """A verification that can only fail, for an address with no account, so
    that it costs the same time (D10)."""
    verify(_DUMMY_HASH, password)
