"""The emails (comments plan D15, D19): at most one per person and gift every
15 minutes, checked again at send time, sent at most once.
"""

import uuid
from dataclasses import dataclass, replace
from datetime import timedelta

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session
from worker_world import BASE_URL, MINUTE, NOW, SECRET, World, config

from app.accounts.models import User
from app.comments.models import Comment
from app.lists.models import OccasionMember
from app.notifications import digests
from app.notifications.digests import send_due
from app.notifications.fanout import fan_out_due
from app.notifications.mailer import Outcome
from app.notifications.unsubscribe import make_token

SETTLED = NOW + 2 * MINUTE


@pytest.fixture
def world(engine) -> World:
    return World(engine)


def fan_out(world, now=NOW):
    return fan_out_due(world.sessions, now)


def send(world, mailer, now=SETTLED, cfg=None):
    return send_due(world.sessions, mailer, cfg or config(), now)


@dataclass
class Giving:
    owner: uuid.UUID
    ana: uuid.UUID
    ben: uuid.UUID
    list_id: uuid.UUID
    occasion: uuid.UUID
    gift: uuid.UUID


@pytest.fixture
def giving(world) -> Giving:
    owner = world.user("Olga")
    ana = world.user("Ana", email="ana@example.test")
    ben = world.user("Ben", language="fr", email="ben@example.test")
    list_id = world.listing(owner)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    world.member(occasion, ben)
    gift = world.gift(list_id, "Scarf")
    return Giving(owner, ana, ben, list_id, occasion, gift)


def reserved(world, giving, user=None):
    """Ana (or `user`) reserved the gift; returns the owner's edit's event."""
    world.claim(giving.gift, giving.occasion, user or giving.ana)
    return world.gift_changed(giving.gift, giving.owner)


def sent_subjects(mailer):
    return [message.subject for _address, _name, message in mailer.sent]


# Grouping.


def test_a_first_email_waits_for_the_settle_minute(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)

    assert send(world, mailer, NOW + 59 * timedelta(seconds=1)).sent == 0
    assert mailer.sent == []

    assert send(world, mailer, NOW + MINUTE).sent == 1
    address, name, message = mailer.sent[0]
    assert (address, name) == ("ana@example.test", "Ana")
    assert "Scarf" in message.subject
    assert world.digests()[0].status == "sent"
    assert world.digests()[0].sent_at == NOW + MINUTE
    assert world.digests()[0].claimed_at == NOW + MINUTE


def test_a_quick_correction_joins_the_pending_digest_and_is_listed(
    world, giving, mailer
):
    reserved(world, giving)
    fan_out(world)
    world.gift_changed(giving.gift, giving.owner, ("price_amount", "price_currency"))
    fan_out(world, NOW + 30 * timedelta(seconds=1))

    assert len(world.digests()) == 1
    assert world.digests()[0].send_after == NOW + MINUTE

    send(world, mailer, NOW + MINUTE)
    assert len(mailer.sent) == 1
    text_part = mailer.sent[0][2].text
    assert "title" in text_part and "price" in text_part


def test_later_notifications_wait_for_15_minutes_after_the_last_claim(
    world, giving, mailer
):
    reserved(world, giving)
    fan_out(world)
    send(world, mailer, NOW + MINUTE)  # claimed at NOW + 1

    world.gift_changed(giving.gift, giving.owner, at=NOW + 2 * MINUTE)
    fan_out(world, NOW + 2 * MINUTE)
    world.gift_changed(giving.gift, giving.owner, ("description",), at=NOW + 3 * MINUTE)
    fan_out(world, NOW + 3 * MINUTE)

    digest = world.digests(giving.ana)[-1]
    assert digest.status == "pending"
    assert digest.send_after == NOW + 16 * MINUTE

    assert send(world, mailer, NOW + 15 * MINUTE).sent == 0
    assert send(world, mailer, NOW + 16 * MINUTE).sent == 1
    assert len(mailer.sent) == 2
    second = mailer.sent[1][2].text
    assert "title" in second and "description" in second


def test_separate_gifts_and_occasions_get_separate_emails(world, giving, mailer):
    other_gift = world.gift(giving.list_id, "Hat")
    other_occasion = world.occasion(giving.list_id, name="Picnic")
    world.member(other_occasion, giving.ana)
    third = world.gift(giving.list_id, "Bike")
    world.claim(giving.gift, giving.occasion, giving.ana)
    world.claim(other_gift, giving.occasion, giving.ana)
    world.claim(third, other_occasion, giving.ana)
    for gift in (giving.gift, other_gift, third):
        world.gift_changed(gift, giving.owner)
    fan_out(world)

    send(world, mailer)

    assert len(mailer.sent) == 3
    assert {s for s in sent_subjects(mailer)} == {
        "News about “Scarf” (Summer party)",
        "News about “Hat” (Summer party)",
        "News about “Bike” (Picnic)",
    }


def test_the_email_lists_all_of_it_oldest_first(world, giving, mailer):
    world.group_claim(giving.gift, giving.occasion, giving.ana)
    world.follow(giving.occasion, giving.gift, giving.ana)
    author = world.user("Carl")
    world.member(giving.occasion, author)
    first = world.comment(giving.occasion, giving.gift, author, "First comment")
    second = world.comment(giving.occasion, giving.gift, giving.ben, "Second comment")
    leaver = world.user("Lea")

    world.gift_changed(giving.gift, giving.owner)
    world.comment_added(giving.occasion, giving.gift, author, first)
    world.comment_added(giving.occasion, giving.gift, giving.ben, second)
    world.participants_left(leaver, (giving.gift, giving.occasion))
    fan_out(world)
    send(world, mailer)

    assert len(mailer.sent) == 1
    body = mailer.sent[0][2].text
    assert "title" in body
    assert body.index("First comment") < body.index("Second comment")
    assert "Carl:" in body and "Ben:" in body
    assert "Lea left this group gift." in body


def test_an_edited_comment_shows_its_current_text_and_a_deleted_one_is_left_out(
    world, giving, mailer
):
    world.follow(giving.occasion, giving.gift, giving.ana)
    edited = world.comment(giving.occasion, giving.gift, giving.ben, "Before")
    gone = world.comment(giving.occasion, giving.gift, giving.ben, "Deleted one")
    world.comment_added(giving.occasion, giving.gift, giving.ben, edited)
    world.comment_added(giving.occasion, giving.gift, giving.ben, gone)
    fan_out(world)

    with Session(world.engine) as db, db.begin():
        db.get_one(Comment, edited).body = "After"
        db.delete(db.get_one(Comment, gone))
    send(world, mailer)

    body = mailer.sent[0][2].text
    assert "After" in body
    assert "Before" not in body and "Deleted one" not in body


def test_a_deleted_gift_says_only_that(world, giving, mailer):
    world.claim(giving.gift, giving.occasion, giving.ana)
    world.follow(giving.occasion, giving.gift, giving.ana)
    comment = world.comment(giving.occasion, giving.gift, giving.ben, "Secret plan")
    world.gift_changed(giving.gift, giving.owner)
    world.comment_added(giving.occasion, giving.gift, giving.ben, comment)
    world.delete_gift(giving.gift)
    world.gift_deleted(giving.gift, giving.owner, "Scarf")
    fan_out(world)
    send(world, mailer)

    assert len(mailer.sent) == 1
    message = mailer.sent[0][2]
    assert message.subject == "The gift “Scarf” was deleted (Summer party)"
    assert "Secret plan" not in message.text
    assert "Secret plan" not in message.html


def test_a_removed_hidden_gift_says_only_that_by_its_captured_title(
    world, giving, mailer
):
    hidden = world.hidden_gift(giving.list_id, giving.occasion, giving.ben, "Bike")
    world.group_claim(hidden, giving.occasion, giving.ana)
    world.delete_gift(hidden)
    world.gifts_removed(giving.occasion, giving.owner, (hidden, "Bike"))
    fan_out(world)
    send(world, mailer)

    assert mailer.sent[0][2].subject == (
        "The hidden gift “Bike” was removed (Summer party)"
    )


def test_a_digest_whose_items_all_vanished_is_skipped(world, giving, mailer):
    world.follow(giving.occasion, giving.gift, giving.ana)
    comment = world.comment(giving.occasion, giving.gift, giving.ben)
    world.comment_added(giving.occasion, giving.gift, giving.ben, comment)
    fan_out(world)
    with Session(world.engine) as db, db.begin():
        db.delete(db.get_one(Comment, comment))

    counts = send(world, mailer)

    digest = world.digests()[0]
    assert counts.skipped == 1 and mailer.sent == []
    assert (digest.status, digest.skip_reason) == ("skipped", "empty")


def test_a_deleted_account_of_a_leaver_or_author_names_nobody(world, giving, mailer):
    world.group_claim(giving.gift, giving.occasion, giving.ana)
    world.follow(giving.occasion, giving.gift, giving.ana)
    leaver = world.user("Lea-the-gone")
    author = world.user("Carl-the-gone")
    world.member(giving.occasion, author)
    comment = world.comment(giving.occasion, giving.gift, author, "Hello")
    world.participants_left(leaver, (giving.gift, giving.occasion))
    world.comment_added(giving.occasion, giving.gift, author, comment)
    fan_out(world)

    with Session(world.engine) as db, db.begin():
        db.execute(delete(User).where(User.id.in_([leaver, author])))
    send(world, mailer)

    body = mailer.sent[0][2].text
    assert "the-gone" not in body
    assert "A participant left this group gift." in body
    assert "Deleted user:" in body


# Send-time checks.


def test_opted_out_is_skipped_at_send_time(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)
    with Session(world.engine) as db, db.begin():
        db.get_one(User, giving.ana).email_notifications = False

    send(world, mailer)

    digest = world.digests()[0]
    assert mailer.sent == []
    assert (digest.status, digest.skip_reason) == ("skipped", "opted_out")


def test_no_longer_a_giver_is_skipped_at_send_time(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)
    with Session(world.engine) as db, db.begin():
        db.execute(delete(OccasionMember).where(OccasionMember.user_id == giving.ana))

    send(world, mailer)

    assert mailer.sent == []
    assert world.digests()[0].skip_reason == "not_giver"


@pytest.mark.parametrize("why", ["mailer", "missing"])
def test_email_not_configured_is_skipped(world, giving, mailer, why):
    reserved(world, giving)
    fan_out(world)
    cfg = config()
    if why == "missing":
        cfg = replace(cfg, missing=("BREVO_API_KEY",))

    counts = send_due(world.sessions, None if why == "mailer" else mailer, cfg, SETTLED)

    digest = world.digests()[0]
    assert counts.skipped == 1 and mailer.sent == []
    assert (digest.status, digest.skip_reason) == ("skipped", "not_configured")


def test_the_allow_list_applies_outside_production(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)

    send(world, mailer, cfg=config(production=False, allowed=frozenset()))

    assert mailer.sent == []
    assert world.digests()[0].skip_reason == "not_allowed"


def test_an_address_on_the_allow_list_is_sent_whatever_its_case(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)

    send(
        world,
        mailer,
        cfg=config(production=False, allowed=frozenset({"ana@example.test"})),
    )

    assert len(mailer.sent) == 1

    with Session(world.engine) as db, db.begin():
        db.get_one(User, giving.ben).email = "BEN@Example.Test"
    other = replace(giving, gift=world.gift(giving.list_id, "Hat"))
    reserved(world, other, giving.ben)
    fan_out(world, NOW + MINUTE)
    send(
        world,
        mailer,
        NOW + 3 * MINUTE,
        config(production=False, allowed=frozenset({"ben@example.test"})),
    )

    assert len(mailer.sent) == 2


def test_the_allow_list_is_ignored_in_production(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)

    send(world, mailer, cfg=config(production=True))

    assert len(mailer.sent) == 1


# Language and links.


def test_an_email_in_the_recipients_language(world, giving, mailer):
    reserved(world, giving, giving.ben)
    fan_out(world)

    send(world, mailer)

    subject = mailer.sent[0][2].subject
    assert subject.startswith("Du nouveau sur") and "Scarf" in subject


def test_links_and_headers_are_on_the_public_base_url(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)

    send(world, mailer)

    message = mailer.sent[0][2]
    token = make_token(SECRET, giving.ana)
    assert message.headers == {
        "List-Unsubscribe": f"<{BASE_URL}/api/unsubscribe/{token}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    assert f"{BASE_URL}/unsubscribe#{token}" in message.text
    assert (f"{BASE_URL}/shared/{giving.occasion}?gift={giving.gift}") in message.text


# Outcomes.


def test_retry_backs_off_then_fails_after_the_sixth_attempt(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)
    mailer.outcome = Outcome.RETRY

    now = NOW + MINUTE
    for attempt, wait in enumerate((1, 5, 30, 120, 720), start=1):
        assert send(world, mailer, now).retried == 1
        digest = world.digests()[0]
        assert (digest.status, digest.attempts) == ("pending", attempt)
        assert digest.next_attempt_at == now + wait * MINUTE
        assert (
            send(world, mailer, now + (wait * 60 - 1) * timedelta(seconds=1)).sent == 0
        )
        now += wait * MINUTE

    counts = send(world, mailer, now)
    digest = world.digests()[0]
    assert counts.failed == 1
    assert (digest.status, digest.skip_reason, digest.attempts) == (
        "failed",
        "retries",
        6,
    )
    assert len(mailer.sent) == 6


def test_a_retry_takes_the_notifications_of_a_new_pending_digest(world, giving, mailer):
    # A digest is sending when a newer one starts; Brevo then refuses the first.
    reserved(world, giving)
    fan_out(world)
    first = world.digests()[0]
    world.set_digest(first.id, status="sending", claimed_at=NOW + MINUTE, attempts=1)
    world.gift_changed(giving.gift, giving.owner, ("description",), at=NOW + 2 * MINUTE)
    fan_out(world, NOW + 2 * MINUTE)
    assert len(world.digests()) == 2

    with Session(world.engine) as db, db.begin():
        status = digests._record(db, first.id, Outcome.RETRY, NOW + 2 * MINUTE)

    assert status == "pending"
    rows = world.digests()
    assert [row.id for row in rows] == [first.id]
    assert rows[0].status == "pending"
    with Session(world.engine) as db:
        assert (
            db.scalar(
                text("SELECT count(*) FROM notifications WHERE email_digest_id = :d"),
                {"d": first.id},
            )
            == 2
        )

    # Its next attempt sends both.
    mailer.outcome = Outcome.SENT
    send(world, mailer, NOW + 4 * MINUTE)
    body = mailer.sent[0][2].text
    assert "title" in body and "description" in body


@pytest.mark.parametrize(
    "outcome,reason",
    [(Outcome.UNKNOWN, "unknown"), (Outcome.REJECTED, "rejected")],
)
def test_unknown_and_rejected_fail_and_are_never_sent_again(
    world, giving, mailer, outcome, reason
):
    reserved(world, giving)
    fan_out(world)
    mailer.outcome = outcome

    counts = send(world, mailer)

    digest = world.digests()[0]
    assert counts.failed == 1
    assert (digest.status, digest.skip_reason) == ("failed", reason)
    send(world, mailer, SETTLED + 1000 * MINUTE)
    assert len(mailer.sent) == 1


def test_a_send_that_raises_is_unknown_and_never_sent_again(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)
    mailer.outcome = RuntimeError("boom")

    send(world, mailer)

    assert world.digests()[0].skip_reason == "unknown"
    assert len(mailer.sent) == 1


def test_a_stale_sending_row_fails_and_is_never_resent(world, giving, mailer):
    reserved(world, giving)
    fan_out(world)
    digest = world.digests()[0]
    claimed = NOW + MINUTE
    world.set_digest(digest.id, status="sending", claimed_at=claimed)

    send(world, mailer, claimed + 10 * MINUTE)
    assert world.digests()[0].status == "sending"  # not older than 10 minutes

    counts = send(world, mailer, claimed + 10 * MINUTE + timedelta(seconds=1))
    digest = world.digests()[0]
    assert counts.failed == 1
    assert (digest.status, digest.skip_reason) == ("failed", "unknown")
    assert mailer.sent == []


def test_a_notification_arriving_during_the_send_waits_for_the_next_email(
    world, giving, mailer
):
    reserved(world, giving)
    fan_out(world)
    digest = world.digests()[0]
    world.set_digest(digest.id, status="sending", claimed_at=NOW + MINUTE, attempts=1)

    world.gift_changed(giving.gift, giving.owner, ("description",), at=NOW + 2 * MINUTE)
    fan_out(world, NOW + 2 * MINUTE)

    pending = [row for row in world.digests() if row.status == "pending"]
    assert len(pending) == 1
    assert pending[0].send_after == NOW + 16 * MINUTE
