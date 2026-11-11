"""What the admin panel reads (admin panel plan D5–D7). Counts and sizes
only, from the database: never a gift, a claim or an invitee, never the disk.
"""

import base64
import binascii
import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import and_, case, func, select, tuple_
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.orm import Session, aliased

from app.accounts.models import User, UserIdentity
from app.admin.schemas import (
    AdminList,
    AdminPhotos,
    AdminPlan,
    AdminSubscription,
    AdminUserRow,
    ManualGrant,
)
from app.billing.entitlements import GRACE, summary
from app.billing.models import ACTIVE, ENDED, MANUAL, PAST_DUE, STRIPE, Entitlement
from app.lists import visibility
from app.lists.models import Gift, List, ListOwner
from app.media.models import Image

PAGE_SIZE = 50

Cursor = tuple[datetime, uuid.UUID]


def users_page(
    db: Session, q: str | None, after: Cursor | None
) -> tuple[list[User], Cursor | None]:
    """A page of users, newest first, those whose address contains `q`
    (case-insensitive) when given, and where the next page starts."""
    query = select(User).order_by(User.created_at.desc(), User.id.desc())
    if q:
        # `strpos`, not `LIKE`: nothing in `q` is a wildcard.
        query = query.where(func.strpos(func.lower(User.email), q.lower()) > 0)
    if after is not None:
        query = query.where(tuple_(User.created_at, User.id) < tuple_(*after))
    users = list(db.scalars(query.limit(PAGE_SIZE + 1)))
    if len(users) <= PAGE_SIZE:
        return users, None
    last = users[PAGE_SIZE - 1]
    return users[:PAGE_SIZE], (last.created_at, last.id)


def encode_cursor(cursor: Cursor) -> str:
    created_at, user_id = cursor
    text = f"{created_at.isoformat()}|{user_id}"
    return base64.urlsafe_b64encode(text.encode()).decode().rstrip("=")


def decode_cursor(value: str) -> Cursor | None:
    """The cursor `encode_cursor` made, or None for anything else."""
    try:
        text = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        created_at, user_id = text.split("|")
        cursor = (datetime.fromisoformat(created_at), uuid.UUID(user_id))
    except binascii.Error, UnicodeDecodeError, ValueError:
        return None
    if cursor[0].tzinfo is None:
        return None
    return cursor


def user_rows(db: Session, users: list[User], now: datetime) -> list[AdminUserRow]:
    """Each user as the users list shows them (D5), in the order given."""
    ids = [user.id for user in users]
    if not ids:
        return []
    sign_in: defaultdict[uuid.UUID, list[str]] = defaultdict(list)
    for user_id, provider in db.execute(
        select(UserIdentity.user_id, UserIdentity.provider)
        .where(UserIdentity.user_id.in_(ids))
        .distinct()
        .order_by(UserIdentity.user_id, UserIdentity.provider)
    ):
        sign_in[user_id].append(provider)
    lists_owned = dict(
        db.execute(
            select(ListOwner.user_id, func.count())
            .where(ListOwner.user_id.in_(ids))
            .group_by(ListOwner.user_id)
        ).all()
    )
    photos = _photos(db, ids, now)
    subscriptions = _subscriptions(db, ids, now)
    grants = _manual_grants(db, ids)
    return [
        AdminUserRow(
            id=user.id,
            email=user.email,
            display_name=user.display_name,
            created_at=user.created_at,
            sign_in=sign_in[user.id],
            plan=plan(db, user.id, now),
            subscription=subscriptions.get(user.id),
            manual_grant=grants.get(user.id),
            lists_owned=lists_owned.get(user.id, 0),
            photos=photos.get(user.id, AdminPhotos(count=0, bytes=0, measuring=False)),
        )
        for user in users
    ]


def plan(db: Session, user_id: uuid.UUID, now: datetime) -> AdminPlan:
    """The plan by the rule of `GET /api/billing`, from the same function."""
    state = summary(db, user_id, now)
    return AdminPlan(
        plan=state.plan,
        source=state.source,
        until=state.renews_at or state.ends_at,
    )


def _subscriptions(
    db: Session, ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, AdminSubscription]:
    """By user, their Stripe subscription, apart from any grant (owner,
    2026-11-11): the one in force, the longest first as `summary` picks it,
    else the latest started. One query for the page."""
    # `entitlements._in_force`, which is private to billing.
    in_force = and_(
        Entitlement.status.in_((ACTIVE, PAST_DUE)),
        Entitlement.period_end > now - GRACE,
    )
    rows = db.execute(
        select(
            Entitlement.user_id,
            Entitlement.status,
            Entitlement.cancel_at_period_end,
            Entitlement.started_at,
            Entitlement.period_end,
            in_force.label("in_force"),
        )
        .where(Entitlement.user_id.in_(ids), Entitlement.source == STRIPE)
        .ext(distinct_on(Entitlement.user_id))
        .order_by(
            Entitlement.user_id,
            # Null without a `period_end`, which Postgres sorts first.
            in_force.desc().nulls_last(),
            case((in_force, Entitlement.period_end)).desc().nulls_last(),
            Entitlement.started_at.desc().nulls_last(),
            Entitlement.created_at.desc(),
            Entitlement.id,
        )
    )
    return {
        user_id: AdminSubscription(
            status=_subscription_status(status, cancel, granting),
            started_at=started_at,
            period_end=period_end,
        )
        for user_id, status, cancel, started_at, period_end, granting in rows
    }


def _subscription_status(status: str, cancel: bool, in_force: bool) -> str:
    """The words of `summary`: a cancellation outweighs a failing card. A
    granting status past its grace grants nothing, so it reads `ended`."""
    if status not in (ACTIVE, PAST_DUE):
        return status
    if not in_force:
        return ENDED
    return "canceling" if cancel else status


def _manual_grants(db: Session, ids: list[uuid.UUID]) -> dict[uuid.UUID, ManualGrant]:
    """By user, the admin's grant not yet ended, as `active_manual_grant`
    finds it (D8). One query for the page."""
    rows = db.execute(
        select(Entitlement.user_id, Entitlement.period_end)
        .where(
            Entitlement.user_id.in_(ids),
            Entitlement.source == MANUAL,
            Entitlement.status == ACTIVE,
            Entitlement.period_end.is_not(None),
        )
        .ext(distinct_on(Entitlement.user_id))
        .order_by(Entitlement.user_id, Entitlement.period_end.desc(), Entitlement.id)
    )
    return {user_id: ManualGrant(period_end=period_end) for user_id, period_end in rows}


def _photos(
    db: Session, ids: list[uuid.UUID], now: datetime
) -> dict[uuid.UUID, AdminPhotos]:
    """By uploader, the images on a gift its list's owners see (D7, review
    R1-1): a pending upload and a hidden gift's photo are a giver's activity,
    and count for no one. A gift has one image, an image one gift."""
    rows = db.execute(
        select(
            Image.uploaded_by,
            func.count(Image.id),
            func.coalesce(func.sum(Image.bytes), 0),
            func.bool_or(Image.bytes.is_(None)),
        )
        .join(Gift, Gift.image_id == Image.id)
        .where(Image.uploaded_by.in_(ids), visibility.owner_visible_anywhere(now))
        .group_by(Image.uploaded_by)
    )
    return {
        uploader: AdminPhotos(count=count, bytes=size, measuring=measuring)
        for uploader, count, size, measuring in rows
        if uploader is not None
    }


def lists_of(db: Session, user_id: uuid.UUID) -> list[AdminList]:
    """The lists the user owns, oldest first, as counts (D6). The gift count
    is `GET /api/lists`'s: hidden, revealed and received gifts never count."""
    gift_count = (
        select(func.count(Gift.id)).where(visibility.counted(List.id)).scalar_subquery()
    )
    owners = aliased(ListOwner)
    owner_count = (
        select(func.count())
        .select_from(owners)
        .where(owners.list_id == List.id)
        .scalar_subquery()
    )
    rows = db.execute(
        select(List, gift_count, owner_count)
        .join(ListOwner, ListOwner.list_id == List.id)
        .where(ListOwner.user_id == user_id)
        .order_by(List.created_at, List.id)
    )
    return [
        AdminList(
            id=found.id,
            title=found.title,
            created_at=found.created_at,
            gift_count=gifts,
            owner_count=owners,
        )
        for found, gifts, owners in rows
    ]


def active_manual_grant(
    db: Session, user_id: uuid.UUID, lock: bool = False
) -> Entitlement | None:
    """The admin's grant not yet ended, if any: at most one (D8)."""
    query = select(Entitlement).where(
        Entitlement.user_id == user_id,
        Entitlement.source == MANUAL,
        Entitlement.status == ACTIVE,
    )
    if lock:
        query = query.with_for_update()
    return db.scalars(query).first()
