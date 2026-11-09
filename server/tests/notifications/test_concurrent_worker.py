"""Two processes running the worker at once (comments plan D16, Review
envelope): each event fanned out once, each digest sent once.
"""

import threading
import uuid
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy.orm import Session
from worker_world import MINUTE, NOW, World, config

from app.lists.models import Gift
from app.notifications.digests import SEND_BATCH
from app.notifications.fanout import EVENT_BATCH
from app.notifications.models import EmailDigest, Notification, NotificationEvent
from app.notifications.worker import run_once
from app.reserving.models import ClaimParticipant, GiftClaim

ROUNDS = 20
EVENTS = 100
TIMEOUT_SECONDS = 60


def together(*calls: Callable[[], Any]) -> list[Any]:
    """Runs the calls in threads released at the same moment."""
    start = threading.Barrier(len(calls), timeout=TIMEOUT_SECONDS)

    def run(call: Callable[[], Any]) -> Any:
        start.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=TIMEOUT_SECONDS) for future in futures]


def build_round(world, owner, ana, list_id, occasion):
    gifts = [uuid.uuid4() for _ in range(EVENTS)]
    with Session(world.engine) as db, db.begin():
        db.add_all(
            Gift(id=g, list_id=list_id, title=f"G{g}", description="", links=[])
            for g in gifts
        )
    with Session(world.engine) as db, db.begin():
        db.add_all(
            GiftClaim(gift_id=g, occasion_id=occasion, kind="reservation")
            for g in gifts
        )
    with Session(world.engine) as db, db.begin():
        db.add_all(ClaimParticipant(gift_id=g, user_id=ana) for g in gifts)
    with Session(world.engine) as db, db.begin():
        db.add_all(
            NotificationEvent(
                kind="gift_changed",
                payload={"fields": ["title"]},
                actor_id=owner,
                gift_id=g,
                created_at=NOW,
                next_attempt_at=NOW,
            )
            for g in gifts
        )
    return gifts


def counts_of(world, model, where):
    with Session(world.engine) as db:
        return db.query(model).filter(where).count()


def two_runs(sessions, mailer, now):
    together(
        lambda: run_once(sessions, mailer, config(), now),
        lambda: run_once(sessions, mailer, config(), now),
    )


def test_two_runs_at_once_fan_out_and_send_each_once(engine, mailer):
    world = World(engine)
    owner, ana = world.user("Olga"), world.user("Ana")
    list_id = world.listing(owner)
    occasion = world.occasion(list_id)
    world.member(occasion, ana)
    sessions = world.sessions
    assert EVENT_BATCH >= EVENTS and SEND_BATCH * 2 >= EVENTS

    for round_number in range(ROUNDS):
        mailer.sent.clear()
        now = NOW + round_number * 20 * MINUTE
        gifts = build_round(world, owner, ana, list_id, occasion)

        two_runs(sessions, mailer, now)

        assert (
            counts_of(world, NotificationEvent, NotificationEvent.status == "pending")
            == 0
        )
        assert counts_of(world, Notification, Notification.gift_id.in_(gifts)) == EVENTS

        # Each digest once, by the two runs and as many more as the batch needs.
        send_at = now + 2 * MINUTE
        two_runs(sessions, mailer, send_at)
        run_once(sessions, mailer, config(), send_at)

        assert counts_of(world, EmailDigest, EmailDigest.gift_id.in_(gifts)) == EVENTS
        assert (
            counts_of(
                world,
                EmailDigest,
                EmailDigest.gift_id.in_(gifts) & (EmailDigest.status == "sent"),
            )
            == EVENTS
        )
        by_subject = Counter(message.subject for _a, _n, message in mailer.sent)
        assert len(by_subject) == EVENTS
        assert set(by_subject.values()) == {1}
