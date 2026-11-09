"""What a giver going away, or an owner deleting, leaves of the claims
(reserving plan D10, D11).

A giver who leaves an occasion or is removed from it gives back what they
had not bought: their unbought reservations end and they leave every group
gift, bought or not. What they reserved and bought stays bought, with their
name. Deleting their account does the same in every occasion; the user's
deletion then takes their name off their bought reservations, through the
foreign key.

An occasion's unbought claims go with it, before the occasion is deleted: the
foreign key keeps a bought claim with no occasion (`SET NULL`), so its gift
stays taken. The callers lock the occasions `FOR UPDATE` first (D7), so no
claim is made in them meanwhile.

Deleting a gift leaves its activity to the worker's sweep (comments plan D13):
out of reach once the gift row is gone, and expired too once its occasion is.
"""

import uuid
from collections.abc import Collection

from sqlalchemy import ColumnElement, delete, exists, select
from sqlalchemy.orm import Session

from app.accounts.sessions import utc_now
from app.comments.follows import drop_follows
from app.lists.models import Gift, Occasion
from app.notifications import events
from app.reserving.models import GROUP, RESERVATION, ClaimParticipant, GiftClaim
from app.reserving.rules import is_live, remove_participant


def release_activity(
    db: Session, user_id: uuid.UUID, occasion_id: uuid.UUID | None
) -> None:
    """Gives back the user's activity in the occasion, or in every occasion
    when `occasion_id` is None (D10): their claims, then their follows, with
    one `participants_left` event (comments plan D10, D14)."""
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
    left: list[uuid.UUID] = []
    for gift_id, kind, bought_at in claims:
        # What they reserved and bought stays bought, with their name.
        if kind == RESERVATION and bought_at is not None:
            continue
        # An unbought reservation ends; a group gift loses them, and ends
        # when unbought and left with nobody.
        remove_participant(db, gift_id, user_id)
        if kind == GROUP:
            left.append(gift_id)
    events.participants_left(db, user_id, _still_given(db, left))
    drop_follows(db, user_id, occasion_id)


def _still_given(
    db: Session, gift_ids: Collection[uuid.UUID]
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Of the group gifts just left, (gift, occasion) of those someone is
    still giving: a live claim with participants left, of a gift that exists
    and an occasion that exists, or no one could be told (comments plan D10,
    D11)."""
    rows = db.execute(
        select(GiftClaim.gift_id, GiftClaim.occasion_id)
        .join(Gift, Gift.id == GiftClaim.gift_id)
        .where(
            GiftClaim.gift_id.in_(gift_ids),
            GiftClaim.occasion_id.is_not(None),
            is_live(utc_now()),
            exists().where(ClaimParticipant.gift_id == GiftClaim.gift_id),
        )
        .order_by(GiftClaim.gift_id)
    )
    return [(gift, occasion) for gift, occasion in rows]


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
    """Called for every gift row a request deletes or replaces, in its
    transaction (hidden gifts plan D15).

    The contract: once the transaction commits, no activity of those ids is
    reachable from any id. It holds by construction: every read of activity
    joins `gifts` or goes through `giving_gift`, and the callers delete those
    rows. So this deletes nothing: the request does the same work whatever
    the gifts' activity (comments plan D12, D13), and the worker's sweep
    removes the rows once their notifications are out.
    """
