"""Reading and recording purchases, whatever their source (premium plan D2, D3).

A provider is one translator into `EntitlementFacts`; nothing here knows one.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from sqlalchemy import ColumnElement, and_, exists, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.models import ACTIVE, MANUAL, PAST_DUE, Entitlement

_log = logging.getLogger(__name__)

# A tolerance, not a commercial term: it absorbs a late renewal, and makes a
# row whose provider went silent end by itself (D2).
GRACE = timedelta(days=3)

_GRANTING = (ACTIVE, PAST_DUE)


@dataclass(frozen=True)
class EntitlementFacts:
    """A purchase as its provider states it now."""

    source: str
    external_id: str
    user_id: uuid.UUID
    status: str
    period_end: datetime | None
    cancel_at_period_end: bool
    started_at: datetime | None


@dataclass(frozen=True)
class EntitlementSummary:
    """What a person's plan is, by the words of `GET /api/billing` (D11)."""

    plan: str
    source: str | None
    status: str | None
    renews_at: datetime | None
    ends_at: datetime | None


class Applied(Enum):
    RECORDED = "recorded"
    USER_GONE = "user_gone"


def apply(db: Session, facts: EntitlementFacts, read_at: datetime) -> Applied:
    """Records what the provider said at `read_at`, unless a read at least as
    recent has been recorded (D13). An older read is a success too: the row
    already says more.

    The user is locked first, so an account's deletion and this take turns:
    a purchase that completes after the deletion finds no user.
    """
    user = db.scalar(
        select(User.id)
        .where(User.id == facts.user_id)
        .with_for_update(read=True, key_share=True)
    )
    if user is None:
        return Applied.USER_GONE
    statement = insert(Entitlement).values(
        source=facts.source,
        external_id=facts.external_id,
        user_id=facts.user_id,
        status=facts.status,
        period_end=facts.period_end,
        cancel_at_period_end=facts.cancel_at_period_end,
        started_at=facts.started_at,
        read_at=read_at,
    )
    new = statement.excluded
    db.execute(
        statement.on_conflict_do_update(
            index_elements=["source", "external_id"],
            set_={
                # The provider says whose it is, as it says everything else.
                "user_id": new.user_id,
                "status": new.status,
                "period_end": new.period_end,
                "cancel_at_period_end": new.cancel_at_period_end,
                "started_at": new.started_at,
                "read_at": new.read_at,
                "updated_at": func.now(),
            },
            where=Entitlement.read_at <= new.read_at,
        )
    )
    return Applied.RECORDED


def record_consent(
    db: Session, source: str, external_id: str, accepted_at: datetime, version: str
) -> None:
    """Stores the proof of consent on a purchase, whatever `read_at` says
    (D13): it arrives once and nothing supersedes it, so a redelivered event
    does not move the first acceptance."""
    db.execute(
        update(Entitlement)
        .where(
            Entitlement.source == source,
            Entitlement.external_id == external_id,
            Entitlement.terms_accepted_at.is_(None),
        )
        .values(
            terms_accepted_at=accepted_at, terms_version=version, updated_at=func.now()
        )
    )


def _in_force(now: datetime) -> ColumnElement[bool]:
    # A null `period_end` compares to null: never in force.
    return and_(Entitlement.status.in_(_GRANTING), Entitlement.period_end > now - GRACE)


def premium_condition(
    user_id: uuid.UUID | ColumnElement[uuid.UUID], now: datetime
) -> ColumnElement[bool]:
    """A SQL condition: is this person premium at `now` (D2)? `user_id` is a
    value or a column of the enclosing query, such as a list's owners."""
    return exists(
        select(Entitlement.id).where(Entitlement.user_id == user_id, _in_force(now))
    )


def is_premium(db: Session, user_id: uuid.UUID, now: datetime) -> bool:
    return bool(db.scalar(select(premium_condition(user_id, now))))


def warn_if_lapsed(db: Session, user_id: uuid.UUID, now: datetime) -> None:
    """Logs each row still granting premium past its grace: its provider's
    events were probably lost. Nothing runs when premium ends, so a lapse is
    only found where it is read (D2). Ids and fixed words only.

    A manual grant has no events to lose: its end is the date the admin chose
    (admin panel plan D8, review R1-6), so it is left out."""
    lapsed = db.execute(
        select(Entitlement.id, Entitlement.source).where(
            Entitlement.user_id == user_id,
            Entitlement.source != MANUAL,
            Entitlement.status.in_(_GRANTING),
            Entitlement.period_end <= now - GRACE,
        )
    )
    for entitlement_id, source in lapsed:
        _log.warning(
            "entitlement past its grace: id=%s source=%s", entitlement_id, source
        )
    # Not a lost event, so not the wording the runbook's resend answers: the
    # provider's facts came with no period end, and such a row grants nothing
    # (review R3-1).
    undated = db.execute(
        select(Entitlement.id, Entitlement.source).where(
            Entitlement.user_id == user_id,
            Entitlement.status.in_(_GRANTING),
            Entitlement.period_end.is_(None),
        )
    )
    for entitlement_id, source in undated:
        _log.warning(
            "entitlement granting status without a period end: id=%s source=%s",
            entitlement_id,
            source,
        )


def summary(db: Session, user_id: uuid.UUID, now: datetime) -> EntitlementSummary:
    """A person's plan. With several rows in force, the one that lasts longest
    is shown (D11).

    A cancellation outweighs a failing card: the subscription ends at
    `period_end` whether or not the card recovers.
    """
    warn_if_lapsed(db, user_id, now)
    row = db.scalar(
        select(Entitlement)
        .where(Entitlement.user_id == user_id, _in_force(now))
        .order_by(Entitlement.period_end.desc(), Entitlement.id)
        .limit(1)
    )
    if row is None:
        return EntitlementSummary("free", None, None, None, None)
    if row.cancel_at_period_end:
        return EntitlementSummary(
            "premium", row.source, "canceling", None, row.period_end
        )
    return EntitlementSummary("premium", row.source, row.status, row.period_end, None)
