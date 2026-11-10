"""Turns outbox events into notifications: who is told of what (comments plan
D9, D11).

One transaction per event, the event's row locked `SKIP LOCKED`, so two
processes never work on the same one. What an event does is in a savepoint: a
failure undoes its notifications and its digests, and the event, still locked,
records the attempt and backs off.

Every target must be a giver of the notification's occasion now, by
`giver_condition`: a recipient is never one, so no notification ever names a
recipient.
"""

import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import BigInteger, Select, Uuid, exists, literal, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.comments.models import Comment, GiftFollow
from app.lists import visibility
from app.lists.access import giver_condition
from app.lists.models import Gift, Occasion
from app.notifications import digests
from app.notifications.models import (
    COMMENT_ADDED,
    GIFT_CHANGED,
    GIFT_DELETED,
    GIFTS_REMOVED,
    PARTICIPANTS_LEFT,
    Notification,
    NotificationEvent,
)
from app.reserving.models import ClaimParticipant, GiftClaim
from app.reserving.rules import is_live

_log = logging.getLogger(__name__)

EVENT_BATCH = 100
# The waits after each of the first four failures; the fifth ends it (D9).
EVENT_BACKOFF = tuple(timedelta(minutes=m) for m in (1, 5, 30, 120))
MAX_EVENT_ATTEMPTS = len(EVENT_BACKOFF) + 1

NO_OCCASION = "no_occasion"
ERROR = "error"


class FanOutCounts(NamedTuple):
    events: int = 0
    notifications: int = 0
    failed: int = 0


class _Created(NamedTuple):
    notification_id: int
    user_id: uuid.UUID
    occasion_id: uuid.UUID
    gift_id: uuid.UUID


def fan_out_due(
    session_factory: sessionmaker[Session],
    now: datetime,
    should_stop: Callable[[], bool] = lambda: False,
) -> FanOutCounts:
    """Up to `EVENT_BATCH` due events, each in its own transaction."""
    counts = FanOutCounts()
    for _ in range(EVENT_BATCH):
        if should_stop():
            break
        result = _next_event(session_factory, now)
        if result is None:
            break
        counts = FanOutCounts(*(a + b for a, b in zip(counts, result, strict=True)))
    return counts


def _next_event(
    session_factory: sessionmaker[Session], now: datetime
) -> FanOutCounts | None:
    with session_factory() as db, db.begin():
        event = db.scalar(
            select(NotificationEvent)
            .where(
                NotificationEvent.status == "pending",
                NotificationEvent.next_attempt_at <= now,
            )
            .order_by(NotificationEvent.next_attempt_at, NotificationEvent.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            return None
        try:
            with db.begin_nested():
                created, reason = _fan_out(db, event)
                # In one order across events, or two transactions attaching
                # to the same digests could wait on each other.
                for row in sorted(created, key=_digest_key):
                    digests.attach(db, *row, now)
        except Exception as exc:
            _back_off(event, now, type(exc).__name__)
            return FanOutCounts(events=1, failed=int(event.status == "failed"))
        event.status = "done"
        event.reason = reason
        event.processed_at = now
        return FanOutCounts(events=1, notifications=len(created))


def _digest_key(row: _Created) -> tuple[str, str, str]:
    return str(row.user_id), str(row.occasion_id), str(row.gift_id)


def _back_off(event: NotificationEvent, now: datetime, error: str) -> None:
    """The exception's type only: its text can quote a row."""
    event.attempts += 1
    if event.attempts >= MAX_EVENT_ATTEMPTS:
        event.status = "failed"
        event.reason = ERROR
        event.processed_at = now
        _log.error("notifications: event %d (%s) failed", event.id, event.kind)
    else:
        event.next_attempt_at = now + EVENT_BACKOFF[event.attempts - 1]
        _log.warning(
            "notifications: event %d (%s) attempt %d failed (%s)",
            event.id,
            event.kind,
            event.attempts,
            error,
        )


def _fan_out(
    db: Session, event: NotificationEvent
) -> tuple[list[_Created], str | None]:
    """The notifications the event writes, and the word that says why it ended
    as it did, if any."""
    if event.kind == GIFT_CHANGED:
        return _to_claim_participants(db, event)
    if event.kind == GIFT_DELETED:
        return _gift_deleted(db, event)
    if event.kind == COMMENT_ADDED:
        return _comment_added(db, event), None
    if event.kind == PARTICIPANTS_LEFT:
        return _participants_left(db, event), None
    if event.kind == GIFTS_REMOVED:
        return _gifts_removed(db, event), None
    raise ValueError("unknown event kind")


def _gift_deleted(
    db: Session, event: NotificationEvent
) -> tuple[list[_Created], str | None]:
    if event.payload["received"]:
        return [], None
    return _to_claim_participants(db, event)


def _to_claim_participants(
    db: Session, event: NotificationEvent
) -> tuple[list[_Created], str | None]:
    """The participants of the gift's claim, if it was live when the event was
    written, its occasion and all (D11). Never the actor."""
    assert event.gift_id is not None
    claim = db.get(GiftClaim, event.gift_id)
    if claim is None:
        return [], None
    occasion_id = claim.occasion_id
    if occasion_id is None:
        return [], NO_OCCASION
    if not _claim_live(db, event.gift_id, occasion_id, event.created_at):
        return [], None
    # Received is not notified, and its invitees no longer see it (D11). A gift
    # gone since has its own `gift_deleted`.
    if event.kind == GIFT_CHANGED and not _in_occasion(db, event.gift_id, occasion_id):
        return [], None
    created = _notify(
        db,
        event,
        occasion_id,
        event.gift_id,
        select(ClaimParticipant.user_id).where(
            ClaimParticipant.gift_id == event.gift_id
        ),
        event.actor_id,
    )
    return created, None


def _comment_added(db: Session, event: NotificationEvent) -> list[_Created]:
    assert event.occasion_id is not None and event.gift_id is not None
    comment = db.get(Comment, uuid.UUID(event.payload["comment_id"]))
    if comment is None:  # deleted since
        return []
    if not _in_occasion(db, event.gift_id, event.occasion_id):
        return []
    return _notify(
        db,
        event,
        event.occasion_id,
        event.gift_id,
        select(GiftFollow.user_id).where(
            GiftFollow.occasion_id == event.occasion_id,
            GiftFollow.gift_id == event.gift_id,
            GiftFollow.following.is_(True),
        ),
        comment.author_id,
    )


def _participants_left(db: Session, event: NotificationEvent) -> list[_Created]:
    """Each listed gift on its own: one with a row missing is skipped, and
    never takes the others down with it (D11). The removal's `gifts_removed`
    tells of a gift gone with the same removal."""
    created: list[_Created] = []
    for entry in event.payload["gifts"]:
        gift_id = uuid.UUID(entry["gift_id"])
        occasion_id = uuid.UUID(entry["occasion_id"])
        if _in_occasion(db, gift_id, occasion_id):
            created += _notify(
                db,
                event,
                occasion_id,
                gift_id,
                _participants_of_claim(gift_id, occasion_id),
                event.actor_id,
            )
    return created


def _gifts_removed(db: Session, event: NotificationEvent) -> list[_Created]:
    """Read from the claim rows the deletion left, which the sweep keeps until
    this event is done (D11, D13)."""
    assert event.occasion_id is not None
    created: list[_Created] = []
    for entry in event.payload["gifts"]:
        gift_id = uuid.UUID(entry["gift_id"])
        if _claim_live(db, gift_id, event.occasion_id, event.created_at):
            created += _notify(
                db,
                event,
                event.occasion_id,
                gift_id,
                _participants_of_claim(gift_id, event.occasion_id),
                event.actor_id,
            )
    return created


def _participants_of_claim(gift_id: uuid.UUID, occasion_id: uuid.UUID) -> Select:
    return (
        select(ClaimParticipant.user_id)
        .join(GiftClaim, GiftClaim.gift_id == ClaimParticipant.gift_id)
        .where(
            ClaimParticipant.gift_id == gift_id,
            GiftClaim.occasion_id == occasion_id,
        )
    )


def _claim_live(
    db: Session, gift_id: uuid.UUID, occasion_id: uuid.UUID, at: datetime
) -> bool:
    """Whether the gift's claim was live at `at`: the rule every claims read
    uses, at the event's time rather than the fan-out's (D11)."""
    return (
        db.scalar(
            select(GiftClaim.gift_id).where(
                GiftClaim.gift_id == gift_id,
                GiftClaim.occasion_id == occasion_id,
                is_live(at),
            )
        )
        is not None
    )


def _in_occasion(db: Session, gift_id: uuid.UUID, occasion_id: uuid.UUID) -> bool:
    """Whether the occasion's givers see the gift: its row is there and it was
    not received. An email about anything else would lead nowhere."""
    occasion = db.get(Occasion, occasion_id)
    if occasion is None:
        return False
    return bool(
        db.scalar(
            select(exists().where(Gift.id == gift_id, visibility.in_occasion(occasion)))
        )
    )


def _notify(
    db: Session,
    event: NotificationEvent,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    users: Select,
    excluded: uuid.UUID | None,
) -> list[_Created]:
    """Inserts a notification for each of `users` who is a giver of the
    occasion now, but `excluded`. `ON CONFLICT DO NOTHING`: an event fanned out
    twice inserts nothing twice, and returns only what it did insert."""
    candidates = users.subquery()
    user_id = candidates.c.user_id
    chosen = select(
        literal(event.id, BigInteger),
        user_id,
        literal(occasion_id, Uuid),
        literal(gift_id, Uuid),
    ).where(giver_condition(user_id, occasion_id))
    if excluded is not None:
        chosen = chosen.where(user_id != excluded)
    rows = db.execute(
        insert(Notification)
        .from_select(["event_id", "user_id", "occasion_id", "gift_id"], chosen)
        .on_conflict_do_nothing(index_elements=["event_id", "user_id", "gift_id"])
        .returning(Notification.id, Notification.user_id)
    ).all()
    return [_Created(id_, user, occasion_id, gift_id) for id_, user in rows]
