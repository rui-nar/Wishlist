"""What a giver going away, or an owner deleting, leaves of the claims
(reserving plan D10, D11).

A giver who leaves an occasion or is removed from it gives back what they
had not bought: their unbought reservations end and they leave every group
gift, bought or not. What they reserved and bought stays bought, with their
name. Deleting their account does the same in every occasion; the user's
deletion then takes their name off their bought reservations, through the
foreign key.

An occasion's unbought claims must be gone before the occasion is: the
foreign key keeps a bought claim with no occasion (`SET NULL`), which the
claims' check constraint refuses for an unbought one. The callers lock the
occasions `FOR UPDATE` first (D7), so no claim is made in them meanwhile.
"""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.orm import Session

from app.lists.models import Gift, Occasion
from app.reserving.models import RESERVATION, ClaimParticipant, GiftClaim
from app.reserving.rules import remove_participant


def release_activity(
    db: Session, user_id: uuid.UUID, occasion_id: uuid.UUID | None
) -> None:
    """Gives back the user's activity in the occasion, or in every occasion
    when `occasion_id` is None (D10)."""
    held = (
        select(GiftClaim.gift_id, GiftClaim.kind, GiftClaim.bought_at)
        .join(ClaimParticipant, ClaimParticipant.gift_id == GiftClaim.gift_id)
        .where(ClaimParticipant.user_id == user_id)
    )
    if occasion_id is not None:
        held = held.where(GiftClaim.occasion_id == occasion_id)
    # Each claim locked as the claim routes lock it (D7 step 4), in one order,
    # so a group gift's other participants take turns with this release.
    claims = db.execute(
        held.order_by(GiftClaim.gift_id).with_for_update(of=GiftClaim)
    ).all()
    for gift_id, kind, bought_at in claims:
        # What they reserved and bought stays bought, with their name.
        if kind == RESERVATION and bought_at is not None:
            continue
        # An unbought reservation ends; a group gift loses them, and ends
        # when unbought and left with nobody.
        remove_participant(db, gift_id, user_id)


def lock_occasions(db: Session, where: ColumnElement[bool]) -> None:
    """Locks the occasions `FOR UPDATE`, in one order: a claim write waits
    (its `FOR SHARE`), then finds the occasion, or its giver, gone (D7)."""
    db.execute(select(Occasion.id).where(where).order_by(Occasion.id).with_for_update())


def delete_unbought_claims(db: Session, occasion_id: uuid.UUID) -> None:
    """Before deleting the occasion: its bought claims stay, its occasion
    then set to null, so the gift stays taken (D11)."""
    db.execute(
        delete(GiftClaim).where(
            GiftClaim.occasion_id == occasion_id, GiftClaim.bought_at.is_(None)
        )
    )


def delete_gift_claims(db: Session, gifts: ColumnElement[bool]) -> None:
    """Before deleting lists: every claim on the gifts matching `gifts`,
    explicitly, whatever order Postgres fires the gifts' and occasions'
    cascades in (D11, review R1-1)."""
    db.execute(
        delete(GiftClaim).where(GiftClaim.gift_id.in_(select(Gift.id).where(gifts)))
    )


def drop_gift_activity(db: Session, gift_ids: Collection[uuid.UUID]) -> None:
    """Before a gift row is deleted or replaced: every activity on those ids,
    in the caller's transaction (hidden gifts plan D15).

    The contract: once the transaction commits, no activity of those ids is
    reachable from any id. Every path deleting or replacing a gift calls it,
    rather than relying on a cascade from `gifts`. Today the activity is the
    gifts' claims (their participants go by cascade), which also keeps an
    unbought claim away from the occasions' `SET NULL` (review R1-1).
    COMMENTS_NOTIFICATIONS_PLAN owns this body next and extends it; the
    contract stays.
    """
    if gift_ids:
        db.execute(delete(GiftClaim).where(GiftClaim.gift_id.in_(gift_ids)))
