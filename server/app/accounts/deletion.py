"""Deleting an account, from its own account screen or from the admin panel
(accounts plan D8, admin panel plan D9): one way, whoever asks."""

import logging
import uuid

from fastapi import HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy import delete, exists, or_, select
from sqlalchemy.orm import Session, aliased
from starlette.datastructures import State

from app.accounts import apple_tokens, identities
from app.accounts.models import EmailLink, User, UserIdentity
from app.billing import apple_events
from app.billing.closing import report_late_purchases, stop_billing
from app.hidden_gifts.lifecycle import lock_authored
from app.lists.deletion import delete_lists_owned_only_by
from app.lists.models import List, ListOwner, Occasion, OccasionMember
from app.lists.visibility import of_lists
from app.reserving.release import delete_gift_claims, lock_occasions, release_activity

_log = logging.getLogger(__name__)


def delete_account(
    db: Session, state: State, user_id: uuid.UUID
) -> JSONResponse | None:
    """Deletes the account, or answers the refusal to send, with nothing
    changed (premium plan D15). The caller holds no lock on the account:
    Stripe is asked first, for up to 45 s a call, then Apple."""
    # Before any lock, so that none of their requests waits on Stripe (premium
    # plan D15). A refusal has changed nothing.
    stopped = stop_billing(db, state.stripe_gateway, user_id, state.clock())
    if isinstance(stopped, JSONResponse):
        return stopped
    # Apple's tokens revoked once billing can no longer refuse the deletion,
    # and before any lock, for the same reason (iOS app plan D5, review R1-5).
    revoked = apple_tokens.revoke_all(db, state.apple_tokens, user_id)
    # The links of their address (sign-in plan Boundaries crossed), before the
    # user's lock: a link being used holds its row and then waits on the user,
    # so taken after the lock this would deadlock with it. A link used
    # meanwhile finishes first and is deleted here.
    db.execute(
        delete(EmailLink)
        .where(
            EmailLink.address.in_(
                select(UserIdentity.subject).where(
                    UserIdentity.user_id == user_id,
                    UserIdentity.provider == identities.EMAIL,
                )
            )
        )
        .execution_options(synchronize_session=False)
    )
    # The account locked first (`FOR UPDATE`, by `_lock`), then every
    # occasion they give in or own, in the order every request takes them
    # (reserving plan D7): each request holds its user `FOR KEY SHARE` from
    # `current_session` on, so their requests in flight finished before this
    # one went on and are released below, and a later one waits, then finds
    # no user and answers 401: never a claim, a membership or a session left
    # by no one. An owner removing them locks them before the occasion too.
    user = _lock(db, user_id)
    report_late_purchases(db, user.id, stopped)
    apple_tokens.report_late_tokens(db, user.id, revoked)
    # Apple gives the server no way to cancel one, and refusing the deletion
    # is not allowed: the person was warned (Apple IAP plan D9).
    for external_id in apple_events.renewing(db, user.id):
        _log.warning(
            "billing: account %s deleted with Apple subscription %s still renewing",
            user.id,
            external_id,
        )
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
    return None


def _lock(db: Session, user_id: uuid.UUID) -> User:
    """The user locked `FOR UPDATE`, once billing is stopped. Taken here,
    never upgraded from a share lock: two deletions of one account would
    deadlock. An account deleted meanwhile gets the answer of a signed-out
    token, as `deps.current_session` gives it. A session signed out meanwhile
    does not: the deletion was asked for while it was valid, Stripe has been
    told, and the session goes with the account."""
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not signed in",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user
