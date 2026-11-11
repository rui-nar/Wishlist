"""The rows the worker's tests start from, written directly, so each case sets
exactly the state it needs and every time is the test's clock.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.media.models  # noqa: F401 (for the mapper: `gifts` refers to `images`)
from app.accounts.models import User
from app.comments.models import Comment, GiftFollow
from app.lists.models import (
    OTHER,
    SELF,
    Gift,
    List,
    ListOwner,
    Occasion,
    OccasionMember,
)
from app.notifications.digests import EmailConfig
from app.notifications.models import (
    COMMENT_ADDED,
    GIFT_CHANGED,
    GIFT_DELETED,
    GIFTS_REMOVED,
    PARTICIPANTS_LEFT,
    EmailDigest,
    Notification,
    NotificationEvent,
)
from app.reserving.models import GROUP, RESERVATION, ClaimParticipant, GiftClaim

NOW = datetime(2026, 11, 8, 12, tzinfo=UTC)
FUTURE: date = NOW.date() + timedelta(days=60)
PASSED: date = NOW.date() - timedelta(days=30)
MINUTE = timedelta(minutes=1)
BASE_URL = "https://shushgift.example.test"
SECRET = "a-test-notification-secret"


def config(production: bool = True, allowed: frozenset[str] = frozenset()):
    """Email fully configured; outside production, `allowed` is the allow-list."""
    return EmailConfig(
        public_base_url=BASE_URL,
        notification_secret=SECRET,
        allowed_addresses=None if production else allowed,
        missing=(),
    )


@dataclass
class World:
    engine: Engine

    @property
    def sessions(self) -> sessionmaker[Session]:
        return sessionmaker(bind=self.engine)

    def _add(self, row: Any) -> Any:
        with Session(self.engine, expire_on_commit=False) as db, db.begin():
            db.add(row)
        return row

    def user(
        self,
        name: str = "Ada",
        language: str = "en",
        email: str | None = None,
        notifications: bool = True,
    ) -> uuid.UUID:
        return self._add(
            User(
                email=email or f"{uuid.uuid4().hex}@example.test",
                display_name=name,
                language=language,
                email_notifications=notifications,
            )
        ).id

    def listing(self, owner: uuid.UUID, kind: str = SELF) -> uuid.UUID:
        row = List(
            title="Birthday",
            recipient_kind=kind,
            recipient_name="Leo" if kind == OTHER else None,
        )
        self._add(row)
        self._add(ListOwner(list_id=row.id, user_id=owner))
        return row.id

    def occasion(
        self, list_id: uuid.UUID, on: date = FUTURE, name: str = "Summer party"
    ) -> uuid.UUID:
        return self._add(Occasion(list_id=list_id, name=name, date=on)).id

    def member(self, occasion: uuid.UUID, user: uuid.UUID) -> None:
        self._add(OccasionMember(occasion_id=occasion, user_id=user))

    def gift(
        self,
        list_id: uuid.UUID,
        title: str = "Scarf",
        received: bool = False,
    ) -> uuid.UUID:
        return self._add(
            Gift(
                list_id=list_id,
                title=title,
                description="",
                links=[],
                received_at=NOW if received else None,
            )
        ).id

    def hidden_gift(
        self, list_id: uuid.UUID, occasion: uuid.UUID, author: uuid.UUID, title: str
    ) -> uuid.UUID:
        return self._add(
            Gift(
                for_list_id=list_id,
                hidden_occasion_id=occasion,
                hidden_by=author,
                title=title,
                description="",
                links=[],
            )
        ).id

    def claim(
        self,
        gift: uuid.UUID,
        occasion: uuid.UUID | None,
        *participants: uuid.UUID,
        bought: bool = False,
        kind: str = RESERVATION,
    ) -> None:
        self._add(
            GiftClaim(
                gift_id=gift,
                occasion_id=occasion,
                kind=kind,
                bought_at=NOW if bought else None,
            )
        )
        for participant in participants:
            self._add(ClaimParticipant(gift_id=gift, user_id=participant))

    def group_claim(
        self, gift: uuid.UUID, occasion: uuid.UUID, *participants: uuid.UUID
    ) -> None:
        self.claim(gift, occasion, *participants, kind=GROUP)

    def comment(
        self,
        occasion: uuid.UUID,
        gift: uuid.UUID,
        author: uuid.UUID,
        body: str = "I'll take the blue one",
    ) -> uuid.UUID:
        return self._add(
            Comment(occasion_id=occasion, gift_id=gift, author_id=author, body=body)
        ).id

    def follow(
        self,
        occasion: uuid.UUID,
        gift: uuid.UUID,
        user: uuid.UUID,
        following: bool = True,
    ) -> None:
        self._add(
            GiftFollow(
                occasion_id=occasion, gift_id=gift, user_id=user, following=following
            )
        )

    def event(
        self,
        kind: str,
        payload: dict[str, Any],
        actor: uuid.UUID | None = None,
        gift: uuid.UUID | None = None,
        occasion: uuid.UUID | None = None,
        at: datetime = NOW,
    ) -> int:
        return self._add(
            NotificationEvent(
                kind=kind,
                payload=payload,
                actor_id=actor,
                gift_id=gift,
                occasion_id=occasion,
                created_at=at,
                next_attempt_at=at,
            )
        ).id

    def gift_changed(
        self,
        gift: uuid.UUID,
        actor: uuid.UUID,
        fields: tuple[str, ...] = ("title",),
        at: datetime = NOW,
    ) -> int:
        return self.event(
            GIFT_CHANGED, {"fields": list(fields)}, actor, gift=gift, at=at
        )

    def gift_deleted(
        self,
        gift: uuid.UUID,
        actor: uuid.UUID,
        title: str = "Scarf",
        received: bool = False,
        at: datetime = NOW,
    ) -> int:
        payload = {"title": title, "received": received}
        return self.event(GIFT_DELETED, payload, actor, gift=gift, at=at)

    def comment_added(
        self,
        occasion: uuid.UUID,
        gift: uuid.UUID,
        author: uuid.UUID | None,
        comment: uuid.UUID,
        at: datetime = NOW,
    ) -> int:
        return self.event(
            COMMENT_ADDED,
            {"comment_id": str(comment)},
            author,
            gift=gift,
            occasion=occasion,
            at=at,
        )

    def participants_left(
        self,
        actor: uuid.UUID | None,
        *gifts: tuple[uuid.UUID, uuid.UUID],
        at: datetime = NOW,
    ) -> int:
        listed = [
            {"gift_id": str(gift), "occasion_id": str(occasion)}
            for gift, occasion in gifts
        ]
        return self.event(PARTICIPANTS_LEFT, {"gifts": listed}, actor, at=at)

    def gifts_removed(
        self,
        occasion: uuid.UUID,
        actor: uuid.UUID,
        *gifts: tuple[uuid.UUID, str],
        at: datetime = NOW,
    ) -> int:
        listed = [{"gift_id": str(gift), "title": title} for gift, title in gifts]
        return self.event(
            GIFTS_REMOVED, {"gifts": listed}, actor, occasion=occasion, at=at
        )

    def delete_gift(self, gift: uuid.UUID) -> None:
        with Session(self.engine) as db, db.begin():
            db.delete(db.get_one(Gift, gift))

    # Reads.

    def targets(self, event_id: int) -> set[uuid.UUID]:
        with Session(self.engine) as db:
            return set(
                db.scalars(
                    select(Notification.user_id).where(
                        Notification.event_id == event_id
                    )
                )
            )

    def notifications(self, event_id: int) -> list[Notification]:
        with Session(self.engine) as db:
            return list(
                db.scalars(
                    select(Notification).where(Notification.event_id == event_id)
                )
            )

    def event_row(self, event_id: int) -> NotificationEvent:
        with Session(self.engine) as db:
            return db.get_one(NotificationEvent, event_id)

    def digests(self, user: uuid.UUID | None = None) -> list[EmailDigest]:
        query = select(EmailDigest).order_by(EmailDigest.send_after, EmailDigest.id)
        if user is not None:
            query = query.where(EmailDigest.user_id == user)
        with Session(self.engine) as db:
            return list(db.scalars(query))

    def set_digest(self, digest_id: uuid.UUID, **values: Any) -> None:
        with Session(self.engine) as db, db.begin():
            digest = db.get_one(EmailDigest, digest_id)
            for name, value in values.items():
                setattr(digest, name, value)
