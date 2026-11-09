"""Who is told of what (comments plan D11): the events of each kind become
notifications for the people who still give, and for nobody else. The surprise
rule first: no row ever names a non-giver.
"""

import logging
import uuid
from dataclasses import dataclass

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from worker_world import MINUTE, NOW, PASSED, World

from app.accounts.models import User
from app.lists.access import giver_condition, giving_occasion
from app.lists.models import OTHER, ListOwner, OccasionMember
from app.notifications.fanout import fan_out_due
from app.notifications.models import NotificationEvent
from app.reserving.models import ClaimParticipant, GiftClaim


@pytest.fixture
def world(engine) -> World:
    return World(engine)


def fan_out(world, now=NOW):
    return fan_out_due(world.sessions, now)


@dataclass
class Giving:
    """A "for me" list, its recipient, and an occasion with two invitees who
    each hold a gift."""

    owner: uuid.UUID
    ana: uuid.UUID
    ben: uuid.UUID
    list_id: uuid.UUID
    occasion: uuid.UUID
    gift: uuid.UUID


@pytest.fixture
def giving(world) -> Giving:
    owner, ana, ben = world.user("Olga"), world.user("Ana"), world.user("Ben")
    list_id = world.listing(owner)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    world.member(occasion, ben)
    gift = world.gift(list_id)
    return Giving(owner, ana, ben, list_id, occasion, gift)


# giver_condition against giving_occasion, role by role.


def test_giver_condition_equals_giving_occasion_for_every_role(world):
    me_owner, other_owner = world.user("Olga"), world.user("Otto")
    invitee, elsewhere, removed = world.user(), world.user(), world.user()
    stranger, co_owner_member = world.user(), world.user()
    for_me = world.listing(me_owner)
    for_someone = world.listing(other_owner, OTHER)
    world.member(world.occasion(for_me), elsewhere)  # another occasion of the list
    world.member(world.occasion(for_someone), elsewhere)
    occasions = [world.occasion(for_me), world.occasion(for_someone)]
    actors = [me_owner, other_owner, invitee, elsewhere, removed, stranger]
    actors.append(co_owner_member)
    for occasion in occasions:
        world.member(occasion, invitee)
        world.member(occasion, removed)
        world.member(occasion, co_owner_member)
    world._add(ListOwner(list_id=for_me, user_id=co_owner_member))
    with Session(world.engine) as db, db.begin():
        db.execute(
            OccasionMember.__table__.delete().where(OccasionMember.user_id == removed)
        )

    givers_seen = 0
    for occasion in occasions:
        for actor in actors:
            with Session(world.engine) as db:
                user = db.get_one(User, actor)
                try:
                    giving_occasion(db, user, occasion, lock=False)
                    expected = True
                except HTTPException:
                    expected = False
                assert db.scalar(select(giver_condition(actor, occasion))) == expected
                givers_seen += expected
    # The invitee on both lists, the co-owner on the other list only, and the
    # owner of the list for someone else: never all of them refused.
    assert givers_seen == 4


# gift_changed and gift_deleted.


def test_gift_changed_tells_the_participants_bought_included(world, giving):
    buyer_gift = world.gift(giving.list_id)
    world.claim(giving.gift, giving.occasion, giving.ana)
    world.claim(buyer_gift, giving.occasion, giving.ben, bought=True)

    first = world.gift_changed(giving.gift, giving.owner)
    second = world.gift_changed(buyer_gift, giving.owner)
    fan_out(world)

    assert world.targets(first) == {giving.ana}
    assert world.targets(second) == {giving.ben}
    assert world.event_row(first).status == "done"
    assert world.event_row(first).processed_at == NOW


def test_a_group_gift_tells_every_participant(world, giving):
    world.group_claim(giving.gift, giving.occasion, giving.ana, giving.ben)

    event = world.gift_changed(giving.gift, giving.owner)
    fan_out(world)

    assert world.targets(event) == {giving.ana, giving.ben}


@pytest.mark.parametrize("kind", ["changed", "deleted"])
def test_nobody_for_a_gift_without_a_claim(world, giving, kind):
    if kind == "changed":
        event = world.gift_changed(giving.gift, giving.owner)
    else:
        event = world.gift_deleted(giving.gift, giving.owner)

    fan_out(world)

    assert world.targets(event) == set()
    assert world.event_row(event).status == "done"
    assert world.event_row(event).reason is None


def test_nobody_for_a_received_gift(world, giving):
    gift = world.gift(giving.list_id, received=True)
    world.claim(gift, giving.occasion, giving.ana, bought=True)

    event = world.gift_changed(gift, giving.owner)
    fan_out(world)

    assert world.targets(event) == set()


def test_nobody_for_a_gift_deleted_while_received(world, giving):
    world.claim(giving.gift, giving.occasion, giving.ana, bought=True)
    world.delete_gift(giving.gift)

    event = world.gift_deleted(giving.gift, giving.owner, received=True)
    fan_out(world)

    assert world.targets(event) == set()


@pytest.mark.parametrize("kind", ["changed", "deleted"])
def test_nobody_for_a_claim_expired_before_the_event(world, giving, kind):
    passed = world.occasion(giving.list_id, on=PASSED)
    world.member(passed, giving.ana)
    world.claim(giving.gift, passed, giving.ana)
    if kind == "changed":
        event = world.gift_changed(giving.gift, giving.owner)
    else:
        world.delete_gift(giving.gift)
        event = world.gift_deleted(giving.gift, giving.owner)

    fan_out(world)

    assert world.targets(event) == set()


@pytest.mark.parametrize("kind", ["changed", "deleted"])
def test_a_claim_expiring_between_the_event_and_the_fan_out_is_still_told(
    world, giving, kind
):
    # Live at the event, passed by the fan-out, forty days later.
    world.claim(giving.gift, giving.occasion, giving.ana)
    if kind == "changed":
        event = world.gift_changed(giving.gift, giving.owner)
    else:
        world.delete_gift(giving.gift)
        event = world.gift_deleted(giving.gift, giving.owner)

    fan_out(world, NOW + (40 * 24 * 60) * MINUTE)

    assert world.targets(event) == {giving.ana}


def test_the_actor_is_never_a_target_even_as_a_giver(world):
    owner, ana = world.user("Olga"), world.user("Ana")
    list_id = world.listing(owner, OTHER)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    gift = world.gift(list_id)
    world.group_claim(gift, occasion, owner, ana)

    event = world.gift_changed(gift, owner)
    fan_out(world)

    assert world.targets(event) == {ana}


def test_the_owner_of_a_list_for_someone_else_who_gives_is_told(world):
    owner, ana = world.user("Olga"), world.user("Ana")
    list_id = world.listing(owner, OTHER)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    gift = world.gift(list_id)
    world.group_claim(gift, occasion, owner, ana)

    event = world.gift_changed(gift, ana)
    fan_out(world)

    assert world.targets(event) == {owner}


def test_a_claim_with_no_occasion_tells_nobody(world, giving):
    world.claim(giving.gift, None, giving.ana, bought=True)

    event = world.gift_changed(giving.gift, giving.owner)
    fan_out(world)

    row = world.event_row(event)
    assert world.targets(event) == set()
    assert (row.status, row.reason) == ("done", "no_occasion")


# comment_added.


def test_a_comment_tells_the_followers_but_its_author(world, giving):
    carl = world.user("Carl")
    world.member(giving.occasion, carl)
    world.follow(giving.occasion, giving.gift, giving.ana)
    world.follow(giving.occasion, giving.gift, giving.ben)
    world.follow(giving.occasion, giving.gift, carl, following=False)
    comment = world.comment(giving.occasion, giving.gift, giving.ana)

    event = world.comment_added(giving.occasion, giving.gift, giving.ana, comment)
    fan_out(world)

    assert world.targets(event) == {giving.ben}


def test_a_comment_deleted_before_the_fan_out_tells_nobody(world, giving):
    world.follow(giving.occasion, giving.gift, giving.ben)

    event = world.comment_added(giving.occasion, giving.gift, giving.ana, uuid.uuid4())
    fan_out(world)

    assert world.targets(event) == set()


@pytest.mark.parametrize("gone", ["received", "deleted"])
def test_a_comment_on_a_gift_no_giver_can_see_tells_nobody(world, giving, gone):
    gift = world.gift(giving.list_id, received=gone == "received")
    world.follow(giving.occasion, gift, giving.ben)
    comment = world.comment(giving.occasion, gift, giving.ana)
    if gone == "deleted":
        world.delete_gift(gift)

    event = world.comment_added(giving.occasion, gift, giving.ana, comment)
    fan_out(world)

    assert world.targets(event) == set()


# participants_left and gifts_removed.


def test_a_leaver_tells_the_other_participants(world, giving):
    leaver = world.user("Lea")
    world.group_claim(giving.gift, giving.occasion, giving.ana, giving.ben)

    event = world.participants_left(leaver, (giving.gift, giving.occasion))
    fan_out(world)

    assert world.targets(event) == {giving.ana, giving.ben}


def test_a_leaver_listed_by_two_gifts_is_told_of_both(world, giving):
    other = world.gift(giving.list_id)
    world.group_claim(giving.gift, giving.occasion, giving.ana)
    world.group_claim(other, giving.occasion, giving.ana)
    leaver = world.user("Lea")

    event = world.participants_left(
        leaver, (giving.gift, giving.occasion), (other, giving.occasion)
    )
    fan_out(world)

    assert {row.gift_id for row in world.notifications(event)} == {giving.gift, other}


def test_a_missing_listed_gift_is_skipped_and_the_others_are_told(world, giving):
    leaver = world.user("Lea")
    world.group_claim(giving.gift, giving.occasion, giving.ana)
    gone_gift = world.gift(giving.list_id)
    gone_occasion = uuid.uuid4()

    event = world.participants_left(
        leaver,
        (uuid.uuid4(), giving.occasion),  # never existed
        (gone_gift, gone_occasion),  # its occasion is gone
        (giving.gift, giving.occasion),
    )
    fan_out(world)

    assert world.targets(event) == {giving.ana}
    assert world.event_row(event).status == "done"


def test_a_removal_of_a_hidden_gift_author(world, giving):
    # Removing Lea took her from Ben's group gift and deleted her hidden group
    # gift, which Ana pledged on: the same removal writes both events.
    lea = world.user("Lea")
    hidden = world.hidden_gift(giving.list_id, giving.occasion, lea, "Bike")
    world.group_claim(hidden, giving.occasion, giving.ana)
    world.group_claim(giving.gift, giving.occasion, giving.ben)
    world.delete_gift(hidden)

    left = world.participants_left(
        lea, (hidden, giving.occasion), (giving.gift, giving.occasion)
    )
    removed = world.gifts_removed(giving.occasion, giving.owner, (hidden, "Bike"))
    fan_out(world)

    assert world.targets(left) == {giving.ben}
    assert [r.gift_id for r in world.notifications(left)] == [giving.gift]
    notified = world.notifications(removed)
    assert [(r.user_id, r.gift_id) for r in notified] == [(giving.ana, hidden)]
    # The claim row is the sweep's, after this event is done (test_worker.py).
    with Session(world.engine) as db:
        assert db.get(GiftClaim, hidden) is not None


def test_a_removed_gift_with_no_claim_rows_tells_nobody(world, giving):
    event = world.gifts_removed(giving.occasion, giving.owner, (uuid.uuid4(), "Bike"))

    fan_out(world)

    assert world.targets(event) == set()
    assert world.event_row(event).status == "done"


# Nobody but a giver.


def test_no_notification_for_a_non_giver(world, giving):
    # All of them hold the claim, or follow the gift; none gives any more.
    removed, recipient_member, stranger = world.user(), world.user(), world.user()
    world.member(giving.occasion, recipient_member)
    world._add(ListOwner(list_id=giving.list_id, user_id=recipient_member))
    world.claim(giving.gift, giving.occasion, giving.ana, bought=True)
    for participant in (removed, stranger, giving.owner, recipient_member):
        world._add(ClaimParticipant(gift_id=giving.gift, user_id=participant))
    for follower in (removed, stranger, giving.owner, recipient_member, giving.ana):
        world.follow(giving.occasion, giving.gift, follower)
    comment = world.comment(giving.occasion, giving.gift, giving.ben)

    changed = world.gift_changed(giving.gift, world.user("Someone"))
    commented = world.comment_added(giving.occasion, giving.gift, giving.ben, comment)
    fan_out(world)

    assert world.targets(changed) == {giving.ana}
    assert world.targets(commented) == {giving.ana}


# Once only, and failures.


def test_fanning_out_the_same_event_twice_inserts_nothing_twice(world, giving):
    world.claim(giving.gift, giving.occasion, giving.ana)
    event = world.gift_changed(giving.gift, giving.owner)
    fan_out(world)
    first = {row.id for row in world.notifications(event)}
    digests = {digest.id for digest in world.digests()}

    with Session(world.engine) as db, db.begin():
        db.execute(
            update(NotificationEvent)
            .where(NotificationEvent.id == event)
            .values(status="pending")
        )
    fan_out(world)

    assert {row.id for row in world.notifications(event)} == first
    assert {digest.id for digest in world.digests()} == digests


def test_a_fan_out_that_keeps_raising_backs_off_then_fails_and_is_logged(
    world, giving, caplog
):
    # A malformed payload stands for any unexpected error.
    event = world.event("gift_deleted", {}, giving.owner, gift=giving.gift)

    now = NOW
    for attempt, wait in enumerate((1, 5, 30, 120), start=1):
        counts = fan_out(world, now)
        row = world.event_row(event)
        assert (row.status, row.attempts) == ("pending", attempt)
        assert row.next_attempt_at == now + wait * MINUTE
        assert counts.failed == 0
        assert fan_out(world, now).events == 0  # not due again until then
        now += wait * MINUTE

    with caplog.at_level(logging.ERROR, logger="app.notifications.fanout"):
        counts = fan_out(world, now)

    row = world.event_row(event)
    assert counts.failed == 1
    assert (row.status, row.reason, row.attempts) == ("failed", "error", 5)
    assert row.processed_at == now
    lines = [r.getMessage() for r in caplog.records]
    assert lines[-1] == f"notifications: event {event} (gift_deleted) failed"
    assert lines[:-1] == [
        f"notifications: event {event} (gift_deleted) attempt {n} failed (KeyError)"
        for n in range(1, 5)
    ]
    # Never retried.
    assert fan_out(world, now + 1000 * MINUTE).events == 0


def test_a_failing_event_does_not_keep_another_from_being_fanned_out(world, giving):
    world.claim(giving.gift, giving.occasion, giving.ana)
    bad = world.event("gift_deleted", {}, giving.owner, gift=giving.gift)
    good = world.gift_changed(giving.gift, giving.owner)

    fan_out(world)

    assert world.event_row(bad).status == "pending"
    assert world.targets(good) == {giving.ana}
