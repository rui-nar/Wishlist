"""Sign-in, sign-out and the signed-in user's account (accounts plan D7)."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import Select, delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.deps import CurrentSession, CurrentUser
from app.accounts.google import GoogleIdentity, InvalidGoogleToken
from app.accounts.models import User, UserIdentity
from app.accounts.schemas import GoogleSignIn, SignedIn, UserOut
from app.db import DbSession
from app.lists.deletion import delete_lists_owned_only_by

router = APIRouter(prefix="/api", tags=["accounts"])

GOOGLE = "google"


@router.post("/auth/google")
def sign_in_with_google(
    body: GoogleSignIn, request: Request, db: DbSession
) -> SignedIn:
    verifier = request.app.state.google_verifier
    if verifier is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Google sign-in is not configured",
        )
    try:
        identity = verifier.verify(body.id_token)
    except InvalidGoogleToken:
        # The verifier has logged the reason; the client gets a fixed answer.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Google ID token",
        ) from None
    user = _user_for(db, identity)
    token = sessions.create(db, user.id, request.app.state.clock())
    return SignedIn(token=token, user=_user_out(user))


@router.post("/auth/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(session: CurrentSession, db: DbSession) -> Response:
    sessions.delete_one(db, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(user: CurrentUser) -> UserOut:
    return _user_out(user)


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(user: CurrentUser, db: DbSession) -> Response:
    # The lists only this user owns go first, in the same transaction (lists
    # plan D9); a list with another owner stays.
    delete_lists_owned_only_by(db, user.id)
    # The foreign keys cascade to the user's identities and sessions (D8): every
    # token of the account is refused from the next request on.
    db.execute(delete(User).where(User.id == user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _user_for(db: Session, identity: GoogleIdentity) -> User:
    """The account of this Google identity, created at its first sign-in.

    Found by Google's `sub`, never by email (D1). Email and name are refreshed
    from the token at each sign-in, for display only.
    """
    user = db.scalar(_by_google_sub(identity.sub))
    if user is None:
        try:
            # A savepoint: if a concurrent first sign-in of the same Google
            # account commits first, the unique (provider, subject) constraint
            # refuses this insert, and only the savepoint is rolled back.
            with db.begin_nested():
                user = User(email=identity.email, display_name=identity.name)
                db.add(user)
                db.flush()
                db.add(
                    UserIdentity(user_id=user.id, provider=GOOGLE, subject=identity.sub)
                )
                db.flush()
            return user
        except IntegrityError:
            # Each statement sees what was committed before it started, so the
            # winner's rows are visible here.
            user = db.scalars(_by_google_sub(identity.sub)).one()
    user.email = identity.email
    user.display_name = identity.name
    return user


def _by_google_sub(sub: str) -> Select[tuple[User]]:
    return (
        select(User)
        .join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == GOOGLE, UserIdentity.subject == sub)
    )


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
