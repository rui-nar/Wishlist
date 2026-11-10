"""The free plan's limits, on the four paths that make a list longer (premium
plan D4-D8).

The inputs are `visibility.counted`, the lists' owners and the entitlements,
and nothing else (D7): no limit, count or refusal may depend on what invitees
did, and a test fails if this module imports their models.

Nothing here applies unless `settings.limits_enforced` (D9): off, the growing
paths take no lock and count nothing.
"""

import uuid
from datetime import datetime
from typing import Literal, NoReturn

from pydantic import BaseModel
from sqlalchemy import BigInteger, exists, func, literal, select
from sqlalchemy.orm import Session, aliased

from app.billing.entitlements import is_premium, premium_condition, warn_if_lapsed
from app.lists import visibility
from app.lists.models import Gift, ListOwner
from app.settings import Settings

PLAN_LIMIT = "plan_limit"
LISTS = "lists"
GIFTS = "gifts"

Resource = Literal["lists", "gifts"]


class PlanLimitRefusal(BaseModel):
    """The body of a 402: this needs paying (D4). No `used` figure: a refusal
    carries no count."""

    detail: str
    code: Literal["plan_limit"]
    resource: Resource
    limit: int


class PlanLimitReached(Exception):
    """The request would grow something past the free plan's limit: a 402."""

    def __init__(self, resource: Resource, limit: int) -> None:
        super().__init__(resource, limit)
        self.resource: Resource = resource
        self.limit = limit


def _lock_growth(db: Session, key: str) -> None:
    # Held to commit, and taken only by owners' growth (D8): no giver route
    # takes it, so no giver can hold it.
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(key, literal(0, BigInteger))
            )
        )
    )


def ensure_room_for_list(
    db: Session, settings: Settings, user_id: uuid.UUID, now: datetime
) -> None:
    """Raises `PlanLimitReached` when a free user's lists are at the limit.

    Their lists are those no premium owner covers (D5). The lock is the
    user's, and is taken before counting, so two creations take turns (D8).
    """
    if not settings.limits_enforced:
        return
    _lock_growth(db, f"plan_growth:lists:{user_id}")
    if is_premium(db, user_id, now):
        return
    co_owner = aliased(ListOwner)
    covered = exists().where(
        co_owner.list_id == ListOwner.list_id,
        premium_condition(co_owner.user_id, now),
    )
    used = db.scalars(
        select(func.count())
        .select_from(ListOwner)
        .where(ListOwner.user_id == user_id, ~covered)
    ).one()
    if used >= settings.free_max_lists:
        warn_if_lapsed(db, user_id, now)
        raise PlanLimitReached(LISTS, settings.free_max_lists)


def lock_gift_growth(db: Session, settings: Settings, list_id: uuid.UUID) -> None:
    """Takes the list's growth lock, before counting and to commit (D8). A
    caller holding it must not then wait on a giver: `keep_revealed` takes it
    last, after the gift's own wait."""
    if settings.limits_enforced:
        _lock_growth(db, f"plan_growth:gifts:{list_id}")


def ensure_room_for_gift(
    db: Session, settings: Settings, list_id: uuid.UUID, now: datetime
) -> None:
    """Raises `PlanLimitReached` when the list is at the limit and none of its
    owners is premium, whoever is acting (D5). The caller holds
    `lock_gift_growth`."""
    if not settings.limits_enforced:
        return
    premium_owner = exists().where(
        ListOwner.list_id == list_id, premium_condition(ListOwner.user_id, now)
    )
    if db.scalar(select(premium_owner)):
        return
    used = db.scalars(select(func.count(Gift.id)).where(visibility.counted(list_id)))
    if used.one() >= settings.free_max_gifts_per_list:
        _refuse_gift(db, settings, list_id, now)


def _refuse_gift(
    db: Session, settings: Settings, list_id: uuid.UUID, now: datetime
) -> NoReturn:
    # Each owner's, the acting one among them: a lost event for any of them
    # may be why the list is not covered (D2).
    owners = db.scalars(
        select(ListOwner.user_id)
        .where(ListOwner.list_id == list_id)
        .order_by(ListOwner.user_id)
    )
    for owner in owners.all():
        warn_if_lapsed(db, owner, now)
    raise PlanLimitReached(GIFTS, settings.free_max_gifts_per_list)
