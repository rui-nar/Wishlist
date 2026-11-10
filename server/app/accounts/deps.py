"""Who is asking (accounts plan D5).

Every endpoint that needs a user depends on `current_user` (the account's
deletion, and an image's upload or download, on `unlocked_session`; an admin
route on `admin_user`); none reads the Authorization header itself.
"""

from datetime import timedelta
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


def _found(
    request: Request, credentials: HTTPAuthorizationCredentials | None, db: DbSession
) -> UserSession:
    """The session the bearer token opens, nothing locked or written."""
    if credentials is None:
        raise _not_signed_in()
    session = sessions.find(db, credentials.credentials, request.app.state.clock())
    if session is None:
        raise _not_signed_in()
    return session


def current_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> UserSession:
    """The session the bearer token opens, its user locked, its use recorded
    (D4).

    The user is locked until the request commits, before any other lock it
    takes (reserving plan D7): `FOR KEY SHARE` for every request, `FOR UPDATE`
    for the account's deletion (`lock_for_deletion`). A deletion waits for the
    user's requests in flight, then releases what they did; a request that
    comes during a deletion waits for it, then finds no user and gets the
    answer of a signed-out token.
    """
    return _locked(request, _found(request, credentials, db), db)


def _locked(request: Request, session: UserSession, db: DbSession) -> UserSession:
    """`current_session` once the session is found: the user locked, the
    session's use recorded."""
    query = (
        select(User)
        .where(User.id == session.user_id)
        .with_for_update(read=True, key_share=True)
    )
    if db.scalar(query) is None:
        raise _not_signed_in()
    # Only once the user is locked: the deletion's cascade to the sessions
    # must not wait on a request that waits on the user.
    sessions.touch(session, request.app.state.clock())
    return session


def current_user(
    session: Annotated[UserSession, Depends(current_session)], db: DbSession
) -> User:
    # Loaded and locked by `current_session`, in this request's session.
    return db.get_one(User, session.user_id)


def unlocked_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> UserSession:
    """For a route that does slow work before it writes (an image's upload or
    download, reserving review R9-3): the session the token opens, nothing
    locked or written yet, so an account deletion meanwhile does not wait for
    that work. The route calls `lock_signed_in`, or `lock_for_deletion`, before
    its first write."""
    return _found(request, credentials, db)


def lock_signed_in(request: Request, db: DbSession, session: UserSession) -> User:
    """What `current_session` does after finding the session, for a route
    that authenticated with `unlocked_session`: the user locked
    `FOR KEY SHARE`, then the session itself, then its use recorded. Either
    gone by then (the account deleted, or the session signed out, during the
    slow work) gets the answer of a signed-out token."""
    user = db.scalar(
        select(User)
        .where(User.id == session.user_id)
        .with_for_update(read=True, key_share=True)
    )
    if user is None:
        raise _not_signed_in()
    # After the user, in the order the deletion's cascade takes them; read
    # again, so a sign-out committed meanwhile is seen here, not by the touch.
    locked = db.get(
        UserSession,
        session.id,
        with_for_update={"key_share": True},
        populate_existing=True,
    )
    if locked is None:
        raise _not_signed_in()
    sessions.touch(locked, request.app.state.clock())
    return user


def lock_for_deletion(db: DbSession, session: UserSession) -> User:
    """For `DELETE /api/me` only, once billing is stopped (premium plan D15):
    the user locked `FOR UPDATE`. Taken here, never upgraded from a share lock:
    two deletions of one account would deadlock. An account deleted meanwhile
    gets the answer of a signed-out token. A session signed out meanwhile does
    not: the deletion was asked for while it was valid, Stripe has been told,
    and the session goes with the account."""
    user = db.scalar(select(User).where(User.id == session.user_id).with_for_update())
    if user is None:
        raise _not_signed_in()
    return user


def _not_found() -> HTTPException:
    # Starlette's own answer to an unknown path, word for word: an admin route
    # looks like no route at all (admin panel plan D2).
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def admin_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> UserSession:
    """`current_session` for an admin (D1, D2): anyone else, signed out
    included, and everyone when no admin is configured, gets 404, never 401
    or 403. Nothing is locked or recorded for them."""
    admins = request.app.state.settings.admin_ids
    if not admins:
        raise _not_found()
    try:
        session = _found(request, credentials, db)
    except HTTPException:
        raise _not_found() from None
    if session.user_id not in admins:
        raise _not_found()
    try:
        return _locked(request, session, db)
    except HTTPException:
        # The account went between the two reads.
        raise _not_found() from None


def admin_user(
    session: Annotated[UserSession, Depends(admin_session)], db: DbSession
) -> User:
    # Loaded and locked by `admin_session`, in this request's session.
    return db.get_one(User, session.user_id)


# How recent an admin's sign-in must be for a change (D3).
ADMIN_REAUTH_AFTER = timedelta(hours=12)
REAUTH_REQUIRED = "reauth_required"


def recent_admin_user(
    request: Request,
    session: Annotated[UserSession, Depends(admin_session)],
    db: DbSession,
) -> User:
    """`admin_user` for a change (D3): a session created over 12 hours ago
    can read, not change, and gets 401 `reauth_required`. Only the admin ever
    sees it."""
    if request.app.state.clock() - session.created_at >= ADMIN_REAUTH_AFTER:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=REAUTH_REQUIRED,
            headers={"WWW-Authenticate": "Bearer"},
        )
    return db.get_one(User, session.user_id)


CurrentSession = Annotated[UserSession, Depends(current_session)]
CurrentUser = Annotated[User, Depends(current_user)]
UnlockedSession = Annotated[UserSession, Depends(unlocked_session)]
AdminUser = Annotated[User, Depends(admin_user)]
RecentAdminUser = Annotated[User, Depends(recent_admin_user)]
