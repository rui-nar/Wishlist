"""The worker's run (comments plan D13, D16): the sweep waits for the events
that read a deleted gift's activity, finished rows go after 30 days, and the
thread lives and dies with the app.
"""

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session, sessionmaker
from worker_world import MINUTE, NOW, SECRET, World, config

from app.accounts.models import User
from app.comments.models import Comment, GiftFollow
from app.main import create_app
from app.notifications.digests import EmailConfig
from app.notifications.mailer import BrevoMailer
from app.notifications.models import NotificationEvent
from app.notifications.worker import NotificationWorker, run_once, sweep
from app.reserving.models import ClaimParticipant, GiftClaim
from app.settings import Settings

DAY = timedelta(days=1)
LATER = NOW + 2 * MINUTE


@pytest.fixture
def world(engine) -> World:
    return World(engine)


def run(world, mailer, now=NOW):
    return run_once(world.sessions, mailer, config(), now)


def activity(world, gift):
    """How many rows of each table the gift still has."""
    with Session(world.engine) as db:
        return tuple(
            len(db.scalars(select(model).where(model.gift_id == gift)).all())
            for model in (GiftClaim, ClaimParticipant, Comment, GiftFollow)
        )


@pytest.fixture
def giving(world):
    owner, ana = world.user("Olga"), world.user("Ana")
    list_id = world.listing(owner)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    return owner, ana, list_id, occasion


def full_activity(world, ana, occasion, gift):
    world.claim(gift, occasion, ana)
    world.comment(occasion, gift, ana)
    world.follow(occasion, gift, ana)


# A run, end to end.


def test_a_run_fans_out_then_sends_and_logs_counts_only(world, mailer, giving, caplog):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, occasion, ana)
    event = world.gift_changed(gift, owner)

    with caplog.at_level(logging.INFO, logger="app.notifications.worker"):
        counts = run(world, mailer)
        assert world.targets(event) == {ana}
        run(world, mailer, LATER)

    assert counts.events == 1 and counts.notifications == 1
    assert len(mailer.sent) == 1
    lines = [r.getMessage() for r in caplog.records]
    assert lines[0].startswith("notifications: events=1 notifications=1 ")
    for line in lines:
        assert "@example" not in line and "Scarf" not in line and "Ana" not in line


def test_a_run_with_nothing_to_do_logs_nothing(world, mailer, caplog):
    with caplog.at_level(logging.INFO, logger="app.notifications.worker"):
        run(world, mailer)
    assert caplog.records == []


# The sweep (D13).


def test_a_deleted_gifts_activity_goes_after_its_fan_out_not_before(
    world, mailer, giving
):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    full_activity(world, ana, occasion, gift)
    world.delete_gift(gift)
    event = world.gift_deleted(gift, owner, at=NOW + MINUTE)

    # Not yet due: the event is pending and names the gift.
    run(world, mailer, NOW)
    assert activity(world, gift) == (1, 1, 1, 1)
    assert world.event_row(event).status == "pending"

    # Fanned out, then swept in the same run: the event read them first.
    run(world, mailer, NOW + MINUTE)
    assert world.targets(event) == {ana}
    assert activity(world, gift) == (0, 0, 0, 0)


def test_a_failed_event_does_not_hold_the_sweep(world, mailer, giving):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    full_activity(world, ana, occasion, gift)
    world.delete_gift(gift)
    # A malformed payload: this event's fan-out raises each time.
    event = world.event("gift_deleted", {}, owner, gift=gift)

    now = NOW
    for wait in (1, 5, 30, 120, 0):
        run(world, mailer, now)
        if wait:
            assert activity(world, gift) == (1, 1, 1, 1)  # still pending
        now += wait * MINUTE

    assert world.event_row(event).status == "failed"
    assert activity(world, gift) == (0, 0, 0, 0)


def test_a_pending_gifts_removed_event_holds_its_gifts(world, mailer, giving):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    held = world.gift(list_id, "Hat")
    world.group_claim(gift, occasion, ana)
    world.group_claim(held, occasion, ana)
    world.delete_gift(gift)
    world.delete_gift(held)
    pending = world.gifts_removed(
        occasion, owner, (gift, "Scarf"), (held, "Hat"), at=NOW + MINUTE
    )

    run(world, mailer, NOW)
    assert activity(world, gift) == (1, 1, 0, 0)
    assert activity(world, held) == (1, 1, 0, 0)

    run(world, mailer, NOW + MINUTE)
    assert world.targets(pending) == {ana}
    assert activity(world, gift) == (0, 0, 0, 0)
    assert activity(world, held) == (0, 0, 0, 0)


def test_a_removal_of_a_hidden_group_gift_end_to_end(world, mailer, giving):
    # Its claim rows are read by the fan-out, and go only after.
    owner, ana, list_id, occasion = giving
    lea = world.user("Lea")
    hidden = world.hidden_gift(list_id, occasion, lea, "Bike")
    world.group_claim(hidden, occasion, ana)
    world.delete_gift(hidden)
    world.gifts_removed(occasion, owner, (hidden, "Bike"), at=NOW + MINUTE)

    run(world, mailer, NOW + MINUTE)
    run(world, mailer, NOW + 3 * MINUTE)

    assert activity(world, hidden) == (0, 0, 0, 0)
    assert [message.subject for _a, _n, message in mailer.sent] == [
        "The hidden gift “Bike” was removed (Summer party)"
    ]


def test_the_sweep_leaves_a_gift_that_still_exists(world, mailer, giving):
    _owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    full_activity(world, ana, occasion, gift)

    run(world, mailer)

    assert activity(world, gift) == (1, 1, 1, 1)


def test_the_sweep_removes_an_unbought_claim_with_no_occasion(world, mailer, giving):
    _owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, None, ana)
    bought = world.gift(list_id, "Hat")
    world.claim(bought, None, ana, bought=True)

    run(world, mailer)

    assert activity(world, gift) == (0, 0, 0, 0)
    assert activity(world, bought) == (1, 1, 0, 0)


def test_r6_1_the_sweep_skips_a_locked_claim_and_does_not_wait(world, giving):
    # A giver's release holds a claim of a deleted gift (`release_activity`,
    # D7): the sweep leaves it, takes the other, and comes back for it later.
    _owner, ana, list_id, occasion = giving
    held = world.gift(list_id, "Scarf")
    free = world.gift(list_id, "Hat")
    world.claim(held, occasion, ana)
    world.claim(free, occasion, ana)
    world.delete_gift(held)
    world.delete_gift(free)

    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(world.engine) as holder, holder.begin():
            holder.execute(
                select(GiftClaim.gift_id)
                .where(GiftClaim.gift_id == held)
                .with_for_update()
            ).all()

            # Inside the lock: a sweep that waited would time out here.
            swept = pool.submit(sweep, world.sessions).result(timeout=10)

            assert swept == 1

    assert activity(world, held) == (1, 1, 0, 0)
    assert activity(world, free) == (0, 0, 0, 0)

    assert sweep(world.sessions) == 1
    assert activity(world, held) == (0, 0, 0, 0)


# Retention (D16).


def test_finished_rows_go_after_30_days(world, mailer, giving):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, occasion, ana)
    event = world.gift_changed(gift, owner)
    run(world, mailer, NOW)
    run(world, mailer, LATER)
    assert len(mailer.sent) == 1

    # Its event finished at NOW, its digest at LATER; each waits its own 30 days.
    run(world, mailer, NOW + 30 * DAY)
    assert world.event_row(event) is not None
    assert world.digests() != []

    run(world, mailer, NOW + 30 * DAY + timedelta(seconds=1))
    assert world.digests() != [] and world.notifications(event) == []
    with Session(world.engine) as db:
        assert db.get(NotificationEvent, event) is None

    run(world, mailer, LATER + 30 * DAY + timedelta(seconds=1))
    assert world.digests() == []
    assert world.notifications(event) == []
    with Session(world.engine) as db:
        assert db.get(NotificationEvent, event) is None


def test_an_event_waits_for_a_digest_still_to_be_sent(world, mailer, giving):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, occasion, ana)
    event = world.gift_changed(gift, owner)
    run(world, mailer, NOW)
    with Session(world.engine) as db, db.begin():
        # The event ended 31 days ago; its digest has still to be sent.
        db.execute(
            text("UPDATE notification_events SET processed_at = :at WHERE id = :id"),
            {"at": NOW - 31 * DAY, "id": event},
        )

    # Inside the settle minute: the digest stays pending through the run.
    run(world, mailer, NOW + timedelta(seconds=30))

    assert world.digests()[0].status == "pending"
    assert world.notifications(event) != []


def test_account_deletion_removes_their_notifications_and_digests(
    world, mailer, giving
):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, occasion, ana)
    event = world.gift_changed(gift, owner)
    run(world, mailer, NOW)
    assert world.targets(event) == {ana} and len(world.digests(ana)) == 1

    with Session(world.engine) as db, db.begin():
        db.execute(delete(User).where(User.id == ana))

    assert world.notifications(event) == []
    assert world.digests(ana) == []


# Settings (D19).


def settings(**values):
    base = {
        "database_url": "postgresql+psycopg://x:y@localhost/z",
        "brevo_api_key": "key",
        "email_sender_address": "sender@example.test",
        "notification_secret": SECRET,
        "public_base_url": "https://shushgift.example.test",
    }
    return Settings(**(base | values))


def test_email_is_configured_only_with_all_four_variables():
    assert settings().missing_email_settings == []
    assert settings(brevo_api_key="").missing_email_settings == ["BREVO_API_KEY"]
    missing = settings(
        brevo_api_key=" ",
        email_sender_address="",
        notification_secret="",
        public_base_url="/",
    ).missing_email_settings
    assert missing == [
        "BREVO_API_KEY",
        "EMAIL_SENDER_ADDRESS",
        "NOTIFICATION_SECRET",
        "PUBLIC_BASE_URL",
    ]


def test_settings_defaults_and_the_runbook_rules(monkeypatch):
    # The conftest turns the worker off for every app it does not build.
    monkeypatch.delenv("NOTIFICATIONS_WORKER", raising=False)
    assert settings().notifications_worker is True
    assert settings().email_sender_name == "Shush Gift"

    monkeypatch.setenv("EMAIL_SENDER_NAME", "")
    assert settings().email_sender_name == ""

    monkeypatch.setenv("NOTIFICATIONS_WORKER", "false")
    assert settings().notifications_worker is False
    monkeypatch.setenv("NOTIFICATIONS_WORKER", "")
    with pytest.raises(ValidationError):
        settings()


def test_the_allow_list_is_read_whatever_its_spacing_and_case():
    allowed = settings(email_allowed_recipients=" Ana@Example.test , b@example.test,")
    assert allowed.email_allowed_addresses == {"ana@example.test", "b@example.test"}


def test_the_allow_list_applies_except_in_production():
    production = settings(app_env="production", email_allowed_recipients="a@b.test")
    assert EmailConfig.from_settings(production).allowed_addresses is None

    validation = settings(app_env="validation", email_allowed_recipients="a@b.test")
    assert EmailConfig.from_settings(validation).allowed_addresses == {"a@b.test"}
    assert EmailConfig.from_settings(settings()).allowed_addresses == frozenset()


# The thread.


def test_the_mailer_is_built_only_when_configured():
    url = "postgresql+psycopg://a/b"

    configured = create_app(settings(database_url=url))
    assert isinstance(configured.state.mailer, BrevoMailer)
    configured.state.engine.dispose()

    unconfigured = create_app(settings(database_url=url, brevo_api_key=""))
    assert unconfigured.state.mailer is None
    unconfigured.state.engine.dispose()


def test_the_worker_starts_and_stops_with_the_app_when_enabled(make_client):
    client = make_client(notifications_worker=True)
    worker = client.app.state.notification_worker
    assert worker.is_alive()

    client.__exit__(None, None, None)

    assert not worker.is_alive()


def test_the_worker_does_not_start_when_disabled(make_client):
    client = make_client()
    assert client.app.state.notification_worker is None


def test_a_start_with_settings_missing_logs_their_names(database_url, caplog):
    missing = Settings(
        database_url=database_url,
        media_dir="unused",
        notifications_worker=True,
        notification_secret=SECRET,
    )
    with caplog.at_level(logging.WARNING, logger="app.notifications.worker"):
        with TestClient(create_app(missing)):
            pass

    lines = [r.getMessage() for r in caplog.records]
    assert len(lines) == 1
    # The names the runbook greps for, literally.
    for name in ("BREVO_API_KEY", "EMAIL_SENDER_ADDRESS", "PUBLIC_BASE_URL"):
        assert name in lines[0]
    assert "NOTIFICATION_SECRET" not in lines[0]


def test_a_fully_configured_start_names_no_variable(database_url, caplog, mailer):
    configured = Settings(
        database_url=database_url,
        media_dir="unused",
        notifications_worker=True,
        brevo_api_key="key",
        email_sender_address="sender@example.test",
        notification_secret=SECRET,
        public_base_url="https://shushgift.example.test",
    )
    app = create_app(configured)
    app.state.mailer = mailer
    with caplog.at_level(logging.INFO):
        with TestClient(app):
            pass

    for record in caplog.records:
        for name in (
            "BREVO_API_KEY",
            "EMAIL_SENDER_ADDRESS",
            "NOTIFICATION_SECRET",
            "PUBLIC_BASE_URL",
        ):
            assert name not in record.getMessage()


def test_the_thread_runs_the_worker_with_the_clock(world, mailer, giving):
    owner, ana, list_id, occasion = giving
    gift = world.gift(list_id, "Scarf")
    world.claim(gift, occasion, ana)
    event = world.gift_changed(gift, owner)

    worker = NotificationWorker(
        sessionmaker(bind=world.engine),
        lambda: mailer,
        config(),
        lambda: LATER,
        interval=timedelta(seconds=0.02),
    )
    worker.start()
    deadline = time.monotonic() + 10
    while not world.targets(event) and time.monotonic() < deadline:
        time.sleep(0.02)
    worker.stop()

    assert world.targets(event) == {ana}
    assert not worker.is_alive()


def test_a_run_that_raises_is_logged_by_type_and_the_thread_goes_on(
    world, mailer, caplog, monkeypatch
):
    def explode(*_args, **_kwargs):
        raise RuntimeError("a row with someone@example.test")

    monkeypatch.setattr("app.notifications.worker.run_once", explode)
    worker = NotificationWorker(
        world.sessions, lambda: mailer, config(), lambda: NOW, interval=timedelta(0)
    )
    with caplog.at_level(logging.ERROR, logger="app.notifications.worker"):
        worker.start()
        deadline = time.monotonic() + 10
        while not caplog.records and time.monotonic() < deadline:
            time.sleep(0.01)
    assert worker.is_alive()
    worker.stop()

    message = caplog.records[0].getMessage()
    assert message == "notifications: run failed (RuntimeError)"
