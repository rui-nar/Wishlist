"""Sign-in, sign-out and the signed-in user's account (accounts plan D7)."""

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, exists, or_, select
from sqlalchemy.orm import aliased

from app.accounts import identities, sessions
from app.accounts.deps import (
    CurrentSession,
    CurrentUser,
    UnlockedSession,
    lock_for_deletion,
)
from app.accounts.google import InvalidGoogleToken
from app.accounts.models import EmailLink, User, UserIdentity
from app.accounts.schemas import GoogleSignIn, Me, SignedIn, UserOut
from app.billing.closing import report_late_purchases, stop_billing
from app.billing.schemas import BillingRefusal
from app.db import DbSession
from app.hidden_gifts.lifecycle import lock_authored
from app.lists.deletion import delete_lists_owned_only_by
from app.lists.models import List, ListOwner, Occasion, OccasionMember
from app.lists.visibility import of_lists
from app.reserving.release import delete_gift_claims, lock_occasions, release_activity

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
    # Before any lock, so that none of their requests waits on Stripe (premium
    # plan D15). A refusal has changed nothing.
    state = request.app.state
    stopped = stop_billing(db, state.stripe_gateway, session.user_id, state.clock())
    if isinstance(stopped, JSONResponse):
        return stopped
    # The links of their address (sign-in plan Boundaries crossed), before the
    # user's lock: a link being used holds its row and then waits on the user,
    # so taken after the lock this would deadlock with it. A link used
    # meanwhile finishes first and is deleted here.
    db.execute(
        delete(EmailLink)
        .where(
            EmailLink.address.in_(
                select(UserIdentity.subject).where(
                    UserIdentity.user_id == session.user_id,
                    UserIdentity.provider == identities.EMAIL,
                )
            )
        )
        .execution_options(synchronize_session=False)
    )
    # The account locked first (`FOR UPDATE`, by `lock_for_deletion`), then every
    # occasion they give in or own, in the order every request takes them
    # (reserving plan D7): each request holds its user `FOR KEY SHARE` from
    # `current_session` on, so their requests in flight finished before this
    # one went on and are released below, and a later one waits, then finds
    # no user and answers 401: never a claim, a membership or a session left
    # by no one. An owner removing them locks them before the occasion too.
    user = lock_for_deletion(db, session)
    report_late_purchases(db, user.id, stopped)
    lock_occasions(
        db,
        or_(
            Occasion.list_id.in_(
                select(ListOwner.list_id).where(ListOwner.user_id == user.id)
            ),
            Occasion.id.in_(
                select(OccasionMember.occasion_id).where(
                    OccasionMember.user_id == user.id
                )
            ),
        ),
    )
    # The gifts they authored, before any claim: the user's deletion below
    # updates them (`hidden_by`), and a gift is always locked before its
    # claims (hidden gifts plan D10, review R3-1).
    lock_authored(db, user.id)
    # Released in every occasion (D10); their name leaves their bought
    # reservations with the user row, below.
    release_activity(db, user.id, None)
    # The claims on the lists about to go, before their cascades (D11), their
    # hidden and revealed gifts' included (hidden gifts plan D9).
    other = aliased(ListOwner)
    delete_gift_claims(
        db,
        of_lists(
            List.id.in_(
                select(ListOwner.list_id).where(
                    ListOwner.user_id == user.id,
                    ~exists().where(
                        other.list_id == ListOwner.list_id, other.user_id != user.id
                    ),
                )
            )
        ),
    )
    # The lists only this user owns go first, in the same transaction (lists
    # plan D9); a list with another owner stays.
    delete_lists_owned_only_by(db, user.id)
    # The foreign keys cascade to the user's identities and sessions (D8): every
    # token of the account is refused from the next request on.
    db.execute(delete(User).where(User.id == user.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
