"""Who is asking (accounts plan D5).

Every endpoint that needs a user depends on `current_user` (the account's
deletion on `user_to_delete`); none reads the Authorization header itself.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select

from app.accounts import sessions
from app.accounts.models import User, UserSession
from app.db import DbSession

# auto_error=False: a missing or malformed header gets the same answer as an
# unknown or expired token, below, rather than FastAPI's own.
_bearer = HTTPBearer(auto_error=False)


def _not_signed_in() -> HTTPException:
    # One body for every case, so the answer does not say whether the token
    # was missing, unknown or expired.
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not signed in",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _signed_in(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None,
    db: DbSession,
    for_deletion: bool,
) -> UserSession:
    """The session the bearer token opens, its user locked, its use recorded
    (D4).

    The user is locked until the request commits, before any other lock it
    takes (reserving plan D7): `FOR KEY SHARE` for every request, `FOR UPDATE`
    for the account's deletion. A deletion waits for the user's requests in
    flight, then releases what they did; a request that comes during a
    deletion waits for it, then finds no user and gets the answer of a
    signed-out token. The deletion's lock is taken here, never upgraded from
    a share lock: two deletions of one account would deadlock.
    """
    if credentials is None:
        raise _not_signed_in()
    now = request.app.state.clock()
    session = sessions.find(db, credentials.credentials, now)
    if session is None:
        raise _not_signed_in()
    query = select(User).where(User.id == session.user_id)
    if for_deletion:
        query = query.with_for_update()
    else:
        query = query.with_for_update(read=True, key_share=True)
    if db.scalar(query) is None:
        raise _not_signed_in()
    # Only once the user is locked: the deletion's cascade to the sessions
    # must not wait on a request that waits on the user.
    sessions.touch(session, now)
    return session


def current_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> UserSession:
    return _signed_in(request, credentials, db, for_deletion=False)


def current_user(
    session: Annotated[UserSession, Depends(current_session)], db: DbSession
) -> User:
    # Loaded and locked by `current_session`, in this request's session.
    return db.get_one(User, session.user_id)


def user_to_delete(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> User:
    """For `DELETE /api/me` only: the signed-in user, locked `FOR UPDATE`."""
    session = _signed_in(request, credentials, db, for_deletion=True)
    return db.get_one(User, session.user_id)


CurrentSession = Annotated[UserSession, Depends(current_session)]
CurrentUser = Annotated[User, Depends(current_user)]
UserToDelete = Annotated[User, Depends(user_to_delete)]
