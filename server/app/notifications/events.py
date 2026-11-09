"""The outbox's writes: one function per kind, each inserting one row
(comments plan D9, D10).

Inside the caller's transaction, so an event exists if and only if its cause
committed. Nothing here reads activity: who is told is the worker's business
(D11, D12).
"""

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.notifications.models import (
    COMMENT_ADDED,
    GIFT_CHANGED,
    GIFT_DELETED,
    GIFTS_REMOVED,
    PARTICIPANTS_LEFT,
    NotificationEvent,
)


def _write(
    db: Session,
    kind: str,
    actor_id: uuid.UUID,
    payload: dict[str, Any],
    occasion_id: uuid.UUID | None = None,
    gift_id: uuid.UUID | None = None,
) -> None:
    db.execute(
        insert(NotificationEvent).values(
            kind=kind,
            actor_id=actor_id,
            payload=payload,
            occasion_id=occasion_id,
            gift_id=gift_id,
        )
    )


def gift_changed(
    db: Session, gift_id: uuid.UUID, actor_id: uuid.UUID, fields: Sequence[str]
) -> None:
    _write(db, GIFT_CHANGED, actor_id, {"fields": list(fields)}, gift_id=gift_id)


def gift_deleted(
    db: Session, gift_id: uuid.UUID, actor_id: uuid.UUID, title: str, received: bool
) -> None:
    """The title is captured: the row is gone by fan-out."""
    payload = {"title": title, "received": received}
    _write(db, GIFT_DELETED, actor_id, payload, gift_id=gift_id)


def comment_added(
    db: Session,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    actor_id: uuid.UUID,
    comment_id: uuid.UUID,
) -> None:
    payload = {"comment_id": str(comment_id)}
    _write(db, COMMENT_ADDED, actor_id, payload, occasion_id, gift_id)


def participants_left(
    db: Session, actor_id: uuid.UUID, gifts: Sequence[tuple[uuid.UUID, uuid.UUID]]
) -> None:
    """The (gift, occasion) pairs of the group gifts the actor left; written
    also with none, so a departure writes the same rows whatever it released
    (D10, D12)."""
    listed = [
        {"gift_id": str(gift), "occasion_id": str(occasion)} for gift, occasion in gifts
    ]
    _write(db, PARTICIPANTS_LEFT, actor_id, {"gifts": listed})


def gifts_removed(
    db: Session,
    occasion_id: uuid.UUID,
    actor_id: uuid.UUID,
    gifts: Sequence[tuple[uuid.UUID, str]],
) -> None:
    """The (gift, title) pairs of the hidden gifts a removal deleted, their
    titles captured as the rows are gone by fan-out; written also with none
    (D10, D12)."""
    listed = [{"gift_id": str(gift), "title": title} for gift, title in gifts]
    _write(db, GIFTS_REMOVED, actor_id, {"gifts": listed}, occasion_id)
