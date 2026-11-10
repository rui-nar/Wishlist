"""What happens to hidden gifts when their occasion goes (hidden gifts plan
D9), and what an owner decides on a gift: received, put back, keep (D5,
D6).

A hidden gift is deleted explicitly, its activity dropped through
`drop_gift_activity` first (D15), never left to the occasion's cascade: no
`SET NULL` on a claim's occasion then meets an unbought claim, whatever order
Postgres fires cascades in (reserving plan D11, review R1-1).
"""

import uuid
from datetime import datetime

from sqlalchemy import delete, exists, or_, select, update
from sqlalchemy.orm import Session

from app.lists.access import not_found
from app.lists.models import Gift, Occasion
from app.lists.visibility import (
    is_owner_visible,
    is_revealed,
    reveal_date_has_passed,
)
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


def delete_unbought_by(
    db: Session, user_id: uuid.UUID, occasion_id: uuid.UUID
) -> list[tuple[uuid.UUID, str]]:
    """After an owner's removal released their activity: the hidden gifts the
    removed user added to the occasion and nobody bought are deleted, their
    activity dropped first (D8, D15). The bought ones stay, with their name.
    Returns the deleted gifts' ids and titles, for the removal's notification
    (comments plan D10).

    The caller has locked the occasion `FOR UPDATE`, so no hidden gift is
    added, edited, claimed or bought in it meanwhile. Only the gifts about to
    go are locked, in one order: never a bought one, which an owner dismissing
    it locks before its claims while this removal already holds the claims of
    the user's purchases (`release_activity`; review R3-1). An unbought hidden
    gift is not revealed, so no owner route reaches it.
    """
    gone = [
        (gift, title)
        for gift, title in db.execute(
            select(Gift.id, Gift.title)
            .where(
                Gift.hidden_by == user_id,
                Gift.hidden_occasion_id == occasion_id,
                ~exists().where(
                    GiftClaim.gift_id == Gift.id, GiftClaim.bought_at.is_not(None)
                ),
            )
            .order_by(Gift.id)
            .with_for_update()
        )
    ]
    ids = [gift for gift, _ in gone]
    drop_gift_activity(db, ids)
    db.execute(delete(Gift).where(Gift.id.in_(ids)))
    return gone


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


class NotRevealed(Exception):
    """The gift is not revealed now: a 409 `not_revealed` (D5, D6)."""


def set_received(
    db: Session, gift: Gift, received_at: datetime | None, now: datetime
) -> None:
    """Marks the gift received at `received_at`, or puts it back for None
    (D5). Both are idempotent: marking keeps the first receipt's time.

    An update of `received_at` only, a non-key update: it never waits on a
    giver's claim write, nor makes one wait (D10). The caller resolved the
    gift through `owned_gift`; a hidden gift's occasion is then locked `FOR
    SHARE`, so a date change at the same moment takes turns with this
    request, and the gift is checked again under that lock: gone, or hidden
    again, it answers 404. A received hidden gift that is not revealed now
    (its date moved later since) is not put back: it would leave every owner
    view, and its occasion's deletion would take it (review R2-1). Only a
    revealed gift can have been received, so neither answer leaks anything.
    """
    _lock_occasion(db, gift)
    if not is_owner_visible(db, gift, now):
        raise not_found()
    if received_at is None and gift.list_id is None and not is_revealed(db, gift, now):
        # Seen by its owners, yet not revealed: received (`owner_visible`).
        raise NotRevealed
    update_received = update(Gift).where(Gift.id == gift.id)
    if received_at is not None:
        update_received = update_received.where(Gift.received_at.is_(None))
    # `updated_at` named, or its `onupdate` would move it: nothing else is
    # touched (D5).
    db.execute(
        update_received.values(
            received_at=received_at, updated_at=Gift.updated_at
        ).execution_options(synchronize_session=False)
    )


def keep_revealed(db: Session, gift: Gift, now: datetime) -> Gift:
    """Puts a revealed gift on its list, as a new gift: the same title,
    description, links, price and image under a new id, at the end of the
    list, with nothing of its past (D6). Returns the new gift, flushed.

    Lock order (D10): its occasion `FOR SHARE`, so a date change takes turns
    with the keep, then the gift `FOR UPDATE`, which a giver's claim write
    (`FOR KEY SHARE`) excludes; then the reveal is checked. Kept at the same
    moment, or hidden again by a date moved later, it answers 404, the
    random id's answer; a received one whose date moved later answers
    `NotRevealed`, as does a gift on the list.

    The old row's activity is dropped (D15) and the row deleted before the
    new one is inserted, all in the caller's transaction: the image passes
    from one to the other under the unique constraint.
    """
    if gift.list_id is not None:
        raise NotRevealed
    _lock_occasion(db, gift)
    old = db.scalar(
        select(Gift)
        .where(Gift.id == gift.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if old is None:
        raise not_found()
    if not is_revealed(db, old, now):
        if is_owner_visible(db, old, now):
            raise NotRevealed
        raise not_found()
    kept = Gift(
        list_id=old.for_list_id,
        title=old.title,
        description=old.description,
        links=list(old.links),
        price_amount=old.price_amount,
        price_currency=old.price_currency,
        image_id=old.image_id,
    )
    drop_gift_activity(db, [old.id])
    db.execute(delete(Gift).where(Gift.id == old.id))
    db.add(kept)
    db.flush()
    return kept


def _lock_occasion(db: Session, gift: Gift) -> None:
    """Locks the hidden gift's occasion `FOR SHARE`, if it has one: a date
    change, which locks it `FOR NO KEY UPDATE`, waits or is waited for, so
    the reveal read next is the committed one (D10)."""
    if gift.hidden_occasion_id is not None:
        db.execute(
            select(Occasion.id)
            .where(Occasion.id == gift.hidden_occasion_id)
            .with_for_update(read=True)
        )
