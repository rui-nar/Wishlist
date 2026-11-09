"""Who may touch which list and occasion (lists plan D7).

Every endpoint resolves its object here: through `owned_list` for a list and
what is under it, through `visible_occasion` for an occasion. Anything the
user may not see answers 404, the same as something that does not exist, so
an id cannot be probed: the answer for another user's list is the answer for
a random UUID.
"""

import uuid
from datetime import datetime
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.lists import visibility
from app.lists.models import OTHER, Gift, List, ListOwner, Occasion, OccasionMember

OWNER = "owner"
INVITEE = "invitee"
Role = Literal["owner", "invitee"]


def not_found() -> HTTPException:
    # One body for every hidden or missing object.
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def owned_list(db: Session, user: User, list_id: uuid.UUID) -> List:
    """The list, if the user is one of its owners; otherwise 404."""
    found = db.scalar(
        select(List)
        .join(ListOwner, ListOwner.list_id == List.id)
        .where(List.id == list_id, ListOwner.user_id == user.id)
    )
    if found is None:
        raise not_found()
    return found


def owned_gift(db: Session, user: User, gift_id: uuid.UUID, now: datetime) -> Gift:
    """The gift, if the user owns its list (through `owned_list`) and its
    owners see it (`visibility.owner_visible`); otherwise 404.

    A hidden gift not revealed at `now` answers what a random id answers, to
    every owner, those of a "for someone else" list included: they reach it
    as givers (hidden gifts plan D4, D7).
    """
    gift = db.get(Gift, gift_id)
    if gift is None:
        raise not_found()
    owned_list(db, user, visibility.list_of(gift))
    if not visibility.is_owner_visible(db, gift, now):
        raise not_found()
    return gift


def owns_list(db: Session, user: User, list_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    ListOwner.list_id == list_id, ListOwner.user_id == user.id
                )
            )
        )
    )


def visible_occasion(
    db: Session, user: User, occasion_id: uuid.UUID
) -> tuple[Occasion, Role]:
    """The occasion and the user's role on it; 404 for anyone else.

    An owner of its list is `owner`, a member of this very occasion is
    `invitee`: a member of another occasion of the same list sees nothing of
    this one.
    """
    occasion = db.get(Occasion, occasion_id)
    if occasion is None:
        raise not_found()
    if owns_list(db, user, occasion.list_id):
        return occasion, OWNER
    if db.get(OccasionMember, (occasion.id, user.id)) is not None:
        return occasion, INVITEE
    raise not_found()


def giving_occasion(
    db: Session, user: User, occasion_id: uuid.UUID, lock: bool = True
) -> Occasion:
    """The occasion, if the user is one of its givers; otherwise 404
    (reserving plan D4).

    A giver is a member of the occasion, or an owner of its list when the
    list is "for someone else". An owner of a "for me" list is its recipient
    and gets what a stranger gets for a random id, whatever the activity.
    Decided from the list's kind on every call, never stored with the
    activity.

    For a write, the occasion is locked `FOR SHARE` before the membership is
    checked (D7 step 1): a removal or a leave, which lock it `FOR UPDATE`,
    either committed before (and the check fails) or waits for this request.
    A read passes `lock=False`: it needs no lock, and one would make an
    owner's change to the occasion wait on a giver's read, a wait the
    recipient could notice (review round 2).
    """
    if lock:
        locked = db.scalar(
            select(Occasion)
            .where(Occasion.id == occasion_id)
            .with_for_update(read=True)
        )
        if locked is None:
            raise not_found()
    occasion, role = visible_occasion(db, user, occasion_id)
    if role == OWNER and db.get_one(List, occasion.list_id).recipient_kind != OTHER:
        raise not_found()
    return occasion


def giving_gift(
    db: Session,
    user: User,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    lock: bool = True,
) -> Occasion:
    """The occasion, if the user gives in it and its givers see the gift (on
    its list or one of its hidden gifts, not received); otherwise 404
    (reserving plan D6, hidden gifts plan D4, comments plan D6).

    For a write, the gift is locked `FOR KEY SHARE` (reserving plan D7 step
    2): its deletion at the same moment either committed before (404) or
    waits for this request, while an owner's edit of it, or its receipt, is
    not blocked. A read passes `lock=False`, which locks neither the occasion
    nor the gift. Only the gift's id is read, so the row is never in the
    session to be written back (reserving plan D3).
    """
    occasion = giving_occasion(db, user, occasion_id, lock=lock)
    if lock:
        found = visibility.lock_gift_in_occasion(db, gift_id, occasion)
    else:
        found = bool(
            db.scalar(
                select(
                    exists().where(Gift.id == gift_id, visibility.in_occasion(occasion))
                )
            )
        )
    if not found:
        raise not_found()
    return occasion


def owned_occasion(db: Session, user: User, occasion_id: uuid.UUID) -> Occasion:
    """The occasion, if the user owns its list; 404 for its invitees too."""
    occasion, role = visible_occasion(db, user, occasion_id)
    if role != OWNER:
        raise not_found()
    return occasion
