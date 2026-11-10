"""Signing in with an email address and a password (sign-in plan D5, D9, D10).

No answer depends on whether an address has an account: `start` only ever adds
a row for the worker to mail, and `sign-in` spends the same hashing on an
unknown address. Nothing here logs an address, a token or a password.
"""

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Request, Response, status
from sqlalchemy import BigInteger, Row, delete, exists, func, literal, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts import email_links, identities, passwords, sessions, throttle
from app.accounts.models import (
    LINK_CREATE,
    LINK_RESET,
    EmailLink,
    PasswordCredential,
    User,
    UserIdentity,
    UserSession,
)
from app.accounts.schemas import (
    DISPLAY_NAME_MAX_LENGTH,
    EmailComplete,
    EmailSignIn,
    EmailStart,
    SignedIn,
    UserOut,
)
from app.db import DbSession
from app.settings import Settings

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["accounts"])

# How long a mailed link works (D8).
LINK_LIFETIME = timedelta(hours=1)


def _too_many_attempts() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="too_many_attempts"
    )


def _link_gone() -> HTTPException:
    # One body for a forged, used or expired link.
    return HTTPException(
        status_code=status.HTTP_410_GONE, detail="This link is no longer valid"
    )


def _wrong_credentials() -> HTTPException:
    # One body for every failure, so it says nothing about the address (D10).
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Wrong email or password",
    )


def _client_ip(request: Request) -> str:
    # Correct behind Caddy: uvicorn runs with --proxy-headers.
    return request.client.host if request.client else "unknown"


def _has_identity(db: Session, address: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    UserIdentity.provider == identities.EMAIL,
                    UserIdentity.subject == address,
                )
            )
        )
    )


@router.post("/auth/email/start", status_code=status.HTTP_202_ACCEPTED)
def start_email_sign_in(body: EmailStart, request: Request, db: DbSession) -> Response:
    state = request.app.state
    if state.mailer is None or not state.settings.notification_secret.strip():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Email sign-in is not configured",
        )
    now = state.clock()
    # The IP first: a refusal here must not use up the address's own quota,
    # or anyone could spend it from a blocked IP.
    if not throttle.allowed(
        state.session_factory, throttle.START_PER_IP, _client_ip(request), now
    ):
        raise _too_many_attempts()
    if not throttle.allowed(
        state.session_factory, throttle.START_PER_ADDRESS, body.email, now
    ):
        # The same answer as any other: the limit reveals and sends nothing (D12).
        _log.warning("email_start_address_limited")
        return Response(status_code=status.HTTP_202_ACCEPTED)
    purpose = LINK_RESET if _has_identity(db, body.email) else LINK_CREATE
    db.add(
        EmailLink(
            address=body.email,
            purpose=purpose,
            language=body.language,
            created_at=now,
            expires_at=now + LINK_LIFETIME,
        )
    )
    return Response(status_code=status.HTTP_202_ACCEPTED)


@router.post("/auth/email/complete")
def complete_email_sign_in(
    body: EmailComplete, request: Request, db: DbSession
) -> SignedIn:
    state = request.app.state
    now = state.clock()
    if not throttle.allowed(
        state.session_factory, throttle.COMPLETE_PER_IP, _client_ip(request), now
    ):
        raise _too_many_attempts()
    link_id = email_links.read_token(_link_secret(state.settings), body.token)
    if link_id is None:
        raise _link_gone()
    # Before the first statement: hashing waits its turn (D11), and no lock or
    # connection may wait with it.
    password_hash = passwords.hash(body.password)
    link = _consume(db, link_id, now)
    if link is None:
        raise _link_gone()
    # The identity now, not the link's purpose: the holder has proven the
    # mailbox, so a link gone stale needs no refusal (D9).
    if (
        link.purpose == LINK_CREATE
        and body.display_name is None
        and not _has_identity(db, link.address)
    ):
        # Raised, so the request's rollback gives the link back.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="A display name is required",
        )
    user = identities.user_for(
        db,
        identities.EMAIL,
        link.address,
        link.address,
        body.display_name or link.address.partition("@")[0][:DISPLAY_NAME_MAX_LENGTH],
        refresh_name=False,
    )
    _set_password(db, user.id, password_hash, now)
    # After the password: a sign-in that verified the old one either finished
    # first, and its session goes here, or finds its hash replaced (`sign_in`).
    db.execute(
        delete(UserSession)
        .where(UserSession.user_id == user.id)
        .execution_options(synchronize_session=False)
    )
    # So that a second email cannot reset a password just chosen (D9, review
    # R1-4). Only live links: a dead one needs no end, and the worker's sweep
    # takes the rows expired for a day, in an order of its own.
    db.execute(
        update(EmailLink)
        .where(
            EmailLink.address == link.address,
            EmailLink.id != link_id,
            EmailLink.consumed_at.is_(None),
            EmailLink.expires_at > now,
        )
        .values(consumed_at=now)
        .execution_options(synchronize_session=False)
    )
    token = sessions.create(db, user.id, now)
    return SignedIn(token=token, user=_user_out(user))


@router.post("/auth/email/sign-in")
def sign_in_with_email(body: EmailSignIn, request: Request, db: DbSession) -> SignedIn:
    state = request.app.state
    now = state.clock()
    ip = _client_ip(request)
    # Never the address alone, so that nobody can lock someone out (D12).
    if not throttle.allowed(
        state.session_factory, throttle.SIGN_IN_PER_IP, ip, now
    ) or not throttle.allowed(
        state.session_factory,
        throttle.SIGN_IN_PER_ADDRESS_AND_IP,
        f"{body.email}|{ip}",
        now,
    ):
        raise _too_many_attempts()
    # In a transaction of its own, closed before hashing: a flood of sign-ins
    # queues on the semaphore (D11), and must not take every connection with it.
    with state.session_factory() as reading:
        found = reading.execute(
            select(PasswordCredential.user_id, PasswordCredential.password_hash)
            .join(UserIdentity, UserIdentity.user_id == PasswordCredential.user_id)
            .where(
                UserIdentity.provider == identities.EMAIL,
                UserIdentity.subject == body.email,
            )
        ).one_or_none()
    if found is None:
        passwords.dummy_verify(body.password)
        raise _wrong_credentials()
    user_id, stored_hash = found
    if not passwords.verify(stored_hash, body.password):
        raise _wrong_credentials()
    rehashed = (
        passwords.hash(body.password) if passwords.needs_rehash(stored_hash) else None
    )
    # The user first, the order of every request (`current_session`); then the
    # credential, still the one verified. A reset that committed since has
    # ended the sessions, and must end this one too (D9); one still running
    # waits here, and deletes this session once it goes on.
    user = db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update(read=True, key_share=True)
    )
    credential = (
        None
        if user is None
        else db.scalar(
            select(PasswordCredential)
            .where(
                PasswordCredential.user_id == user_id,
                PasswordCredential.password_hash == stored_hash,
            )
            .with_for_update()
        )
    )
    if user is None or credential is None:
        raise _wrong_credentials()
    if rehashed is not None:
        credential.password_hash = rehashed
        credential.updated_at = now
    token = sessions.create(db, user.id, now)
    return SignedIn(token=token, user=_user_out(user))


def _link_secret(settings: Settings) -> str:
    """The secret links are signed with. Left as the worker reads it, but a
    blank one is none at all: nobody may forge a token with it."""
    secret = settings.notification_secret
    return secret if secret.strip() else ""


def _consume(db: Session, link_id: uuid.UUID, now: datetime) -> Row | None:
    """Uses the link up, in one statement (D9); None if it is used, expired or
    was never there.

    Under a lock on its address, held to the end of the request: two links of
    one address used at once take turns, so the second finds itself ended by
    the first instead of deadlocking with it over each other's rows."""
    address = db.scalar(select(EmailLink.address).where(EmailLink.id == link_id))
    if address is None:
        return None
    db.execute(
        select(
            func.pg_advisory_xact_lock(
                func.hashtextextended(f"email_link:{address}", literal(0, BigInteger))
            )
        )
    )
    return db.execute(
        update(EmailLink)
        .where(
            EmailLink.id == link_id,
            EmailLink.consumed_at.is_(None),
            EmailLink.expires_at > now,
        )
        .values(consumed_at=now)
        .returning(EmailLink.address, EmailLink.purpose)
        .execution_options(synchronize_session=False)
    ).one_or_none()


def _set_password(
    db: Session, user_id: uuid.UUID, password_hash: str, now: datetime
) -> None:
    statement = insert(PasswordCredential).values(
        user_id=user_id, password_hash=password_hash, updated_at=now
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[PasswordCredential.user_id],
            set_={
                "password_hash": statement.excluded.password_hash,
                "updated_at": statement.excluded.updated_at,
            },
        )
    )


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name)
