"""The notification worker: fan-out, send, sweep, retention (comments plan D13,
D16), in a daemon thread of the app process, as the media purge.

Nothing it does waits on a request: who is notified is decided here, long
after the owner's response (D12). Each step commits on its own, and two app
processes running at once are safe: the fan-out and the send lock with `SKIP
LOCKED`, and the housekeeping runs in whichever process gets its lock.
"""

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import NamedTuple

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    String,
    and_,
    cast,
    delete,
    exists,
    func,
    literal,
    or_,
    select,
)
from sqlalchemy.orm import Session, sessionmaker

from app.comments.models import Comment, GiftFollow
from app.lists.models import Gift
from app.notifications import digests, fanout
from app.notifications.digests import EmailConfig
from app.notifications.mailer import BrevoMailer
from app.notifications.models import (
    GIFT_DELETED,
    GIFTS_REMOVED,
    EmailDigest,
    Notification,
    NotificationEvent,
)
from app.reserving.models import GiftClaim

_log = logging.getLogger(__name__)

RUN_INTERVAL = timedelta(seconds=15)
RETENTION = timedelta(days=30)
# An arbitrary constant, naming this one lock.
_HOUSEKEEPING_LOCK = 730_912_004


class RunCounts(NamedTuple):
    events: int
    notifications: int
    events_failed: int
    sent: int
    skipped: int
    retried: int
    send_failed: int
    swept: int
    retained: int


def _named_by_pending_event(gift_id: ColumnElement) -> ColumnElement[bool]:
    """Whether a `pending` event still has to read this gift's activity (D13).
    A `failed` event has given up, and waits for nothing."""
    listed = func.jsonb_build_object(
        "gifts",
        func.jsonb_build_array(
            func.jsonb_build_object("gift_id", cast(gift_id, String))
        ),
    )
    return exists().where(
        NotificationEvent.status == "pending",
        or_(
            and_(
                NotificationEvent.kind == GIFT_DELETED,
                NotificationEvent.gift_id == gift_id,
            ),
            and_(
                NotificationEvent.kind == GIFTS_REMOVED,
                NotificationEvent.payload.contains(listed),
            ),
        ),
    )


def _gift_gone(gift_id: ColumnElement) -> ColumnElement[bool]:
    return and_(~exists().where(Gift.id == gift_id), ~_named_by_pending_event(gift_id))


def _housekeeping_lock(db: Session) -> bool:
    """Taken for the transaction; False when the other process has it. Two
    sweeps deleting the same rows in another order could deadlock."""
    return bool(
        db.scalar(
            select(
                func.pg_try_advisory_xact_lock(literal(_HOUSEKEEPING_LOCK, BigInteger))
            )
        )
    )


def sweep(session_factory: sessionmaker[Session]) -> int:
    """Deletes the activity of every gift gone and read by no pending event,
    and unbought claims with no occasion (D13). Each table's choice is one
    statement, a single snapshot: an event committed with its gift's deletion
    is seen by the statement that sees the deletion.

    Claims are locked in `gift_id` order, skipping any held: a giver's release
    locks them in that order too, and the sweep never waits on it, so the two
    cannot deadlock (review R6-1). A claim skipped goes at a later run."""
    with session_factory() as db, db.begin():
        if not _housekeeping_lock(db):
            return 0
        claims = db.scalars(
            select(GiftClaim.gift_id)
            .where(
                or_(
                    _gift_gone(GiftClaim.gift_id),
                    and_(
                        GiftClaim.occasion_id.is_(None),
                        GiftClaim.bought_at.is_(None),
                    ),
                )
            )
            .order_by(GiftClaim.gift_id)
            .with_for_update(skip_locked=True)
        ).all()
        swept = 0
        for statement in (
            delete(GiftClaim).where(GiftClaim.gift_id.in_(claims)),
            delete(Comment).where(_gift_gone(Comment.gift_id)),
            delete(GiftFollow).where(_gift_gone(GiftFollow.gift_id)),
        ):
            swept += db.execute(
                statement.execution_options(synchronize_session=False)
            ).rowcount
    return swept


def retain(session_factory: sessionmaker[Session], now: datetime) -> int:
    """Deletes what finished more than `RETENTION` ago (D16). A skipped or
    failed digest's end is its last claim: it has no `sent_at`. An event waits
    for its digests still to be sent."""
    cutoff = now - RETENTION
    finished_at = func.coalesce(
        EmailDigest.sent_at, EmailDigest.claimed_at, EmailDigest.created_at
    )
    expired_digests = select(EmailDigest.id).where(
        EmailDigest.status.in_(digests.FINISHED), finished_at < cutoff
    )
    with session_factory() as db, db.begin():
        if not _housekeeping_lock(db):
            return 0
        db.execute(
            delete(Notification)
            .where(Notification.email_digest_id.in_(expired_digests))
            .execution_options(synchronize_session=False)
        )
        retained = db.execute(
            delete(EmailDigest)
            .where(EmailDigest.id.in_(expired_digests))
            .execution_options(synchronize_session=False)
        ).rowcount
        retained += db.execute(
            delete(NotificationEvent)
            .where(
                NotificationEvent.status.in_(("done", "failed")),
                NotificationEvent.processed_at < cutoff,
                ~exists().where(
                    Notification.event_id == NotificationEvent.id,
                    EmailDigest.id == Notification.email_digest_id,
                    EmailDigest.status.in_((digests.PENDING, digests.SENDING)),
                ),
            )
            .execution_options(synchronize_session=False)
        ).rowcount
    return retained


def run_once(
    session_factory: sessionmaker[Session],
    mailer: BrevoMailer | None,
    config: EmailConfig,
    now: datetime,
    should_stop: Callable[[], bool] = lambda: False,
) -> RunCounts:
    """One run of D16's steps; one log line if it did anything, counts only."""
    fanned = fanout.fan_out_due(session_factory, now, should_stop)
    sent = digests.send_due(session_factory, mailer, config, now, should_stop)
    swept = sweep(session_factory)
    retained = retain(session_factory, now)
    counts = RunCounts(
        fanned.events,
        fanned.notifications,
        fanned.failed,
        sent.sent,
        sent.skipped,
        sent.retried,
        sent.failed,
        swept,
        retained,
    )
    if any(counts):
        _log.info(
            "notifications: events=%d notifications=%d events_failed=%d sent=%d"
            " skipped=%d retried=%d send_failed=%d swept=%d retained=%d",
            *counts,
        )
    return counts


class NotificationWorker:
    """The runs in a daemon thread of the app process (D16)."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        mailer: Callable[[], BrevoMailer | None],
        config: EmailConfig,
        clock: Callable[[], datetime],
        interval: timedelta = RUN_INTERVAL,
    ) -> None:
        self._session_factory = session_factory
        self._mailer = mailer
        self._config = config
        self._clock = clock
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name="notification-worker", daemon=True
        )

    def start(self) -> None:
        _make_visible()
        if self._config.missing:
            # The runbook greps for these names (DEPLOYMENT.md).
            _log.warning(
                "notifications: email is off, not set: %s",
                ", ".join(self._config.missing),
            )
        self._thread.start()

    def stop(self) -> None:
        """Returns once the run in progress has reached its next event or
        digest: a deployment does not wait for the whole batch."""
        self._stop.set()
        self._thread.join()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def _run(self) -> None:
        while not self._stop.wait(self._interval.total_seconds()):
            try:
                run_once(
                    self._session_factory,
                    self._mailer(),
                    self._config,
                    self._clock(),
                    self._stop.is_set,
                )
            except Exception as exc:
                # The next run tries again. The type only: an exception's text
                # can quote a row, and logs never hold personal data.
                _log.error("notifications: run failed (%s)", type(exc).__name__)


def _make_visible() -> None:
    # uvicorn configures its own loggers only, as for the media purge.
    _log.setLevel(logging.INFO)
    if not _log.hasHandlers():
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(levelname)s:     %(message)s"))
        _log.addHandler(handler)
