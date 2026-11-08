"""What account deletion removes of a user's lists (lists plan D9)."""

import uuid

from sqlalchemy import delete, exists, select
from sqlalchemy.orm import Session, aliased

from app.lists.models import List, ListOwner


def delete_lists_owned_only_by(db: Session, user_id: uuid.UUID) -> None:
    """Deletes the lists this user is the only owner of, with all under them.

    A list with another owner is kept; the user's own `list_owners` row goes
    with the user, through its foreign key.
    """
    other = aliased(ListOwner)
    db.execute(
        delete(List).where(
            List.id.in_(select(ListOwner.list_id).where(ListOwner.user_id == user_id)),
            ~exists().where(other.list_id == List.id, other.user_id != user_id),
        )
    )
