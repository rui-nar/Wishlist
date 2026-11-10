"""Mails the sign-in links (sign-in plan D6), by the digests' rules.

A link is claimed under `FOR UPDATE SKIP LOCKED` and committed `sending` before
Brevo is called: a process killed there loses that email rather than sending it
twice, and a link found `sending` too long is never resent. Sent here, not in
the request, so that the time of an answer reveals nothing (D5).
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, and_, or_, select, update
from sqlalchemy.orm import Session, sessionmaker

from app.accounts.email_links import make_token
from app.accounts.models import (
    LINK_CREATE,
    LINK_FAILED,
    LINK_PENDING,
    LINK_SENDING,
    LINK_SENT,
    LINK_SKIPPED,
    EmailLink,
)
from app.notifications.digests import (
    SEND_BACKOFF,
    SEND_BATCH,
    STALE_SENDING,
    EmailConfig,
    SendCounts,
)
from app.notifications.email_content import EmailMessage, render_sign_in_link
from app.notifications.mailer import BrevoMailer, Outcome

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class _Claimed:
    link_id: uuid.UUID
    address: str
    # None when it ended without a send.
    message: EmailMessage | None


def _retry_due(now: datetime) -> ColumnElement[bool]:
    """Whether a pending link's backoff is over: the wait after each refusal
    counts from the claim it followed, as the digests' `next_attempt_at`."""
    return or_(
        EmailLink.attempts == 0,
        *(
            and_(EmailLink.attempts == attempt, EmailLink.claimed_at <= now - wait)
            for attempt, wait in enumerate(SEND_BACKOFF, start=1)
        ),
    )


def send_due(
    session_factory: sessionmaker[Session],
    mailer: BrevoMailer | None,
    config: EmailConfig,
    now: datetime,
    should_stop: Callable[[], bool] = lambda: False,
) -> SendCounts:
    """Up to `SEND_BATCH` due links, taken one at a time."""
    with session_factory() as db, db.begin():
        skipped, failed = _finish_dead(db, now)
    sent = retried = 0
    for _ in range(SEND_BATCH):
        if should_stop():
            break
        claimed = _take_next(session_factory, mailer, config, now)
        if claimed is None:
            break
        if claimed.message is None:
            skipped += 1
            continue
        assert mailer is not None  # no message without one
        outcome = _deliver(mailer, claimed)
        with session_factory() as db, db.begin():
            status = _record(db, claimed.link_id, outcome)
        sent += status == LINK_SENT
        retried += status == LINK_PENDING
        failed += status == LINK_FAILED
    return SendCounts(sent, skipped, retried, failed)


def _finish_dead(db: Session, now: datetime) -> tuple[int, int]:
    """Links no use to send, and links left `sending` by a crash: maybe
    accepted, maybe not, so never sent again. Skips what a request holds: it
    comes up again at the next run."""

    def end(where: ColumnElement[bool], status: str) -> int:
        chosen = select(EmailLink.id).where(where).with_for_update(skip_locked=True)
        return db.execute(
            update(EmailLink)
            .where(EmailLink.id.in_(chosen))
            .values(status=status)
            .execution_options(synchronize_session=False)
        ).rowcount

    skipped = end(
        and_(
            EmailLink.status == LINK_PENDING,
            or_(EmailLink.consumed_at.is_not(None), EmailLink.expires_at <= now),
        ),
        LINK_SKIPPED,
    )
    failed = end(
        and_(
            EmailLink.status == LINK_SENDING,
            EmailLink.claimed_at < now - STALE_SENDING,
        ),
        LINK_FAILED,
    )
    return skipped, failed


def _take_next(
    session_factory: sessionmaker[Session],
    mailer: BrevoMailer | None,
    config: EmailConfig,
    now: datetime,
) -> _Claimed | None:
    """The next due link, claimed and committed; None when there is none."""
    with session_factory() as db, db.begin():
        link = db.scalar(
            select(EmailLink)
            .where(
                EmailLink.status == LINK_PENDING,
                EmailLink.consumed_at.is_(None),
                EmailLink.expires_at > now,
                _retry_due(now),
            )
            .order_by(EmailLink.created_at, EmailLink.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        if link is None:
            return None
        link.claimed_at = now
        message = _prepare(link, mailer, config)
        if message is None:
            link.status = LINK_SKIPPED
        else:
            link.status = LINK_SENDING
            link.attempts += 1
        return _Claimed(link.id, link.address, message)


def _prepare(
    link: EmailLink, mailer: BrevoMailer | None, config: EmailConfig
) -> EmailMessage | None:
    """The email to send; None when email is off, or the address is not one
    this environment may write to (VAL holds PROD's addresses, D6)."""
    if mailer is None or config.missing:
        return None
    if (
        config.allowed_addresses is not None
        and link.address.casefold() not in config.allowed_addresses
    ):
        return None
    creating = link.purpose == LINK_CREATE
    # In the fragment: it reaches neither the proxy's logs nor a `Referer` (D8).
    page = "create-account" if creating else "reset-password"
    token = make_token(config.notification_secret, link.id)
    return render_sign_in_link(
        link.language, creating, f"{config.public_base_url}/{page}#{token}"
    )


def _deliver(mailer: BrevoMailer, claimed: _Claimed) -> Outcome:
    assert claimed.message is not None  # only what has a message is delivered
    try:
        # No name: nobody has given one yet, and none can reach a header.
        return mailer.send(claimed.address, "", claimed.message)
    except Exception as exc:
        # Whatever it was may have come after Brevo accepted the email.
        _log.error(
            "notifications: link %s send raised %s",
            claimed.link_id,
            type(exc).__name__,
        )
        return Outcome.UNKNOWN


def _record(db: Session, link_id: uuid.UUID, outcome: Outcome) -> str:
    """Writes what became of the send, and returns the link's new status. A
    refusal is retried after the digests' waits, and the sixth ends it."""
    link = db.get_one(EmailLink, link_id)
    if link.status != LINK_SENDING:
        return link.status
    if outcome is Outcome.SENT:
        link.status = LINK_SENT
    elif outcome is Outcome.RETRY and link.attempts <= len(SEND_BACKOFF):
        link.status = LINK_PENDING
    else:
        link.status = LINK_FAILED
    return link.status
