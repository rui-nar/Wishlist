"""The worker's sending of sign-in links (sign-in plan D6): the allow-list, the
digests' retries, expiry, and two processes at once.
"""

import logging
import uuid
from collections import Counter
from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session
from test_concurrent_worker import together
from worker_world import BASE_URL, MINUTE, NOW, SECRET, World, config

from app.accounts import email_links as tokens
from app.accounts.models import AuthThrottle, EmailLink
from app.notifications.digests import SEND_BACKOFF, SEND_BATCH, STALE_SENDING
from app.notifications.email_content import _EN, _FR
from app.notifications.email_links import send_due
from app.notifications.mailer import Outcome
from app.notifications.worker import SIGN_IN_RETENTION, run_once, sweep_sign_in

ADDRESS = "ada@example.test"
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


@pytest.fixture(autouse=True)
def empty_sign_in_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE email_links, auth_throttle"))


@pytest.fixture
def world(engine) -> World:
    return World(engine)


def add_link(world, **values) -> uuid.UUID:
    row = EmailLink(
        **{
            "address": ADDRESS,
            "purpose": "create",
            "language": "en",
            "created_at": NOW,
            "expires_at": NOW + HOUR,
        }
        | values
    )
    with Session(world.engine, expire_on_commit=False) as db, db.begin():
        db.add(row)
    return row.id


def link(world, link_id: uuid.UUID) -> EmailLink:
    with Session(world.engine) as db:
        return db.get_one(EmailLink, link_id)


def send(world, mailer, now=NOW, cfg=None):
    return send_due(world.sessions, mailer, cfg or config(), now)


def test_a_pending_link_is_mailed_to_its_address_with_a_working_token(world, mailer):
    link_id = add_link(world)

    counts = send(world, mailer)

    assert counts.sent == 1
    [(to_address, to_name, message)] = mailer.sent
    assert to_address == ADDRESS
    assert to_name == ""  # nobody has given a name yet (D2)
    token = message.text.split(f"{BASE_URL}/create-account#")[1].split()[0]
    assert tokens.read_token(SECRET, token) == link_id
    assert f"{BASE_URL}/create-account#{token}" in message.html
    row = link(world, link_id)
    assert row.status == "sent" and row.attempts == 1 and row.claimed_at == NOW


def test_a_reset_link_goes_to_the_reset_page(world, mailer):
    add_link(world, purpose="reset")

    send(world, mailer)

    [(_address, _name, message)] = mailer.sent
    assert f"{BASE_URL}/reset-password#" in message.text
    assert "/create-account" not in message.text


@pytest.mark.parametrize(
    ("language", "strings", "purpose", "subject_key"),
    [
        ("en", _EN, "create", "sign_in_create_subject"),
        ("en", _EN, "reset", "sign_in_reset_subject"),
        ("fr", _FR, "create", "sign_in_create_subject"),
        ("fr", _FR, "reset", "sign_in_reset_subject"),
    ],
)
def test_the_email_is_in_the_links_language_with_the_two_lines(
    world, mailer, language, strings, purpose, subject_key
):
    add_link(world, language=language, purpose=purpose)

    send(world, mailer)

    [(_address, _name, message)] = mailer.sent
    assert message.subject == strings[subject_key]
    for key in ("sign_in_android", "sign_in_other_ways", "sign_in_lifetime"):
        assert strings[key] in message.text
        assert strings[key].replace("'", "&#x27;") in message.html
    assert message.headers == {}  # no unsubscribe: it is not a notification


def test_the_two_lines_say_what_the_plan_says():
    assert _EN["sign_in_other_ways"] == (
        "If you usually sign in with Google or Apple, use that button."
    )
    assert "Android" in _EN["sign_in_android"]
    assert "Android" in _FR["sign_in_android"]


# The allow-list (D6).


def test_outside_production_an_address_not_allowed_is_skipped(world, mailer):
    link_id = add_link(world)

    counts = send(world, mailer, cfg=config(production=False))

    assert counts.skipped == 1 and mailer.sent == []
    assert link(world, link_id).status == "skipped"


def test_outside_production_an_allowed_address_is_sent(world, mailer):
    add_link(world)

    counts = send(world, mailer, cfg=config(production=False, allowed={ADDRESS}))

    assert counts.sent == 1 and len(mailer.sent) == 1


def test_in_production_every_address_is_sent(world, mailer):
    add_link(world)

    assert send(world, mailer, cfg=config()).sent == 1


@pytest.mark.parametrize("why", ["mailer", "config"])
def test_email_off_skips_the_link(world, mailer, why):
    link_id = add_link(world)
    cfg = config()
    if why == "config":
        cfg = type(cfg)(
            cfg.public_base_url,
            cfg.notification_secret,
            cfg.allowed_addresses,
            ("BREVO_API_KEY",),
        )

    counts = send(world, None if why == "mailer" else mailer, cfg=cfg)

    assert counts.skipped == 1 and mailer.sent == []
    assert link(world, link_id).status == "skipped"


# Retries: the digests' rule (D6).


def test_a_temporary_refusal_waits_for_the_backoff(world, mailer):
    mailer.outcome = Outcome.RETRY
    link_id = add_link(world)

    assert send(world, mailer).retried == 1
    row = link(world, link_id)
    assert row.status == "pending" and row.attempts == 1

    # Not before the wait, to the second.
    send(world, mailer, NOW + MINUTE - timedelta(seconds=1))
    assert link(world, link_id).attempts == 1
    assert len(mailer.sent) == 1

    mailer.outcome = Outcome.SENT
    send(world, mailer, NOW + MINUTE)
    assert link(world, link_id).status == "sent"
    assert len(mailer.sent) == 2


def test_the_sixth_refusal_ends_it_after_the_digests_waits(world, mailer):
    mailer.outcome = Outcome.RETRY
    link_id = add_link(world, expires_at=NOW + 30 * DAY)

    now = NOW
    for attempt, wait in enumerate(SEND_BACKOFF, start=1):
        assert send(world, mailer, now).retried == 1
        assert link(world, link_id).attempts == attempt
        # Each wait counted from its own attempt.
        assert send(world, mailer, now + wait - timedelta(seconds=1)).retried == 0
        now += wait

    assert send(world, mailer, now).failed == 1
    row = link(world, link_id)
    assert row.status == "failed" and row.attempts == 6
    assert send(world, mailer, now + 30 * DAY).sent == 0
    assert len(mailer.sent) == 6


@pytest.mark.parametrize(
    "outcome",
    [Outcome.UNKNOWN, Outcome.REJECTED, RuntimeError("for someone@example.test")],
    ids=["unknown", "rejected", "raises"],
)
def test_anything_but_a_refusal_is_never_sent_again(world, mailer, outcome, caplog):
    mailer.outcome = outcome
    link_id = add_link(world)

    with caplog.at_level(logging.ERROR, logger="app.notifications.email_links"):
        assert send(world, mailer).failed == 1

    assert link(world, link_id).status == "failed"
    assert send(world, mailer, NOW + 10 * MINUTE).sent == 0
    assert len(mailer.sent) == 1
    for record in caplog.records:
        assert "example.test" not in record.getMessage()


def test_a_link_left_sending_by_a_crash_is_never_sent_again(world, mailer):
    link_id = add_link(
        world, status="sending", claimed_at=NOW - STALE_SENDING, attempts=1
    )

    assert send(world, mailer).failed == 0
    assert link(world, link_id).status == "sending"

    assert send(world, mailer, NOW + timedelta(seconds=1)).failed == 1
    assert link(world, link_id).status == "failed"
    assert mailer.sent == []


# Links past their use (D6, D8).


def test_an_expired_link_is_not_sent(world, mailer):
    link_id = add_link(world, expires_at=NOW)

    counts = send(world, mailer)

    assert counts.skipped == 1 and mailer.sent == []
    assert link(world, link_id).status == "skipped"


def test_a_link_expiring_during_its_retries_is_not_sent_again(world, mailer):
    mailer.outcome = Outcome.RETRY
    link_id = add_link(world, expires_at=NOW + HOUR)

    send(world, mailer)
    send(world, mailer, NOW + HOUR)

    assert link(world, link_id).status == "skipped"
    assert len(mailer.sent) == 1


def test_a_consumed_link_is_not_sent(world, mailer):
    link_id = add_link(world, consumed_at=NOW)

    counts = send(world, mailer)

    assert counts.skipped == 1 and mailer.sent == []
    assert link(world, link_id).status == "skipped"


def test_a_row_being_used_is_passed_over_without_waiting(world, mailer):
    # A request holds it: the worker's run neither waits nor sends it.
    link_id = add_link(world)
    with Session(world.engine) as holder, holder.begin():
        holder.execute(
            select(EmailLink).where(EmailLink.id == link_id).with_for_update()
        ).all()

        assert send(world, mailer).sent == 0

    assert mailer.sent == []
    assert send(world, mailer).sent == 1


def test_the_batch_is_bounded_and_the_rest_waits_for_the_next_run(world, mailer):
    with Session(world.engine) as db, db.begin():
        db.add_all(
            EmailLink(
                address=f"u{n}@example.test",
                purpose="create",
                language="en",
                created_at=NOW,
                expires_at=NOW + HOUR,
            )
            for n in range(SEND_BATCH + 1)
        )

    assert send(world, mailer).sent == SEND_BATCH
    assert send(world, mailer).sent == 1


# Two processes (Review envelope).


def test_two_workers_at_once_send_each_link_once(world, mailer):
    links = 30
    with Session(world.engine) as db, db.begin():
        db.add_all(
            EmailLink(
                address=f"u{n}@example.test",
                purpose="create",
                language="en",
                created_at=NOW,
                expires_at=NOW + HOUR,
            )
            for n in range(links)
        )

    for _round in range(3):
        together(
            lambda: run_once(world.sessions, mailer, config(), NOW),
            lambda: run_once(world.sessions, mailer, config(), NOW),
        )

    sent = Counter(address for address, _name, _message in mailer.sent)
    assert len(sent) == links
    assert set(sent.values()) == {1}


# A run, and the sweep (D6, D12).


def test_a_run_mails_a_link_and_logs_counts_only(world, mailer, caplog):
    add_link(world)

    with caplog.at_level(logging.INFO, logger="app.notifications.worker"):
        counts = run_once(world.sessions, mailer, config(), NOW)

    assert counts.links_sent == 1 and len(mailer.sent) == 1
    for record in caplog.records:
        assert ADDRESS not in record.getMessage()


def test_the_sweep_deletes_links_a_day_after_they_expire(world):
    gone = add_link(world, expires_at=NOW - SIGN_IN_RETENTION - timedelta(seconds=1))
    kept = add_link(world, expires_at=NOW - SIGN_IN_RETENTION)
    live = add_link(world)

    assert sweep_sign_in(world.sessions, NOW) == 1

    with Session(world.engine) as db:
        assert db.get(EmailLink, gone) is None
        assert db.get(EmailLink, kept) is not None
        assert db.get(EmailLink, live) is not None


def test_a_run_sweeps_old_links_and_old_throttle_rows(world, mailer):
    add_link(world, expires_at=NOW - 2 * DAY, status="sent", claimed_at=NOW - 2 * DAY)
    with Session(world.engine) as db, db.begin():
        db.add_all(
            [
                AuthThrottle(
                    key_hash="a" * 64,
                    window_started_at=NOW - SIGN_IN_RETENTION - MINUTE,
                    count=1,
                ),
                AuthThrottle(
                    key_hash="b" * 64,
                    window_started_at=NOW - timedelta(minutes=30),
                    count=1,
                ),
            ]
        )

    counts = run_once(world.sessions, mailer, config(), NOW)

    assert counts.sign_in_swept == 2
    with Session(world.engine) as db:
        assert db.scalars(select(EmailLink)).all() == []
        assert [row.key_hash for row in db.scalars(select(AuthThrottle))] == ["b" * 64]
