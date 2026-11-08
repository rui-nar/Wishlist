"""Opaque session tokens, stored hashed (accounts plan D4).

The client holds the token; the database holds only its SHA-256, so a copy of
the database signs no one in. Every function takes the current time from its
caller (`app.state.clock` in the app), so tests can freeze it.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import UserSession

# A session ends 90 days after it was last used.
LIFETIME = timedelta(days=90)
# Its use is recorded at most once per hour, so a busy client does not write
# on every request.
TOUCH_INTERVAL = timedelta(hours=1)


def utc_now() -> datetime:
    return datetime.now(UTC)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(db: Session, user_id: uuid.UUID, now: datetime) -> str:
    """Opens a session for the user and returns its token, never stored."""
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            user_id=user_id,
            token_hash=hash_token(token),
            created_at=now,
            last_used_at=now,
            expires_at=now + LIFETIME,
        )
    )
    db.flush()
    return token


def find(db: Session, token: str, now: datetime) -> UserSession | None:
    """The session the token opens, or None when it is unknown or expired."""
    session = db.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(token))
    )
    if session is None or session.expires_at <= now:
        return None
    return session


def touch(session: UserSession, now: datetime) -> None:
    """Records a use: the session lives another LIFETIME from now."""
    if now - session.last_used_at < TOUCH_INTERVAL:
        return
    session.last_used_at = now
    session.expires_at = now + LIFETIME


def delete_one(db: Session, session: UserSession) -> None:
    db.delete(session)
