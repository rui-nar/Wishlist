"""Writes to a giver's follow of a gift (comments plan D4).

Inside the caller's transaction. A follow names only ids, so none of these
reads anything an owner sees.
"""

import uuid

from sqlalchemy import delete, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.comments.models import GiftFollow

_KEY = (GiftFollow.occasion_id, GiftFollow.gift_id, GiftFollow.user_id)


def auto_follow(
    db: Session, occasion_id: uuid.UUID, gift_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Follows the gift unless the user has a follow row already: an explicit
    unfollow stays one (D4)."""
    db.execute(
        insert(GiftFollow)
        .values(
            occasion_id=occasion_id, gift_id=gift_id, user_id=user_id, following=True
        )
        .on_conflict_do_nothing(index_elements=_KEY)
    )


def set_following(
    db: Session,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    user_id: uuid.UUID,
    following: bool,
) -> None:
    """Follows or unfollows by hand, whatever the row said (D4)."""
    db.execute(
        insert(GiftFollow)
        .values(
            occasion_id=occasion_id,
            gift_id=gift_id,
            user_id=user_id,
            following=following,
        )
        .on_conflict_do_update(
            index_elements=_KEY,
            set_={"following": following, "updated_at": func.now()},
        )
    )


def drop_follows(
    db: Session, user_id: uuid.UUID, occasion_id: uuid.UUID | None
) -> None:
    """The user's follows in the occasion, or in every occasion when
    `occasion_id` is None (D14)."""
    statement = delete(GiftFollow).where(GiftFollow.user_id == user_id)
    if occasion_id is not None:
        statement = statement.where(GiftFollow.occasion_id == occasion_id)
    db.execute(statement)
