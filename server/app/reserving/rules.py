"""When a claim is live, and the writes every claim route shares (reserving
plan D2, D8).

Expiry is evaluated, never written: a claim of a passed occasion that was not
bought simply stops counting, and its row is purged only when someone claims
the gift again. Moving an occasion's date later therefore makes its unbought
claims live again, and no background job is needed.
"""

import datetime as dt
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import ColumnElement, delete, exists, not_, or_
from sqlalchemy.orm import Session

from app.lists.models import Occasion
from app.reserving.models import ClaimParticipant, GiftClaim

# An occasion dated D has passed from 12:00 UTC on D + 1: D has then ended in
# every time zone, the last to end being UTC-12 (D8).
_GRACE = timedelta(hours=36)


def last_passed_date(now: datetime) -> dt.date:
    """The latest occasion date that has passed at `now`."""
    return (now.astimezone(UTC) - _GRACE).date()


def has_passed(date: dt.date, now: datetime) -> bool:
    return date <= last_passed_date(now)


def is_live(now: datetime) -> ColumnElement[bool]:
    """A claim that still holds its gift: bought, or of an occasion that has
    not passed. A bought claim of a deleted occasion stays live (D11)."""
    return or_(
        GiftClaim.bought_at.is_not(None),
        exists().where(
            Occasion.id == GiftClaim.occasion_id,
            Occasion.date > last_passed_date(now),
        ),
    )


def purge_expired(db: Session, gift_id: uuid.UUID, now: datetime) -> None:
    """Deletes the gift's claim if it has expired, so it can be claimed again
    (D7 step 3). Its participants go with it."""
    db.execute(
        delete(GiftClaim).where(GiftClaim.gift_id == gift_id, not_(is_live(now)))
    )


def remove_participant(db: Session, gift_id: uuid.UUID, user_id: uuid.UUID) -> None:
    """Takes the user out of the gift's claim, and deletes the claim when that
    leaves it unbought with nobody in it: the gift is free again (D2).

    The caller holds the claim's row `FOR UPDATE` (D7 step 4), so nobody joins
    it between the two statements.
    """
    db.execute(
        delete(ClaimParticipant).where(
            ClaimParticipant.gift_id == gift_id, ClaimParticipant.user_id == user_id
        )
    )
    db.execute(
        delete(GiftClaim).where(
            GiftClaim.gift_id == gift_id,
            GiftClaim.bought_at.is_(None),
            ~exists().where(ClaimParticipant.gift_id == GiftClaim.gift_id),
        )
    )
