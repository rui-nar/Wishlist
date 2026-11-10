"""Webhook handlers meeting each other and an account deletion (premium plan
D13, Review envelope, Concurrency)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing.models import Entitlement

TIMEOUT = 10
UPDATED = "customer.subscription.updated"


@pytest.fixture
def client(make_client, billing_on):
    return make_client(**billing_on)


@pytest.fixture
def fake(client):
    return client.app.state.stripe_gateway


def wait_until_blocked_on_a_lock(engine):
    deadline = time.monotonic() + TIMEOUT
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            waiting = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            observer.rollback()
            if waiting:
                return
            time.sleep(0.02)
    raise AssertionError("the webhook never waited on the deletion")


def only_row(engine):
    with Session(engine) as db:
        return db.scalars(select(Entitlement)).one()


def test_an_older_read_committing_after_a_newer_one_does_not_overwrite_it(
    client, fake, engine, make_account
):
    ada = make_account()
    old_end = sessions.utc_now() + timedelta(days=30)
    new_end = sessions.utc_now() + timedelta(days=400)
    fake.add_subscription("sub_1", ada.id, period_end=old_end)
    reading = threading.Event()
    proceed = threading.Event()

    def stall_the_first_read(name):
        if name == "subscription" and not reading.is_set():
            reading.set()
            assert proceed.wait(TIMEOUT)

    fake.on_call = stall_the_first_read
    with ThreadPoolExecutor(max_workers=1) as pool:
        # This handler has read the old state, and stalls before writing it.
        older = pool.submit(fake.deliver, client, UPDATED, {"id": "sub_1"})
        assert reading.wait(TIMEOUT)
        fake.add_subscription("sub_1", ada.id, period_end=new_end)
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
        proceed.set()
        assert older.result(timeout=TIMEOUT).status_code == 204

    assert only_row(engine).period_end == new_end.replace(microsecond=0)


def test_a_webhook_during_an_account_deletion_waits_then_finds_the_user_gone(
    client, fake, engine, make_account
):
    ada = make_account()
    fake.add_subscription("sub_1", ada.id)
    with engine.connect() as deleting:
        deleting.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": ada.id}
        )
        deleting.execute(text("DELETE FROM users WHERE id = :id"), {"id": ada.id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            arriving = pool.submit(fake.deliver, client, UPDATED, {"id": "sub_1"})
            wait_until_blocked_on_a_lock(engine)
            deleting.commit()
            response = arriving.result(timeout=TIMEOUT)

    assert response.status_code == 204
    assert fake.called("cancel") == [("sub_1",)]
    with Session(engine) as db:
        assert db.scalars(select(Entitlement)).all() == []
