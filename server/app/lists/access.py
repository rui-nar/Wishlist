"""Who may touch which list (lists plan D7).

Every list and gift endpoint resolves its object here. Anything the user may
not see answers 404, the same as something that does not exist, so an id
cannot be probed: the answer for another user's list is the answer for a
random UUID.
"""

import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.lists.models import Gift, List, ListOwner


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
