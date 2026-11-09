"""The claims endpoints: an occasion's activity, reserving, releasing,
marking bought, and joining or leaving a group gift (reserving plan D6).

Every route resolves its occasion through `giving_occasion`, so a recipient
gets the random-id 404 for every route and every state of their gifts (D4).
Writes follow one lock order (D7): the user `FOR KEY SHARE` (taken by
`current_session`), the occasion `FOR SHARE`, the gift `FOR KEY SHARE`, then
the claim; they write `gift_claims` and
`claim_participants` only, never a row an owner reads (D3).

A 409 is returned, not raised, so it keeps the `code` its body needs. The
only write it can commit is the purge of an expired claim, which changes
nothing anyone sees (D8).
"""

import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.db import DbSession
from app.lists.access import giving_gift, giving_occasion
from app.lists.models import Gift
from app.lists.visibility import in_occasion
from app.reserving.models import GROUP as GROUP_KIND
from app.reserving.models import RESERVATION, ClaimParticipant, GiftClaim
from app.reserving.rules import has_passed, is_live, purge_expired, remove_participant
from app.reserving.schemas import (
    BOUGHT,
    GROUP,
    PASSED,
    RESERVED,
    TAKEN,
    ClaimConflict,
    ConflictCode,
    GiftClaimOut,
    OccasionClaims,
    ParticipantOut,
    PledgeIn,
)

router = APIRouter(prefix="/api", tags=["reserving"])

_CONFLICTS: dict[str, str] = {
    TAKEN: "Someone else is giving this gift",
    BOUGHT: "This gift is bought, which is final",
    PASSED: "This occasion has passed",
}
_CONFLICT_RESPONSE = {status.HTTP_409_CONFLICT: {"model": ClaimConflict}}


@router.get("/occasions/{occasion_id}/claims")
def occasion_claims(
    occasion_id: uuid.UUID, request: Request, user: CurrentUser, db: DbSession
) -> OccasionClaims:
    # No lock: an owner's change to the occasion never waits on this read.
    occasion = giving_occasion(db, user, occasion_id, lock=False)
    now = request.app.state.clock()
    # Live claims, and the caller's own claims of this occasion that have
    # expired: they may still mark those bought (D8, review R3-1). Anyone
    # else's expired claim is gone, for this occasion's invitees too, and
    # counts as taken nowhere. Only of the gifts the occasion shows: its
    # hidden gifts included, received gifts left out (hidden gifts plan D4).
    rows = db.execute(
        select(GiftClaim, is_live(now).label("live"))
        .join(Gift, Gift.id == GiftClaim.gift_id)
        .where(
            in_occasion(occasion),
            or_(
                is_live(now),
                and_(
                    GiftClaim.occasion_id == occasion.id,
                    exists().where(
                        ClaimParticipant.gift_id == GiftClaim.gift_id,
                        ClaimParticipant.user_id == user.id,
                    ),
                ),
            ),
        )
        .order_by(Gift.created_at, Gift.id)
    ).all()
    participants = _participants(
        db,
        [claim.gift_id for claim, _ in rows if claim.occasion_id == occasion.id],
        user,
    )
    return OccasionClaims(
        passed=has_passed(occasion.date, now),
        gifts=[
            _claim_out(claim, live, occasion.id, participants) for claim, live in rows
        ],
    )


@router.post(
    "/occasions/{occasion_id}/gifts/{gift_id}/reservation",
    response_model=GiftClaimOut,
    responses=_CONFLICT_RESPONSE,
)
def reserve(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> GiftClaimOut | JSONResponse:
    occasion = giving_gift(db, user, occasion_id, gift_id)
    now = request.app.state.clock()
    if has_passed(occasion.date, now):
        return _conflict(PASSED)
    created, held = _take(db, gift_id, occasion.id, user, now, bought_at=None)
    # Mine already: a double tap, answered as the first (D6). Mine in another
    # occasion, or a group gift I am in, is taken all the same.
    if not created and not (
        held is not None
        and held.kind == RESERVATION
        and _is_mine(db, held, occasion.id, user)
    ):
        return _conflict(TAKEN)
    return _gift_claim_out(db, gift_id, occasion.id, user, now)


@router.delete(
    "/occasions/{occasion_id}/gifts/{gift_id}/reservation",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_CONFLICT_RESPONSE,
)
def release(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    occasion = giving_gift(db, user, occasion_id, gift_id)
    if has_passed(occasion.date, request.app.state.clock()):
        return _conflict(PASSED)
    claim = _locked_claim(db, gift_id)
    # Holding none is the outcome asked for: nothing to do (D6).
    if (
        claim is not None
        and claim.kind == RESERVATION
        and _is_mine(db, claim, occasion.id, user)
    ):
        if claim.bought_at is not None:
            return _conflict(BOUGHT)
        remove_participant(db, gift_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/occasions/{occasion_id}/gifts/{gift_id}/bought",
    response_model=GiftClaimOut,
    responses=_CONFLICT_RESPONSE,
)
def mark_bought(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> GiftClaimOut | JSONResponse:
    occasion = giving_gift(db, user, occasion_id, gift_id)
    now = request.app.state.clock()
    if has_passed(occasion.date, now):
        # The one write a passed occasion allows: recording a gift handed
        # over on the day, while the giver's claim still exists (D8, review
        # round 1). Nothing is created.
        claim = _locked_claim(db, gift_id)
        if claim is None or not _is_mine(db, claim, occasion.id, user):
            return _conflict(PASSED)
    else:
        # A free gift is reserved and bought at once.
        created, claim = _take(db, gift_id, occasion.id, user, now, bought_at=now)
        if created:
            return _gift_claim_out(db, gift_id, occasion.id, user, now)
        # My reservation, or a group gift I am in, here.
        if claim is None or not _is_mine(db, claim, occasion.id, user):
            return _conflict(TAKEN)
    # Bought is final: marking it again changes nothing.
    if claim.bought_at is None:
        claim.bought_at = now
        db.flush()
    return _gift_claim_out(db, gift_id, occasion.id, user, now)


@router.put(
    "/occasions/{occasion_id}/gifts/{gift_id}/pledge",
    response_model=GiftClaimOut,
    responses=_CONFLICT_RESPONSE,
)
def pledge(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    body: PledgeIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> GiftClaimOut | JSONResponse:
    occasion = giving_gift(db, user, occasion_id, gift_id)
    now = request.app.state.clock()
    if has_passed(occasion.date, now):
        return _conflict(PASSED)
    # The gift's currency now, stored with the amount: an owner changing it
    # later does not change what was pledged (D9).
    currency = db.scalar(select(Gift.price_currency).where(Gift.id == gift_id))
    if body.amount is not None and currency is None:
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "amount"),
                    "msg": "a gift with no price takes no amount",
                }
            ]
        )
    pledged = {
        "pledge_amount": body.amount,
        "pledge_currency": None if body.amount is None else currency,
    }
    # A free gift becomes a group gift with me in it.
    created, claim = _take(
        db, gift_id, occasion.id, user, now, bought_at=None, kind=GROUP_KIND, **pledged
    )
    if created:
        return _gift_claim_out(db, gift_id, occasion.id, user, now)
    # A reservation, mine included (release it first), or anything held from
    # another occasion.
    if claim is None or claim.occasion_id != occasion.id or claim.kind != GROUP_KIND:
        return _conflict(TAKEN)
    # Its composition is frozen once bought (Open decisions).
    if claim.bought_at is not None:
        return _conflict(BOUGHT)
    # Joining, or changing my amount: the claim is locked, so participants
    # of one group gift take turns (D7 step 4).
    db.execute(
        insert(ClaimParticipant)
        .values(gift_id=gift_id, user_id=user.id, **pledged)
        .on_conflict_do_update(
            index_elements=[ClaimParticipant.gift_id, ClaimParticipant.user_id],
            set_=pledged,
        )
    )
    return _gift_claim_out(db, gift_id, occasion.id, user, now)


@router.delete(
    "/occasions/{occasion_id}/gifts/{gift_id}/pledge",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_CONFLICT_RESPONSE,
)
def leave_group(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    occasion = giving_gift(db, user, occasion_id, gift_id)
    if has_passed(occasion.date, request.app.state.clock()):
        return _conflict(PASSED)
    claim = _locked_claim(db, gift_id)
    # Not in it is the outcome asked for: nothing to do (D6). The last one out
    # frees the gift.
    if (
        claim is not None
        and claim.kind == GROUP_KIND
        and _is_mine(db, claim, occasion.id, user)
    ):
        if claim.bought_at is not None:
            return _conflict(BOUGHT)
        remove_participant(db, gift_id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _conflict(code: ConflictCode) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": _CONFLICTS[code], "code": code},
    )


def _take(
    db: Session,
    gift_id: uuid.UUID,
    occasion_id: uuid.UUID,
    user: User,
    now: datetime,
    bought_at: datetime | None,
    kind: str = RESERVATION,
    pledge_amount: Decimal | None = None,
    pledge_currency: str | None = None,
) -> tuple[bool, GiftClaim | None]:
    """Reserves the gift for the user in the occasion, bought at once when
    `bought_at` is given, or starts a group gift with the user's pledge when
    `kind` is a group (D7 step 3).

    Answers (True, None) when it did. Otherwise the gift is held: (False, the
    claim holding it, locked `FOR UPDATE`). The primary key decides between
    givers claiming it at the same moment. A claim released between the
    insert and the lock is tried once more; (False, None) is a gift held
    again by then, which the caller answers as taken.
    """
    for _ in range(2):
        purge_expired(db, gift_id, now)
        created = db.scalar(
            insert(GiftClaim)
            .values(
                gift_id=gift_id,
                occasion_id=occasion_id,
                kind=kind,
                bought_at=bought_at,
            )
            .on_conflict_do_nothing(index_elements=[GiftClaim.gift_id])
            .returning(GiftClaim.gift_id)
        )
        if created is not None:
            db.execute(
                insert(ClaimParticipant).values(
                    gift_id=gift_id,
                    user_id=user.id,
                    pledge_amount=pledge_amount,
                    pledge_currency=pledge_currency,
                )
            )
            return True, None
        held = _locked_claim(db, gift_id)
        if held is not None:
            return False, held
    return False, None


def _locked_claim(db: Session, gift_id: uuid.UUID) -> GiftClaim | None:
    """The gift's claim, live or not, locked until the request commits
    (D7 step 4): changes to one claim take turns."""
    return db.scalar(
        select(GiftClaim)
        .where(GiftClaim.gift_id == gift_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _is_mine(db: Session, claim: GiftClaim, occasion_id: uuid.UUID, user: User) -> bool:
    """The user is in the claim, and the claim is of this occasion."""
    return claim.occasion_id == occasion_id and bool(
        db.scalar(
            select(
                exists().where(
                    ClaimParticipant.gift_id == claim.gift_id,
                    ClaimParticipant.user_id == user.id,
                )
            )
        )
    )


def _participants(
    db: Session, gift_ids: Sequence[uuid.UUID], user: User
) -> dict[uuid.UUID, list[ParticipantOut]]:
    """Each claim's participants, by when they joined, then by name. A
    participant whose account was deleted is no longer there (D10)."""
    found: dict[uuid.UUID, list[ParticipantOut]] = defaultdict(list)
    if not gift_ids:
        return found
    rows = db.execute(
        select(ClaimParticipant, User.display_name)
        .join(User, User.id == ClaimParticipant.user_id)
        .where(ClaimParticipant.gift_id.in_(gift_ids))
        .order_by(ClaimParticipant.joined_at, User.display_name, User.id)
    )
    for participant, name in rows:
        found[participant.gift_id].append(
            ParticipantOut(
                display_name=name,
                mine=participant.user_id == user.id,
                pledge_amount=participant.pledge_amount,
                pledge_currency=participant.pledge_currency,
            )
        )
    return found


def _claim_out(
    claim: GiftClaim,
    live: bool,
    occasion_id: uuid.UUID,
    participants: dict[uuid.UUID, list[ParticipantOut]],
) -> GiftClaimOut:
    """`live` is false only for the caller's own expired claim of this
    occasion: no other expired claim reaches a giver (`occasion_claims`)."""
    if claim.occasion_id != occasion_id:
        # Held from another occasion, or bought in a deleted one: neither who
        # nor where nor whether it was bought (D6).
        return GiftClaimOut(
            gift_id=claim.gift_id,
            state=TAKEN,
            bought=False,
            expired=False,
            participants=[],
        )
    return GiftClaimOut(
        gift_id=claim.gift_id,
        state=RESERVED if claim.kind == RESERVATION else GROUP,
        bought=claim.bought_at is not None,
        expired=not live,
        participants=participants.get(claim.gift_id, []),
    )


def _gift_claim_out(
    db: Session, gift_id: uuid.UUID, occasion_id: uuid.UUID, user: User, now: datetime
) -> GiftClaimOut:
    """The gift's claim as a giver of the occasion sees it after a write."""
    claim, live = db.execute(
        select(GiftClaim, is_live(now).label("live"))
        .where(GiftClaim.gift_id == gift_id)
        .execution_options(populate_existing=True)
    ).one()
    return _claim_out(claim, live, occasion_id, _participants(db, [gift_id], user))
