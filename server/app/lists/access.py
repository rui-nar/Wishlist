"""Who may touch which list and occasion (lists plan D7).

Every endpoint resolves its object here: through `owned_list` for a list and
what is under it, through `visible_occasion` for an occasion. Anything the
user may not see answers 404, the same as something that does not exist, so
an id cannot be probed: the answer for another user's list is the answer for
a random UUID.
"""

import uuid
from typing import Literal

from fastapi import HTTPException, status
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.lists.models import Gift, List, ListOwner, Occasion, OccasionMember

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


def owned_gift(db: Session, user: User, gift_id: uuid.UUID) -> Gift:
    """The gift, if the user owns its list (through `owned_list`); otherwise 404."""
    gift = db.get(Gift, gift_id)
    if gift is None:
        raise not_found()
    owned_list(db, user, gift.list_id)
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


def owned_occasion(db: Session, user: User, occasion_id: uuid.UUID) -> Occasion:
    """The occasion, if the user owns its list; 404 for its invitees too."""
    occasion, role = visible_occasion(db, user, occasion_id)
    if role != OWNER:
        raise not_found()
    return occasion
