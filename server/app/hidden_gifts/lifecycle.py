"""What happens to hidden gifts when their occasion goes (hidden gifts plan
D9).

A hidden gift is deleted explicitly, its activity dropped through
`drop_gift_activity` first (D15), never left to the occasion's cascade: no
`SET NULL` on a claim's occasion then meets an unbought claim, whatever order
Postgres fires cascades in (reserving plan D11, review R1-1).
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.orm import Session

from app.lists.models import Gift, Occasion
from app.lists.visibility import reveal_date_has_passed
from app.reserving.models import GiftClaim
from app.reserving.release import drop_gift_activity


def settle_occasion_deletion(db: Session, occasion: Occasion, now: datetime) -> None:
    """Before deleting the occasion: its hidden gifts that are received, and,
    once its reveal date has passed, those bought, become revealed rows (no
    occasion, no author); the others are deleted, bought or not (D9).

    The caller has locked the occasion `FOR UPDATE`, read it again under that
    lock (its reveal date as committed), and deleted its unbought claims, so
    no claim is made in it meanwhile. The gifts are locked in one order before
    their claims are touched (reserving plan D7: gift, then claims).
    """
    hidden = Gift.hidden_occasion_id == occasion.id
    db.execute(select(Gift.id).where(hidden).order_by(Gift.id).with_for_update())
    # A received gift is never lost: only a revealed gift can have been
    # received, so keeping it whatever the reveal date leaks nothing (review
    # R1-1).
    kept = Gift.received_at.is_not(None)
    if reveal_date_has_passed(occasion, now):
        kept = or_(
            kept,
            exists().where(
                GiftClaim.gift_id == Gift.id, GiftClaim.bought_at.is_not(None)
            ),
        )
    db.execute(
        update(Gift)
        .where(hidden, kept)
        .values(hidden_occasion_id=None, hidden_by=None)
        .execution_options(synchronize_session=False)
    )
    gone = list(db.scalars(select(Gift.id).where(hidden)))
    drop_gift_activity(db, gone)
    db.execute(delete(Gift).where(Gift.id.in_(gone)))


def lock_authored(db: Session, user_id: uuid.UUID) -> None:
    """Before an account deletion releases its claims: the hidden and
    revealed gifts the user authored, locked `FOR NO KEY UPDATE` in id
    order, as the deletion's `hidden_by` `SET NULL` locks them (D8, D10).

    So the deletion takes these gifts before any claim (D10: occasions,
    gifts, claims), never after: a deletion of one of them at the same moment
    (an owner dismissing it, which locks the gift, then its claims) either
    finished first or waits, never a deadlock (review R3-1). A giver's claim
    write, which takes the gift `FOR KEY SHARE`, does not wait on it.
    """
    db.execute(
        select(Gift.id)
        .where(Gift.hidden_by == user_id)
        .order_by(Gift.id)
        .with_for_update(key_share=True)
    )
