"""`DELETE /api/me` past a Google subscription (Android release plan D6):
unlike Apple, Google lets the server cancel, so a renewing one is cancelled
before the account goes, as Stripe's is, with the same refusals when Google
cannot be asked. The admin's deletion:
tests/admin/test_admin_google_subscriptions.py."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from google_fakes import TOKEN
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User
from app.billing import google_events
from app.billing.google_gateway import GoogleUnavailable
from app.billing.models import Entitlement

LOGGER = "app.billing.closing"
TIMEOUT = 10


@pytest.fixture
def client(make_google_client):
    return make_google_client()


@pytest.fixture
def fake(client):
    return client.app.state.google_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def add(engine, user_id, token=TOKEN, **fields):
    now = sessions.utc_now()
    values = {
        "user_id": user_id,
        "source": "google",
        "external_id": token,
        "status": "active",
        "period_end": now + timedelta(days=100),
        "cancel_at_period_end": False,
        "started_at": now - timedelta(days=100),
        "read_at": now,
    } | fields
    with Session(engine) as db, db.begin():
        db.add(Entitlement(**values))


def delete_account(client, account):
    return client.delete("/api/me", headers=account.headers)


def count(engine, model, user_id):
    column = model.id if model is User else model.user_id
    with Session(engine) as db:
        return db.scalar(
            select(func.count()).select_from(model).where(column == user_id)
        )


def gone(engine, user_id):
    return not count(engine, User, user_id) and not count(engine, Entitlement, user_id)


def test_a_renewing_one_is_cancelled_before_the_account_goes(
    client, fake, account, engine
):
    add(engine, account.id)
    fake.add(TOKEN, account.id)
    seen = []
    fake.on_call = lambda name: seen.append((name, count(engine, User, account.id)))

    assert delete_account(client, account).status_code == 204

    assert fake.calls == [("subscription", (TOKEN,)), ("cancel", (TOKEN,))]
    assert seen == [("subscription", 1), ("cancel", 1)]
    assert gone(engine, account.id)


def test_one_google_no_longer_renews_is_not_cancelled(client, fake, account, engine):
    """Our row can be late: Google is asked first."""
    add(engine, account.id)
    fake.add(TOKEN, account.id, state=google_events.CANCELED, auto_renew=False)

    assert delete_account(client, account).status_code == 204

    assert fake.called("cancel") == []
    assert gone(engine, account.id)


def test_one_google_does_not_know_is_not_cancelled(client, fake, account, engine):
    add(engine, account.id)

    assert delete_account(client, account).status_code == 204

    assert fake.called("cancel") == []
    assert gone(engine, account.id)


@pytest.mark.parametrize("status", ["ended", "active"])
def test_one_set_to_stop_calls_no_one(client, fake, account, engine, status):
    add(engine, account.id, status=status, cancel_at_period_end=True)

    assert delete_account(client, account).status_code == 204

    assert fake.calls == []
    assert gone(engine, account.id)


def test_one_on_hold_is_cancelled(client, fake, account, engine):
    """On hold grants nothing, yet Google may still charge it."""
    add(engine, account.id, status="ended")
    fake.add(TOKEN, account.id, state=google_events.ON_HOLD)

    assert delete_account(client, account).status_code == 204

    assert fake.called("cancel") == [(TOKEN,)]


@pytest.mark.parametrize("failing", ["subscription", "cancel"])
def test_google_failing_deletes_nothing_and_retrying_works(
    client, fake, account, engine, failing
):
    add(engine, account.id)
    fake.add(TOKEN, account.id)
    fake.failures[failing] = GoogleUnavailable()

    response = delete_account(client, account)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )
    assert count(engine, User, account.id) == 1
    assert count(engine, Entitlement, account.id) == 1

    del fake.failures[failing]
    assert delete_account(client, account).status_code == 204
    assert gone(engine, account.id)


def test_409_with_no_gateway_and_a_renewing_row(make_client, account, engine, caplog):
    add(engine, account.id)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = delete_account(make_client(), account)

    assert (response.status_code, response.json()["code"]) == (
        409,
        "billing_unavailable",
    )
    assert "selling on Android is not configured" in caplog.text
    assert TOKEN not in caplog.text
    assert count(engine, User, account.id) == 1


def test_no_gateway_and_a_row_set_to_stop_is_deleted(make_client, account, engine):
    add(engine, account.id, cancel_at_period_end=True)
    assert delete_account(make_client(), account).status_code == 204
    assert gone(engine, account.id)


def test_stripe_and_google_both_stopped(
    make_google_client, billing_on, account, engine
):
    client = make_google_client(**billing_on)
    stripe, google = client.app.state.stripe_gateway, client.app.state.google_gateway
    add(engine, account.id)
    google.add(TOKEN, account.id)
    with Session(engine) as db, db.begin():
        db.add(
            Entitlement(
                user_id=account.id,
                source="stripe",
                external_id="sub_1",
                status="active",
                period_end=sessions.utc_now() + timedelta(days=30),
                cancel_at_period_end=False,
                started_at=sessions.utc_now() - timedelta(days=100),
                read_at=sessions.utc_now(),
            )
        )

    assert delete_account(client, account).status_code == 204

    assert stripe.calls == [("cancel", ("sub_1",))]
    assert google.called("cancel") == [(TOKEN,)]


def test_a_row_recorded_during_the_google_call_is_reported_without_its_token(
    client, fake, account, engine, caplog
):
    """Review R6-1, for Google: a notification recorded it after
    `stop_billing` read the rows. Named by our id only."""
    add(engine, account.id)
    fake.add(TOKEN, account.id)

    def record_late(name):
        if name == "cancel":
            add(engine, account.id, token="late-token")

    fake.on_call = record_late

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    errors = [
        record.getMessage()
        for record in caplog.records
        if "recorded during its deletion" in record.getMessage()
    ]
    assert len(errors) == 1
    assert "Play Console" in errors[0]
    assert "late-token" not in caplog.text
    assert TOKEN not in caplog.text


def test_a_concurrent_request_does_not_wait_during_the_google_call(
    client, fake, account, engine
):
    add(engine, account.id)
    fake.add(TOKEN, account.id)
    reached = threading.Event()
    proceed = threading.Event()

    def hold(name):
        if name != "cancel":
            return
        reached.set()
        assert proceed.wait(TIMEOUT)

    fake.on_call = hold
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(delete_account, client, account)
        try:
            assert reached.wait(TIMEOUT)
            asking = pool.submit(client.get, "/api/me", headers=account.headers)
            assert asking.result(timeout=TIMEOUT).status_code == 200
        finally:
            proceed.set()
        assert deleting.result(timeout=TIMEOUT).status_code == 204

    assert gone(engine, account.id)
