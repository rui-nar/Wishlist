"""Groups a person's notifications about a gift into one email, and sends it at
most once (comments plan D15, D19).

A digest is claimed under `FOR UPDATE SKIP LOCKED` and committed `sending`
before Brevo is called: a process killed there loses that email rather than
sending it twice, and a digest found `sending` too long is never resent.

An advisory lock on (person, occasion, gift) serialises the writes that create
or bring back a pending digest for that key, which its unique index allows only
once. Claiming does not take it: a claim only ever frees the slot.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import BigInteger, delete, func, literal, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session, sessionmaker

from app.accounts.models import User
from app.comments.models import Comment as CommentRow
from app.lists import visibility
from app.lists.access import giver_condition
from app.lists.models import Gift, Occasion
from app.notifications.email_content import (
    Comment,
    Digest,
    EmailMessage,
    Links,
    build_links,
    render,
)
from app.notifications.mailer import BrevoMailer, Outcome
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
from app.notifications.unsubscribe import make_token
from app.settings import Settings

_log = logging.getLogger(__name__)

# How long a first email waits, so that a quick correction joins it.
SETTLE = timedelta(minutes=1)
# At most one email per person and gift in this long (NEEDS).
WINDOW = timedelta(minutes=15)
SEND_BATCH = 50
# The waits after each of the first five refusals; the sixth ends it (D15).
SEND_BACKOFF = tuple(timedelta(minutes=m) for m in (1, 5, 30, 120, 720))
# A `sending` row this old was left by a crash: a send lasts seconds.
STALE_SENDING = timedelta(minutes=10)

PENDING = "pending"
SENDING = "sending"
SENT = "sent"
SKIPPED = "skipped"
FAILED = "failed"
FINISHED = (SENT, SKIPPED, FAILED)

NOT_GIVER = "not_giver"
OPTED_OUT = "opted_out"
NOT_CONFIGURED = "not_configured"
NOT_ALLOWED = "not_allowed"
EMPTY = "empty"
UNKNOWN = "unknown"
REJECTED = "rejected"
RETRIES = "retries"
ERROR = "error"


@dataclass(frozen=True)
class EmailConfig:
    public_base_url: str
    notification_secret: str
    # Outside production, the only addresses emailed, casefolded; None in
    # production, where every account with notifications on is.
    allowed_addresses: frozenset[str] | None
    # The variables that keep email off, by name; empty when it can be sent.
    missing: tuple[str, ...]

    @classmethod
    def from_settings(cls, settings: Settings) -> EmailConfig:
        return cls(
            public_base_url=settings.public_base_url.strip().rstrip("/"),
            notification_secret=settings.notification_secret,
            allowed_addresses=(
                None
                if settings.app_env == "production"
                else settings.email_allowed_addresses
            ),
            missing=tuple(settings.missing_email_settings),
        )


class SendCounts(NamedTuple):
    sent: int = 0
    skipped: int = 0
    retried: int = 0
    failed: int = 0


@dataclass(frozen=True)
class _Outgoing:
    to_address: str
    to_name: str
    message: EmailMessage


@dataclass(frozen=True)
class _Taken:
    digest_id: uuid.UUID
    # None when it ended without a send: its status says how.
    outgoing: _Outgoing | None
    status: str


def _lock_key(
    db: Session, user_id: uuid.UUID, occasion_id: uuid.UUID, gift_id: uuid.UUID
) -> None:
    key = f"email_digest:{user_id}:{occasion_id}:{gift_id}"
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(key, literal(0, BigInteger))
            )
        )
    )


def attach(
    db: Session,
    notification_id: int,
    user_id: uuid.UUID,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    now: datetime,
) -> None:
    """Attaches the notification to the pending digest of its key, or to a new
    one due after the settle minute (D15).

    The upsert takes the pending row's lock: a claim either committed before
    (no conflict, a new row) or waits for this transaction and sends the
    notification. `last` is read after it, so a claim that committed before is
    counted; one still to come needs this row, so cannot have happened.
    """
    _lock_key(db, user_id, occasion_id, gift_id)
    statement = insert(EmailDigest).values(
        user_id=user_id,
        occasion_id=occasion_id,
        gift_id=gift_id,
        send_after=now + SETTLE,
    )
    digest_id = db.scalar(
        statement.on_conflict_do_update(
            index_elements=["user_id", "occasion_id", "gift_id"],
            # Literal, not a bound parameter: once psycopg prepares a repeated
            # statement, PostgreSQL could no longer match it to the index.
            index_where=text(f"status = '{PENDING}'"),
            set_={"user_id": statement.excluded.user_id},
        ).returning(EmailDigest.id)
    )
    last = db.scalar(
        select(func.max(EmailDigest.claimed_at)).where(
            EmailDigest.user_id == user_id,
            EmailDigest.occasion_id == occasion_id,
            EmailDigest.gift_id == gift_id,
            EmailDigest.id != digest_id,
        )
    )
    if last is not None:
        db.execute(
            update(EmailDigest)
            .where(EmailDigest.id == digest_id, EmailDigest.send_after < last + WINDOW)
            .values(send_after=last + WINDOW)
            .execution_options(synchronize_session=False)
        )
    db.execute(
        update(Notification)
        .where(Notification.id == notification_id)
        .values(email_digest_id=digest_id)
        .execution_options(synchronize_session=False)
    )


def send_due(
    session_factory: sessionmaker[Session],
    mailer: BrevoMailer | None,
    config: EmailConfig,
    now: datetime,
    should_stop: Callable[[], bool] = lambda: False,
) -> SendCounts:
    """Up to `SEND_BATCH` due digests, taken one at a time: each is `sending`
    only for its own call to Brevo."""
    with session_factory() as db, db.begin():
        failed = _fail_stale(db, now)
    sent = skipped = retried = 0
    for _ in range(SEND_BATCH):
        if should_stop():
            break
        taken = _take_next(session_factory, mailer, config, now)
        if taken is None:
            break
        if taken.outgoing is None:
            skipped += taken.status == SKIPPED
            failed += taken.status == FAILED
            continue
        assert mailer is not None  # no outgoing email without one
        outcome = _deliver(mailer, taken.digest_id, taken.outgoing)
        with session_factory() as db, db.begin():
            status = _record(db, taken.digest_id, outcome, now)
        sent += status == SENT
        retried += status == PENDING
        failed += status == FAILED
    return SendCounts(sent, skipped, retried, failed)


def _fail_stale(db: Session, now: datetime) -> int:
    """`sending` for too long: maybe accepted, maybe not, so never sent again
    (D15)."""
    return db.execute(
        update(EmailDigest)
        .where(
            EmailDigest.status == SENDING,
            EmailDigest.claimed_at < now - STALE_SENDING,
        )
        .values(status=FAILED, skip_reason=UNKNOWN)
        .execution_options(synchronize_session=False)
    ).rowcount


def _take_next(
    session_factory: sessionmaker[Session],
    mailer: BrevoMailer | None,
    config: EmailConfig,
    now: datetime,
) -> _Taken | None:
    """The next due digest, claimed and committed; None when there is none.

    What it says is read now, in the claiming transaction: a comment deleted
    or edited until this moment is left out or shown as it stands."""
    with session_factory() as db, db.begin():
        digest = db.scalar(
            select(EmailDigest)
            .where(
                EmailDigest.status == PENDING,
                EmailDigest.send_after <= now,
                or_(
                    EmailDigest.next_attempt_at.is_(None),
                    EmailDigest.next_attempt_at <= now,
                ),
            )
            .order_by(EmailDigest.send_after, EmailDigest.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if digest is None:
            return None
        digest.claimed_at = now
        try:
            with db.begin_nested():
                prepared = _prepare(db, digest, mailer, config)
        except Exception as exc:
            # An unexpected fault in what it says would recur at each run.
            digest.status = FAILED
            digest.skip_reason = ERROR
            _log.error(
                "notifications: digest %s failed (%s)",
                digest.id,
                type(exc).__name__,
            )
            return _Taken(digest.id, None, FAILED)
        if isinstance(prepared, str):
            digest.status = SKIPPED
            digest.skip_reason = prepared
            return _Taken(digest.id, None, SKIPPED)
        digest.status = SENDING
        digest.attempts += 1
        return _Taken(digest.id, prepared, SENDING)


def _prepare(
    db: Session,
    digest: EmailDigest,
    mailer: BrevoMailer | None,
    config: EmailConfig,
) -> _Outgoing | str:
    """The email to send, or the word that says why none is (D15)."""
    if not db.scalar(select(giver_condition(digest.user_id, digest.occasion_id))):
        return NOT_GIVER
    user = db.get_one(User, digest.user_id)
    if not user.email_notifications:
        return OPTED_OUT
    if mailer is None or config.missing:
        return NOT_CONFIGURED
    if (
        config.allowed_addresses is not None
        and user.email.strip().casefold() not in config.allowed_addresses
    ):
        return NOT_ALLOWED
    token = make_token(config.notification_secret, user.id)
    links = build_links(
        config.public_base_url, digest.occasion_id, digest.gift_id, token
    )
    content = _content(db, digest, user, links)
    if content is None:
        return EMPTY
    return _Outgoing(user.email, user.display_name, render(content))


def _content(
    db: Session, digest: EmailDigest, user: User, links: Links
) -> Digest | None:
    """What the email says, or None when everything it would have said has
    gone. A deletion or removal says that and nothing else about the gift."""
    occasion = db.get_one(Occasion, digest.occasion_id)

    def digest_of(title: str, **rest) -> Digest:
        return Digest(
            recipient_name=user.display_name,
            language=user.language,
            occasion_name=occasion.name,
            gift_title=title,
            links=links,
            **rest,
        )

    items = db.execute(
        select(
            NotificationEvent.kind,
            NotificationEvent.payload,
            NotificationEvent.actor_id,
        )
        .join(Notification, Notification.event_id == NotificationEvent.id)
        .where(Notification.email_digest_id == digest.id)
        .order_by(NotificationEvent.created_at, NotificationEvent.id)
    ).all()
    for kind, payload, _actor in items:
        if kind == GIFT_DELETED:
            return digest_of(payload["title"], gift_deleted=True)
    for kind, payload, _actor in items:
        if kind == GIFTS_REMOVED:
            title = next(
                entry["title"]
                for entry in payload["gifts"]
                if entry["gift_id"] == str(digest.gift_id)
            )
            return digest_of(title, hidden_gift_removed=True)

    # What remains is about a gift its givers still see.
    gift = db.scalar(
        select(Gift).where(Gift.id == digest.gift_id, visibility.in_occasion(occasion))
    )
    if gift is None:
        return None
    fields = dict.fromkeys(
        field
        for kind, payload, _actor in items
        if kind == GIFT_CHANGED
        for field in payload["fields"]
    )
    comments = _comments(
        db,
        digest,
        [
            uuid.UUID(payload["comment_id"])
            for kind, payload, _actor in items
            if kind == COMMENT_ADDED
        ],
    )
    left = tuple(
        None if actor is None else db.get_one(User, actor).display_name
        for kind, _payload, actor in items
        if kind == PARTICIPANTS_LEFT
    )
    if not fields and not comments and not left:
        return None
    return digest_of(
        gift.title,
        fields_changed=tuple(fields),
        comments=comments,
        participants_left=left,
    )


def _comments(
    db: Session, digest: EmailDigest, comment_ids: list[uuid.UUID]
) -> tuple[Comment, ...]:
    """The comments still there, as they stand now, by their author's current
    name; null when the account was deleted."""
    rows = db.execute(
        select(User.display_name, CommentRow.body)
        .select_from(CommentRow)
        .outerjoin(User, User.id == CommentRow.author_id)
        .where(
            CommentRow.id.in_(comment_ids),
            CommentRow.occasion_id == digest.occasion_id,
            CommentRow.gift_id == digest.gift_id,
        )
        .order_by(CommentRow.created_at, CommentRow.id)
    )
    return tuple(Comment(author_name=name, body=body) for name, body in rows)


def _deliver(mailer: BrevoMailer, digest_id: uuid.UUID, outgoing: _Outgoing) -> Outcome:
    try:
        return mailer.send(outgoing.to_address, outgoing.to_name, outgoing.message)
    except Exception as exc:
        # Whatever it was may have come after Brevo accepted the email.
        _log.error(
            "notifications: digest %s send raised %s", digest_id, type(exc).__name__
        )
        return Outcome.UNKNOWN


def _record(db: Session, digest_id: uuid.UUID, outcome: Outcome, now: datetime) -> str:
    """Writes what became of the send, and returns the digest's new status."""
    if outcome is Outcome.RETRY:
        return _requeue(db, digest_id, now)
    if outcome is Outcome.SENT:
        status, values = SENT, {"status": SENT, "sent_at": now}
    else:
        reason = REJECTED if outcome is Outcome.REJECTED else UNKNOWN
        status, values = FAILED, {"status": FAILED, "skip_reason": reason}
    db.execute(
        update(EmailDigest)
        .where(EmailDigest.id == digest_id, EmailDigest.status == SENDING)
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    return status


def _requeue(db: Session, digest_id: uuid.UUID, now: datetime) -> str:
    """Brevo definitely refused it: pending again after the backoff, or failed
    after the last attempt (D15).

    While it was `sending` a new pending digest may have started for its key;
    the index allows one, so this one takes its notifications and its place,
    keeping its own count of attempts.
    """
    digest = db.get_one(EmailDigest, digest_id)
    if digest.status != SENDING:
        return digest.status
    if digest.attempts > len(SEND_BACKOFF):
        digest.status = FAILED
        digest.skip_reason = RETRIES
        return FAILED
    _lock_key(db, digest.user_id, digest.occasion_id, digest.gift_id)
    newer_id = db.scalar(
        select(EmailDigest.id)
        .where(
            EmailDigest.user_id == digest.user_id,
            EmailDigest.occasion_id == digest.occasion_id,
            EmailDigest.gift_id == digest.gift_id,
            EmailDigest.status == PENDING,
        )
        .with_for_update()
    )
    if newer_id is not None:
        db.execute(
            update(Notification)
            .where(Notification.email_digest_id == newer_id)
            .values(email_digest_id=digest_id)
            .execution_options(synchronize_session=False)
        )
        db.execute(
            delete(EmailDigest)
            .where(EmailDigest.id == newer_id)
            .execution_options(synchronize_session=False)
        )
    digest.status = PENDING
    digest.next_attempt_at = now + SEND_BACKOFF[digest.attempts - 1]
    return PENDING
