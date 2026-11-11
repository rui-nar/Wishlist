"""Sign-in, sign-out and the signed-in user's account (accounts plan D7)."""

from fastapi import APIRouter, HTTPException, Request, Response, status

from app.accounts import identities, sessions
from app.accounts.deletion import delete_account
from app.accounts.deps import CurrentSession, CurrentUser, UnlockedSession
from app.accounts.google import InvalidGoogleToken
from app.accounts.models import User
from app.accounts.schemas import GoogleSignIn, Me, SignedIn, UserOut
from app.billing.schemas import BillingRefusal
from app.db import DbSession

router = APIRouter(prefix="/api", tags=["accounts"])


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
    user = identities.user_for(
        db,
        identities.GOOGLE,
        identity.sub,
        identity.email,
        identity.name,
        refresh_name=True,
    )
    token = sessions.create(db, user.id, request.app.state.clock())
    return SignedIn(token=token, user=_user_out(user))


@router.post("/auth/sign-out", status_code=status.HTTP_204_NO_CONTENT)
def sign_out(session: CurrentSession, db: DbSession) -> Response:
    sessions.delete_one(db, session)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/me")
def me(request: Request, user: CurrentUser) -> Me:
    return Me(
        **_user_out(user).model_dump(),
        is_admin=user.id in request.app.state.settings.admin_ids,
    )


@router.delete(
    "/me",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={409: {"model": BillingRefusal}, 502: {"model": BillingRefusal}},
)
def delete_me(request: Request, session: UnlockedSession, db: DbSession) -> Response:
    refusal = delete_account(db, request.app.state, session.user_id)
    if refusal is not None:
        return refusal
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
