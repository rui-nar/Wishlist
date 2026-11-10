"""Limits on the unauthenticated email routes, in PostgreSQL (sign-in plan D12).

Two app processes can run at once, so the count is shared in the database.
Fixed windows on the SHA-256 of `kind|value`: no address or IP is stored.
"""

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import case
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.accounts.models import AuthThrottle


@dataclass(frozen=True)
class Limit:
    kind: str
    attempts: int
    window: timedelta


_QUARTER = timedelta(minutes=15)
_HOUR = timedelta(hours=1)

# The value is the address and the IP together, `<address>|<ip>`.
SIGN_IN_PER_ADDRESS_AND_IP = Limit("sign_in_address_ip", 10, _QUARTER)
SIGN_IN_PER_IP = Limit("sign_in_ip", 100, _QUARTER)
START_PER_ADDRESS = Limit("start_address", 3, _HOUR)
START_PER_IP = Limit("start_ip", 20, _HOUR)
COMPLETE_PER_IP = Limit("complete_ip", 20, _QUARTER)


def _key(limit: Limit, value: str) -> str:
    return hashlib.sha256(f"{limit.kind}|{value}".encode()).hexdigest()


def allowed(
    session_factory: sessionmaker[Session],
    limit: Limit,
    value: str,
    now: datetime,
) -> bool:
    """Counts this attempt, and says whether it is within the limit.

    In its own committed transaction, since a refused request rolls the
    request's own back. The upsert takes the row's lock, so concurrent callers
    count one after the other.
    """
    started_over = AuthThrottle.window_started_at <= now - limit.window
    statement = insert(AuthThrottle).values(
        key_hash=_key(limit, value), window_started_at=now, count=1
    )
    with session_factory.begin() as db:
        count = db.scalars(
            statement.on_conflict_do_update(
                index_elements=[AuthThrottle.key_hash],
                set_={
                    "window_started_at": case(
                        (started_over, now), else_=AuthThrottle.window_started_at
                    ),
                    "count": case((started_over, 1), else_=AuthThrottle.count + 1),
                },
            ).returning(AuthThrottle.count)
        ).one()
    return count <= limit.attempts
