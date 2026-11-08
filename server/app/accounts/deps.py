"""Who is asking (accounts plan D5).

Every endpoint that needs a user depends on `current_user`; none reads the
Authorization header itself.
"""

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

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


def current_session(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: DbSession,
) -> UserSession:
    """The session the bearer token opens, its use recorded (D4)."""
    if credentials is None:
        raise _not_signed_in()
    now = request.app.state.clock()
    session = sessions.find(db, credentials.credentials, now)
    if session is None:
        raise _not_signed_in()
    sessions.touch(session, now)
    return session


def current_user(
    session: Annotated[UserSession, Depends(current_session)], db: DbSession
) -> User:
    # The foreign key cascades: a session never outlives its user.
    return db.get_one(User, session.user_id)


CurrentSession = Annotated[UserSession, Depends(current_session)]
CurrentUser = Annotated[User, Depends(current_user)]
