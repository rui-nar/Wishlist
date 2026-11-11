"""`POST /api/billing/apple/notifications` (Apple IAP plan D4, D6): verified,
then only a pointer to the subscription, read back from Apple (the fake).
Also a notification and a report racing, and two reports (Review envelope,
Concurrency)."""

import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from apple_fakes import apple_ms, apple_sign, build_apple_pki, notification_claims
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing.apple_gateway import AppleUnavailable
from app.billing.models import Entitlement

ROUTE = "/api/billing/apple/notifications"
LOGGER = "app.billing.router"
ORIGINAL = "2000000001"
INVALID = (400, {"detail": "Invalid notification"})
TIMEOUT = 10


@pytest.fixture
def client(make_apple_client):
    return make_apple_client()


@pytest.fixture
def fake(client):
    return client.app.state.apple_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def deliver(client, signed):
    return client.post(ROUTE, json={"signedPayload": signed})


def notify(client, fake, external_id=ORIGINAL):
    response = deliver(client, fake.signed_notification(external_id))
    assert (response.status_code, response.content) == (200, b""), response.text
    return response


def rows(engine):
    with Session(engine) as db:
        return db.scalars(select(Entitlement)).all()


def row(engine):
    [found] = rows(engine)
    return found


def answer(response):
    return response.status_code, response.json()


def test_404_without_the_gateway(make_client):
    response = make_client().post(ROUTE, json={"signedPayload": "x"})
    assert answer(response) == (404, {"detail": "Not found"})


def test_a_renewal_is_recorded(client, fake, account, engine):
    end = sessions.utc_now() + timedelta(days=365)
    fake.add(ORIGINAL, account.id, expires=end)

    notify(client, fake)

    found = row(engine)
    assert (found.source, found.external_id, found.user_id, found.status) == (
        "apple",
        ORIGINAL,
        account.id,
        "active",
    )
    assert fake.calls == [("subscription", (ORIGINAL, "Sandbox"))]


def test_the_notification_is_only_a_pointer(client, fake, account, engine):
    """It says active; Apple says expired: Apple wins (D4)."""
    fake.add(ORIGINAL, account.id, status=2, auto_renew=0)

    notify(client, fake)

    assert row(engine).status == "ended"


@pytest.mark.parametrize(
    "apple_status, status, renewing",
    [
        (1, "active", True),
        (4, "past_due", True),
        (3, "ended", True),
        (2, "ended", False),
        (5, "ended", False),
    ],
)
def test_each_status_of_d5(
    client, fake, account, engine, apple_status, status, renewing
):
    grace = sessions.utc_now() + timedelta(days=15)
    fake.add(ORIGINAL, account.id, status=apple_status, grace=grace)

    notify(client, fake)

    assert row(engine).status == status
    body = client.get("/api/billing", headers=account.headers).json()
    assert body["apple_renewing"] is renewing


def test_a_forged_notification_writes_nothing_and_asks_nothing(
    client, fake, account, engine, caplog
):
    fake.add(ORIGINAL, account.id)
    forged_pki = build_apple_pki()
    transaction = apple_sign(fake.pki, fake.subscriptions[ORIGINAL].transaction)
    forged = apple_sign(forged_pki, notification_claims(transaction))

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = deliver(client, forged)

    assert answer(response) == INVALID
    assert rows(engine) == []
    assert fake.calls == []
    assert "a notification failed its check" in caplog.text
    assert forged.split(".")[1] not in caplog.text


def test_a_tampered_notification_writes_nothing(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    header, _, signature = fake.signed_notification(ORIGINAL).split(".")
    other = fake.signed_notification(ORIGINAL, notificationType="REFUND")
    tampered = ".".join([header, other.split(".")[1], signature])

    assert answer(deliver(client, tampered)) == INVALID
    assert rows(engine) == []
    assert fake.calls == []


def test_a_notification_pointing_at_a_forged_transaction_writes_nothing(
    client, fake, account, engine, caplog
):
    """Apple signs the notification; the transaction inside is not Apple's."""
    fake.add(ORIGINAL, account.id)
    forged = apple_sign(build_apple_pki(), fake.subscriptions[ORIGINAL].transaction)
    signed = apple_sign(fake.pki, notification_claims(forged))

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = deliver(client, signed)

    assert response.status_code == 200
    assert rows(engine) == []
    assert fake.calls == []
    assert "transaction failed its signature check" in caplog.text


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'{"signedPayload": 1}',
        b'{"signedPayload": ""}',
        b"\xff",
    ],
)
def test_a_malformed_body_is_invalid(client, fake, body):
    assert answer(client.post(ROUTE, content=body)) == INVALID
    assert fake.calls == []


def test_a_body_over_one_mebibyte_is_invalid(client, fake):
    body = json.dumps({"signedPayload": "x" * (1024 * 1024)}).encode()
    assert answer(client.post(ROUTE, content=body)) == INVALID


def test_the_bad_signature_warning_is_rate_limited(client, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(3):
            deliver(client, "not a jws")
    assert caplog.text.count("a notification failed its check") == 1


def test_a_session_is_nothing_to_it(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    response = client.post(ROUTE, json={"signedPayload": "x"}, headers=account.headers)
    assert answer(response) == INVALID
    assert rows(engine) == []


def test_a_notification_about_no_subscription_is_acknowledged(client, fake):
    summary = apple_sign(
        fake.pki,
        {
            "notificationType": "RENEWAL_EXTENSION",
            "subtype": "SUMMARY",
            "notificationUUID": str(uuid.uuid4()),
            "version": "2.0",
            "signedDate": apple_ms(sessions.utc_now()),
            "summary": {
                "environment": "Sandbox",
                "bundleId": "com.example.wishlist",
            },
        },
    )
    response = deliver(client, summary)
    assert response.status_code == 200
    assert fake.calls == []


def test_repeats_change_nothing(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    for _ in range(3):
        notify(client, fake)
    assert row(engine).status == "active"


def test_an_unknown_subscription_is_acknowledged_and_logged(
    client, fake, account, engine, caplog
):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_notification(ORIGINAL)
    del fake.subscriptions[ORIGINAL]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert deliver(client, signed).status_code == 200
    assert rows(engine) == []
    assert f"subscription {ORIGINAL} is unknown to Apple" in caplog.text


def test_apple_failing_is_502_and_apple_retries(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    fake.failures["subscription"] = AppleUnavailable()

    response = deliver(client, fake.signed_notification(ORIGINAL))

    assert answer(response) == (
        502,
        {"detail": "Billing is unavailable", "code": "billing_unavailable"},
    )
    assert rows(engine) == []
    del fake.failures["subscription"]
    notify(client, fake)
    assert row(engine).status == "active"


# D4: whose the subscription is.


def test_a_resubscription_under_another_account_moves_and_stays(
    client, fake, make_account, engine
):
    first, second = make_account(), make_account()
    fake.add(ORIGINAL, first.id)
    notify(client, fake)
    assert row(engine).user_id == first.id

    fake.add(ORIGINAL, second.id)
    notify(client, fake)
    assert row(engine).user_id == second.id

    # A later notification whose latest transaction has no token keeps it.
    fake.add(ORIGINAL, None, status=2, auto_renew=0)
    notify(client, fake)
    assert (row(engine).user_id, row(engine).status) == (second.id, "ended")


def test_no_token_and_no_row_is_logged(client, fake, engine, caplog):
    fake.add(ORIGINAL, None)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    assert rows(engine) == []
    assert f"subscription {ORIGINAL} of no known account" in caplog.text


def test_a_token_naming_no_account_is_not_the_stored_rows(
    client, fake, account, engine, caplog
):
    """The token wins when present (review R1-2): one naming a deleted account
    does not fall back to the stored row."""
    fake.add(ORIGINAL, account.id)
    notify(client, fake)
    fake.add(ORIGINAL, uuid.uuid4(), status=2, auto_renew=0)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)

    assert row(engine).status == "active"
    assert f"subscription {ORIGINAL} of no known account" in caplog.text


def test_another_product_is_logged_and_ignored(client, fake, account, engine, caplog):
    fake.add(ORIGINAL, account.id, product="example.other")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    assert rows(engine) == []
    assert f"subscription {ORIGINAL} is of another product" in caplog.text


# D6: the environments.


def test_production_records_sandbox_for_a_listed_account_only(
    make_apple_client, make_account, engine, caplog
):
    listed, tester = make_account(), make_account()
    client = make_apple_client(
        app_env="production", apple_sandbox_account_ids=str(listed.id)
    )
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, tester.id)
    fake.add("2000000002", listed.id)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake, ORIGINAL)
        notify(client, fake, "2000000002")

    assert [(found.external_id, found.user_id) for found in rows(engine)] == [
        ("2000000002", listed.id)
    ]
    assert f"Sandbox subscription {ORIGINAL} refused" in caplog.text


def test_production_records_production(make_apple_client, account, engine):
    client = make_apple_client(app_env="production")
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id, environment="Production")

    notify(client, fake)

    assert row(engine).status == "active"


def test_val_refuses_a_production_notification(make_apple_client, account, engine):
    client = make_apple_client(app_env="validation")
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id, environment="Production")

    assert answer(deliver(client, fake.signed_notification(ORIGINAL))) == INVALID
    assert rows(engine) == []


def test_a_gone_account_is_logged(client, fake, account, engine, caplog, monkeypatch):
    """Found as the owner, then deleted before the write: logged, since Apple
    cannot be told to stop (D9)."""
    fake.add(ORIGINAL, account.id)
    deleted = threading.Event()
    scalar = Session.scalar

    def delete_once_found(self, statement, *args, **kwargs):
        result = scalar(self, statement, *args, **kwargs)
        if result == account.id and not deleted.is_set():
            deleted.set()
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM users WHERE id = :id"), {"id": account.id}
                )
        return result

    monkeypatch.setattr(Session, "scalar", delete_once_found)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    monkeypatch.undo()

    assert deleted.is_set()
    assert rows(engine) == []
    assert f"subscription {ORIGINAL} of a gone account" in caplog.text


# Concurrency.


def stall_first_read(fake, release):
    reading = threading.Event()

    def on_call(name):
        if name == "subscription" and not reading.is_set():
            reading.set()
            assert release.wait(TIMEOUT)

    fake.on_call = on_call
    return reading


def test_an_older_report_committing_after_a_newer_notification_loses(
    client, fake, account, engine
):
    old_end = sessions.utc_now() + timedelta(days=30)
    new_end = sessions.utc_now() + timedelta(days=400)
    fake.add(ORIGINAL, account.id, expires=old_end)
    signed = fake.signed_transaction(ORIGINAL)
    release = threading.Event()
    reading = stall_first_read(fake, release)

    with ThreadPoolExecutor(max_workers=1) as pool:
        # The report has read the old state, and stalls before writing it.
        older = pool.submit(
            client.post,
            "/api/billing/apple/transactions",
            json={"signed_transaction": signed},
            headers=account.headers,
        )
        assert reading.wait(TIMEOUT)
        fake.add(ORIGINAL, account.id, expires=new_end)
        notify(client, fake)
        release.set()
        assert older.result(timeout=TIMEOUT).status_code == 204

    assert abs(row(engine).period_end - new_end) < timedelta(milliseconds=1)


def test_an_older_notification_committing_after_a_newer_report_loses(
    client, fake, account, engine
):
    old_end = sessions.utc_now() + timedelta(days=30)
    new_end = sessions.utc_now() + timedelta(days=400)
    fake.add(ORIGINAL, account.id, expires=old_end)
    signed_notification = fake.signed_notification(ORIGINAL)
    release = threading.Event()
    reading = stall_first_read(fake, release)

    with ThreadPoolExecutor(max_workers=1) as pool:
        older = pool.submit(deliver, client, signed_notification)
        assert reading.wait(TIMEOUT)
        fake.add(ORIGINAL, account.id, expires=new_end)
        response = client.post(
            "/api/billing/apple/transactions",
            json={"signed_transaction": fake.signed_transaction(ORIGINAL)},
            headers=account.headers,
        )
        assert response.status_code == 204
        release.set()
        assert older.result(timeout=TIMEOUT).status_code == 200

    assert abs(row(engine).period_end - new_end) < timedelta(milliseconds=1)


def test_two_reports_at_once_make_one_row(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    both_reading = threading.Barrier(2, timeout=TIMEOUT)
    fake.on_call = lambda name: both_reading.wait()

    def post():
        return client.post(
            "/api/billing/apple/transactions",
            json={"signed_transaction": signed},
            headers=account.headers,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(post) for _ in range(2)]
        statuses = [result.result(timeout=TIMEOUT).status_code for result in results]

    assert statuses == [204, 204]
    assert row(engine).status == "active"
