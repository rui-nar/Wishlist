"""Which gifts each person sees (hidden gifts plan D4).

A gift is on a list (`list_id`), or hidden for one (`for_list_id`, with its
occasion and author), and any gift may be marked received. This module is the
only one, besides the models and `app.hidden_gifts`, that names the columns
saying so: every query selecting gifts for an owner or a giver takes one of
its conditions, and a test fails on any other module naming them.

A hidden gift is revealed when its claim is bought and its occasion's reveal
date has passed (D3). Nothing is written then: like a claim's expiry
(reserving plan D8), it is evaluated at every read, by the server's clock.
"""

import datetime as dt
import uuid
from datetime import datetime

from sqlalchemy import ColumnElement, and_, exists, func, or_, select
from sqlalchemy.orm import Session

from app.lists.models import Gift, List, Occasion
from app.reserving.models import GiftClaim
from app.reserving.rules import has_passed, last_passed_date

ListId = uuid.UUID | ColumnElement[uuid.UUID]


def on_list(list_id: ListId) -> ColumnElement[bool]:
    """The gifts the list shows: its owners' list and every occasion's view,
    for owners and invitees alike. Never a hidden gift, never a received one."""
    return and_(Gift.list_id == list_id, Gift.received_at.is_(None))


def counted(list_id: ListId) -> ColumnElement[bool]:
    """The gifts counted as on the list (`gift_count`, and the free plan's
    limit, D12): hidden and revealed gifts have no `list_id`, so they never
    count, and received gifts are left out."""
    return on_list(list_id)


def reveal_date_passed(now: datetime) -> ColumnElement[bool]:
    """The occasion's reveal date has passed: the later of its date and the
    latest date it had (D3), by the rule an occasion passes by (reserving
    plan D8). `greatest` ignores a null `latest_date`."""
    return func.greatest(Occasion.date, Occasion.latest_date) <= last_passed_date(now)


def reveal_date_has_passed(occasion: Occasion, now: datetime) -> bool:
    """`reveal_date_passed`, for one occasion in hand."""
    return has_passed(max(occasion.date, occasion.latest_date or occasion.date), now)


def move_date(occasion: Occasion, date: dt.date) -> None:
    """Sets the occasion's date, keeping the latest date it had: moving it
    later moves the reveal later, moving it earlier never brings the reveal
    forward (D3). The caller holds the occasion's row locked."""
    if date == occasion.date:
        return
    occasion.latest_date = max(occasion.date, occasion.latest_date or occasion.date)
    occasion.date = date


def revealed(list_id: ListId, now: datetime) -> ColumnElement[bool]:
    """The list's revealed gifts: hidden for it, bought, in an occasion whose
    reveal date has passed; or left by their occasion's deletion (D9). The
    only owner-side condition that reads a claim, and only a hidden gift's."""
    return and_(
        Gift.for_list_id == list_id,
        or_(
            Gift.hidden_occasion_id.is_(None),
            and_(
                exists().where(
                    Occasion.id == Gift.hidden_occasion_id, reveal_date_passed(now)
                ),
                exists().where(
                    GiftClaim.gift_id == Gift.id, GiftClaim.bought_at.is_not(None)
                ),
            ),
        ),
    )


def owner_visible(list_id: ListId, now: datetime) -> ColumnElement[bool]:
    """Every gift the list's owners may see or act on: on the list (received
    or not), revealed, or a hidden gift they marked received, whatever its
    occasion's date became since (D5, review R1-1). Only a revealed gift can
    be marked received, so the last term leaks nothing."""
    return or_(
        Gift.list_id == list_id,
        revealed(list_id, now),
        and_(Gift.for_list_id == list_id, Gift.received_at.is_not(None)),
    )


def owner_visible_anywhere(now: datetime) -> ColumnElement[bool]:
    """`owner_visible`, for gifts of any list: every gift its list's owners
    may see, on whichever list it is or is for. The admin panel's photo
    figures count these only (admin panel plan D7, review R1-1): a hidden
    gift is a giver's activity until revealed."""
    return or_(Gift.list_id.is_not(None), owner_visible(Gift.for_list_id, now))


def received(list_id: ListId) -> ColumnElement[bool]:
    """The list's "Received": every gift of it its owners marked received,
    on the list or revealed, whatever its occasion's date became since (D5,
    review R1-1). All of them `owner_visible`."""
    return and_(
        or_(Gift.list_id == list_id, Gift.for_list_id == list_id),
        Gift.received_at.is_not(None),
    )


# Newest first, then by id (D5).
RECEIVED_ORDER = (Gift.received_at.desc(), Gift.id)


def undecided(list_id: ListId, now: datetime) -> ColumnElement[bool]:
    """The revealed gifts its owners have not marked received: what they
    decide on (received, dismiss, keep, D6)."""
    return and_(revealed(list_id, now), Gift.received_at.is_(None))


# By title, then by id: never `created_at`, which is when a giver added it
# (D6).
REVEALED_ORDER = (Gift.title, Gift.id)


def in_occasion(occasion: Occasion) -> ColumnElement[bool]:
    """The gifts the occasion's givers see: its list's gifts and its own
    hidden gifts, none received. The claims read, every claim write, the
    occasion's image route for givers and the hidden-gift routes."""
    return and_(
        Gift.received_at.is_(None),
        or_(
            Gift.list_id == occasion.list_id,
            Gift.hidden_occasion_id == occasion.id,
        ),
    )


def of_lists(lists: ColumnElement[bool]) -> ColumnElement[bool]:
    """Every gift of the lists matching `lists`, hidden, revealed and
    received included: what deleting them must clear first (D9)."""
    matching = select(List.id).where(lists)
    return or_(Gift.list_id.in_(matching), Gift.for_list_id.in_(matching))


def list_of(gift: Gift) -> uuid.UUID:
    """The list the gift is on, or is for."""
    list_id = gift.list_id if gift.list_id is not None else gift.for_list_id
    assert list_id is not None  # the database's `list_reference` check
    return list_id


def is_owner_visible(db: Session, gift: Gift, now: datetime) -> bool:
    """Whether the owners of the gift's list see it (`owner_visible`)."""
    return bool(
        db.scalar(
            select(
                exists().where(Gift.id == gift.id, owner_visible(list_of(gift), now))
            )
        )
    )


def is_revealed(db: Session, gift: Gift, now: datetime) -> bool:
    """Whether the gift is revealed (`revealed`)."""
    return bool(
        db.scalar(
            select(exists().where(Gift.id == gift.id, revealed(list_of(gift), now)))
        )
    )


def lock_gift_in_occasion(db: Session, gift_id: uuid.UUID, occasion: Occasion) -> bool:
    """Locks the gift `FOR KEY SHARE` if the occasion's givers see it
    (reserving plan D7 step 2). The condition is checked by the locked read,
    so a receipt committed meanwhile is seen (D10); its deletion either
    committed before (not found) or waits for the caller. Only the id is
    read: the gift row is never in the session to be written back."""
    return (
        db.scalar(
            select(Gift.id)
            .where(Gift.id == gift_id, in_occasion(occasion))
            .with_for_update(read=True, key_share=True)
        )
        is not None
    )
