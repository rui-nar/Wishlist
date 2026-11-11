"""`POST /api/billing/google/notifications` (Android release plan D6): the
Pub/Sub push's token verified, then the notification only a pointer to the
purchase, read back from Google (the fake). Also a notification and a report
racing, and two reports (Review envelope, Concurrency)."""

import base64
import json
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from google_fakes import (
    ORDER,
    TOKEN,
    GoogleKeys,
    developer_notification,
    other_signer,
    push_body,
)
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing import google_events
from app.billing.google_gateway import GoogleUnavailable
from app.billing.models import Entitlement

ROUTE = "/api/billing/google/notifications"
PURCHASES = "/api/billing/google/purchases"
LOGGER = "app.billing.router"
INVALID = (400, {"detail": "Invalid notification"})
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


def deliver(client, keys, notification=None, headers=None, **claims):
    return client.post(
        ROUTE,
        json=push_body(notification or developer_notification()),
        headers=keys.headers(**claims) if headers is None else headers,
    )


def notify(client, fake, token=TOKEN, kind="subscription"):
    response = deliver(client, fake.keys, developer_notification(token, kind))
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


def test_404_without_the_gateway(make_client, google_keys):
    response = deliver(make_client(), google_keys)
    assert answer(response) == (404, {"detail": "Not found"})


def test_a_renewal_is_recorded(client, fake, account, engine):
    end = sessions.utc_now() + timedelta(days=365)
    fake.add(TOKEN, account.id, expires=end, acknowledged=True)

    notify(client, fake)

    found = row(engine)
    assert (found.source, found.external_id, found.user_id, found.status) == (
        "google",
        TOKEN,
        account.id,
        "active",
    )
    assert fake.calls == [("subscription", (TOKEN,))]


def test_a_notification_acknowledges_an_accepted_purchase(
    client, fake, account, engine
):
    """Review R2-1: a Play Store resubscription involves no app, so the
    notification acknowledges it, or Google refunds it on the third day."""
    fake.add(
        "old-token",
        account.id,
        state=google_events.EXPIRED,
        auto_renew=False,
        acknowledged=True,
    )
    notify(client, fake, "old-token")
    fake.add(TOKEN, None, expired_token="old-token")

    notify(client, fake)

    assert fake.called("acknowledge") == [(TOKEN,)]
    assert fake.purchases[TOKEN]["acknowledgementState"] == (
        "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"
    )
    found = {entry.external_id: entry for entry in rows(engine)}
    assert (found[TOKEN].status, found[TOKEN].user_id) == ("active", account.id)


def test_a_notification_acknowledges_before_writing_and_retries(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id)
    fake.failures["acknowledge"] = GoogleUnavailable()

    response = deliver(client, fake.keys)

    assert answer(response) == (
        502,
        {"detail": "Billing is unavailable", "code": "billing_unavailable"},
    )
    assert rows(engine) == []
    del fake.failures["acknowledge"]
    notify(client, fake)
    assert row(engine).status == "active"
    assert fake.called("acknowledge") == [(TOKEN,), (TOKEN,)]


@pytest.mark.parametrize(
    "fields, env",
    [
        ({"product": "example.other"}, "dev"),
        ({"test": False}, "validation"),
        ({"test": True}, "production"),
    ],
    ids=["another product", "a real purchase on VAL", "an unlisted test on PROD"],
)
def test_a_refused_purchase_is_not_acknowledged(
    make_google_client, account, engine, fields, env
):
    client = make_google_client(app_env=env)
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, **fields)

    notify(client, fake)

    assert rows(engine) == []
    assert fake.called("acknowledge") == []


def test_a_purchase_of_no_known_account_is_not_acknowledged(client, fake, engine):
    fake.add(TOKEN, None)
    notify(client, fake)
    assert rows(engine) == []
    assert fake.called("acknowledge") == []


def test_an_acknowledged_purchase_is_left_alone(client, fake, account, engine):
    fake.add(TOKEN, account.id, acknowledged=True)
    notify(client, fake)
    assert row(engine).status == "active"
    assert fake.called("acknowledge") == []


@pytest.mark.parametrize(
    "state, auto_renew, status, renewing",
    [
        (google_events.STATE_ACTIVE, True, "active", True),
        (google_events.CANCELED, False, "active", False),
        (google_events.IN_GRACE_PERIOD, True, "past_due", True),
        (google_events.ON_HOLD, True, "ended", True),
        (google_events.PAUSED, True, "ended", True),
        (google_events.EXPIRED, False, "ended", False),
    ],
)
def test_each_state_of_d6(
    client, fake, account, engine, state, auto_renew, status, renewing
):
    fake.add(TOKEN, account.id, state=state, auto_renew=auto_renew)

    notify(client, fake)

    assert row(engine).status == status
    body = client.get("/api/billing", headers=account.headers).json()
    assert body["google_renewing"] is renewing


def test_a_refund_with_revocation_reads_as_expired(client, fake, account, engine):
    """Review R1-4: the voided notification is a pointer too; Play's state,
    expired once revoked, decides."""
    fake.add(TOKEN, account.id)
    notify(client, fake)
    fake.add(TOKEN, account.id, state=google_events.EXPIRED, auto_renew=False)

    notify(client, fake, kind="voided")

    assert (row(engine).status, row(engine).cancel_at_period_end) == ("ended", True)
    assert client.get("/api/billing", headers=account.headers).json()["plan"] == (
        "free"
    )


def test_a_refund_without_revocation_changes_nothing_play_does_not_say(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id)
    notify(client, fake)

    notify(client, fake, kind="voided")

    assert (row(engine).status, row(engine).cancel_at_period_end) == ("active", False)


def test_a_voided_one_time_product_is_acknowledged_unread(client, fake):
    notification = developer_notification(kind="voided")
    notification["voidedPurchaseNotification"]["productType"] = 2
    assert deliver(client, fake.keys, notification).status_code == 200
    assert fake.calls == []


def test_the_notification_is_only_a_pointer(client, fake, account, engine):
    """It says renewed; Google says expired: Google wins."""
    fake.add(TOKEN, account.id, state=google_events.EXPIRED, auto_renew=False)
    notify(client, fake)
    assert row(engine).status == "ended"


# The push's authentication: a forged or tampered one changes nothing.


def assert_refused(client, fake, engine, response):
    assert answer(response) == INVALID
    assert rows(engine) == []
    assert fake.calls == []


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "https://wishlist.example.test/elsewhere"},
        {"email": "someone@example-project.iam.gserviceaccount.com"},
        {"email_verified": False},
        {"email": None},
        {"iss": "https://evil.example"},
        {"exp": 1_000_000_000, "iat": 999_996_400},
    ],
    ids=[
        "another audience",
        "another service account",
        "unverified email",
        "no email",
        "another issuer",
        "expired",
    ],
)
def test_a_push_with_wrong_claims_writes_nothing(
    client, fake, account, engine, caplog, claims
):
    fake.add(TOKEN, account.id)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = deliver(client, fake.keys, **claims)
    assert_refused(client, fake, engine, response)
    assert "a push failed its check" in caplog.text


def test_a_push_signed_by_another_key_writes_nothing(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    forged = fake.keys.token(signer=other_signer())
    response = deliver(client, fake.keys, headers={"Authorization": f"Bearer {forged}"})
    assert_refused(client, fake, engine, response)


def test_a_tampered_push_token_writes_nothing(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    header, _, signature = fake.keys.token(aud="elsewhere").split(".")
    payload = fake.keys.token().split(".")[1]
    tampered = ".".join([header, payload, signature])
    response = deliver(
        client, fake.keys, headers={"Authorization": f"Bearer {tampered}"}
    )
    assert_refused(client, fake, engine, response)


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Bearer ", "Basic abc", "Bearer not-a-jwt", "Bearer a.b.c"],
)
def test_a_push_without_a_token_writes_nothing_and_fetches_nothing(
    client, fake, account, engine, authorization
):
    keys = GoogleKeys()
    fake.push = keys.verifier()
    fake.add(TOKEN, account.id)
    headers = {} if authorization is None else {"Authorization": authorization}
    response = deliver(client, keys, headers=headers)
    assert_refused(client, fake, engine, response)
    # Junk costs no request for Google's certificates.
    assert keys.fetches == 0


def test_a_session_is_nothing_to_it(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    response = deliver(client, fake.keys, headers=account.headers)
    assert_refused(client, fake, engine, response)


def test_googles_certificates_unavailable_is_502_and_retried(
    client, fake, account, engine
):
    keys = GoogleKeys()
    fake.push = keys.verifier()
    fake.add(TOKEN, account.id)
    keys.unavailable = True

    response = deliver(client, keys)

    assert answer(response) == (
        502,
        {"detail": "Billing is unavailable", "code": "billing_unavailable"},
    )
    assert rows(engine) == []
    keys.unavailable = False
    assert deliver(client, keys).status_code == 200
    assert row(engine).status == "active"


@pytest.mark.parametrize(
    "body",
    [
        b"",
        b"not json",
        b"[]",
        b'{"message": {}}',
        b'{"message": {"data": 1}}',
        b'{"message": {"data": "not base64!"}}',
        json.dumps({"message": {"data": base64.b64encode(b"[]").decode()}}).encode(),
        b"\xff",
    ],
)
def test_a_malformed_body_is_invalid(client, fake, body):
    response = client.post(ROUTE, content=body, headers=fake.keys.headers())
    assert answer(response) == INVALID
    assert fake.calls == []


def test_a_body_over_one_mebibyte_is_invalid(client, fake):
    body = json.dumps({"message": {"data": "x" * (1024 * 1024)}}).encode()
    response = client.post(ROUTE, content=body, headers=fake.keys.headers())
    assert answer(response) == INVALID


def test_the_bad_push_warning_is_rate_limited(client, fake, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for _ in range(3):
            deliver(client, fake.keys, aud="elsewhere")
    assert caplog.text.count("a push failed its check") == 1


def test_a_test_notification_is_acknowledged(client, fake):
    response = deliver(client, fake.keys, developer_notification(kind="test"))
    assert (response.status_code, response.content) == (200, b"")
    assert fake.calls == []


def test_another_apps_notification_is_acknowledged_unread(client, fake, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = deliver(
            client, fake.keys, developer_notification(package="com.example.other")
        )
    assert response.status_code == 200
    assert fake.calls == []
    assert "a notification for another app" in caplog.text


def test_a_notification_pointing_at_no_token_is_acknowledged(client, fake, caplog):
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = deliver(client, fake.keys, developer_notification("not a token"))
    assert response.status_code == 200
    assert fake.calls == []
    assert "a notification points at no purchase" in caplog.text


def test_repeats_change_nothing(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    for _ in range(3):
        notify(client, fake)
    assert row(engine).status == "active"


def test_an_unknown_purchase_is_acknowledged_and_logged(client, fake, engine, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake, kind="voided")
    assert rows(engine) == []
    assert f"a notified purchase is unknown to Google (order {ORDER})" in caplog.text


def test_google_failing_is_502_and_pubsub_retries(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    fake.failures["subscription"] = GoogleUnavailable()

    response = deliver(client, fake.keys)

    assert answer(response) == (
        502,
        {"detail": "Billing is unavailable", "code": "billing_unavailable"},
    )
    assert rows(engine) == []
    del fake.failures["subscription"]
    notify(client, fake)
    assert row(engine).status == "active"


# D6: whose the purchase is, in order (review R1-1).


def test_no_account_id_keeps_the_stored_rows_account(
    client, fake, make_account, engine
):
    first = make_account()
    fake.add(TOKEN, first.id)
    notify(client, fake)
    fake.add(TOKEN, None, state=google_events.EXPIRED, auto_renew=False)

    notify(client, fake)

    assert (row(engine).user_id, row(engine).status) == (first.id, "ended")


def test_an_account_id_naming_no_account_falls_back_to_the_stored_row(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id)
    notify(client, fake)
    fake.add(TOKEN, uuid.uuid4(), state=google_events.EXPIRED, auto_renew=False)

    notify(client, fake)

    assert (row(engine).user_id, row(engine).status) == (account.id, "ended")


def test_a_play_store_resubscription_is_the_expired_ones_account(
    client, fake, account, engine
):
    fake.add("old-token", account.id, state=google_events.EXPIRED, auto_renew=False)
    notify(client, fake, "old-token")
    fake.add(TOKEN, None, expired_token="old-token")

    notify(client, fake)

    assert {(found.external_id, found.user_id) for found in rows(engine)} == {
        ("old-token", account.id),
        (TOKEN, account.id),
    }


def test_no_account_and_no_row_is_logged(client, fake, engine, caplog):
    fake.add(TOKEN, None)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    assert rows(engine) == []
    assert f"purchase {ORDER} of no known account" in caplog.text


def test_a_replacing_token_ends_the_one_it_replaces(client, fake, account, engine):
    fake.add("old-token", account.id)
    notify(client, fake, "old-token")
    fake.add(TOKEN, None, linked="old-token")

    notify(client, fake)

    found = {entry.external_id: entry for entry in rows(engine)}
    assert (found["old-token"].status, found["old-token"].cancel_at_period_end) == (
        "ended",
        True,
    )
    assert (found[TOKEN].status, found[TOKEN].user_id) == ("active", account.id)


def test_another_product_is_logged_and_ignored(client, fake, account, engine, caplog):
    fake.add(TOKEN, account.id, product="example.other")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    assert rows(engine) == []
    assert f"purchase {ORDER} is of another product" in caplog.text


# D6: test purchases.


def test_val_records_no_real_purchase(make_google_client, account, engine, caplog):
    client = make_google_client(app_env="validation")
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, test=False)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)

    assert rows(engine) == []
    assert f"purchase {ORDER} refused for account {account.id}" in caplog.text


def test_production_records_tests_for_a_listed_account_only(
    make_google_client, make_account, engine, caplog
):
    listed, tester = make_account(), make_account()
    client = make_google_client(
        app_env="production", google_play_test_account_ids=str(listed.id)
    )
    fake = client.app.state.google_gateway
    fake.add(TOKEN, tester.id, test=True)
    fake.add("listed-token", listed.id, test=True)
    fake.add("real-token", tester.id, test=False)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        for token in (TOKEN, "listed-token", "real-token"):
            notify(client, fake, token)

    assert {(found.external_id, found.user_id) for found in rows(engine)} == {
        ("listed-token", listed.id),
        ("real-token", tester.id),
    }
    assert "test_refused" in caplog.text


# An account gone before the write: Google lets the server cancel.


def delete_once_found(engine, account, monkeypatch):
    deleted = threading.Event()
    scalar = Session.scalar

    def deleting(self, statement, *args, **kwargs):
        result = scalar(self, statement, *args, **kwargs)
        if result == account.id and not deleted.is_set():
            deleted.set()
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM users WHERE id = :id"), {"id": account.id}
                )
        return result

    monkeypatch.setattr(Session, "scalar", deleting)
    return deleted


def test_a_gone_accounts_renewing_purchase_is_cancelled(
    client, fake, account, engine, caplog, monkeypatch
):
    fake.add(TOKEN, account.id)
    deleted = delete_once_found(engine, account, monkeypatch)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        notify(client, fake)
    monkeypatch.undo()

    assert deleted.is_set()
    assert rows(engine) == []
    assert fake.called("cancel") == [(TOKEN,)]
    assert f"cancelling purchase {ORDER} of a gone account" in caplog.text


def test_a_gone_accounts_cancel_failing_is_502(
    client, fake, account, engine, monkeypatch
):
    fake.add(TOKEN, account.id)
    fake.failures["cancel"] = GoogleUnavailable()
    delete_once_found(engine, account, monkeypatch)
    response = deliver(client, fake.keys)
    monkeypatch.undo()
    assert response.status_code == 502


def test_a_gone_accounts_finished_purchase_is_left(
    client, fake, account, engine, monkeypatch
):
    fake.add(TOKEN, account.id, state=google_events.CANCELED, auto_renew=False)
    delete_once_found(engine, account, monkeypatch)
    notify(client, fake)
    monkeypatch.undo()
    assert fake.called("cancel") == []


def test_no_token_in_the_log(client, fake, account, caplog):
    fake.add(TOKEN, None)
    with caplog.at_level(logging.DEBUG):
        notify(client, fake)
        deliver(client, fake.keys, aud="elsewhere")
        notify(client, fake, "unknown-token")
    assert TOKEN not in caplog.text
    assert "unknown-token" not in caplog.text
    assert fake.keys.token().split(".")[2][:20] not in caplog.text


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
    fake.add(TOKEN, account.id, expires=old_end)
    release = threading.Event()
    reading = stall_first_read(fake, release)

    with ThreadPoolExecutor(max_workers=1) as pool:
        # The report has read the old state, and stalls before writing it.
        older = pool.submit(
            client.post,
            PURCHASES,
            json={"purchase_token": TOKEN},
            headers=account.headers,
        )
        assert reading.wait(TIMEOUT)
        fake.add(TOKEN, account.id, expires=new_end, acknowledged=True)
        notify(client, fake)
        release.set()
        assert older.result(timeout=TIMEOUT).status_code == 204

    assert abs(row(engine).period_end - new_end) < timedelta(milliseconds=1)


def test_an_older_notification_committing_after_a_newer_report_loses(
    client, fake, account, engine
):
    old_end = sessions.utc_now() + timedelta(days=30)
    new_end = sessions.utc_now() + timedelta(days=400)
    fake.add(TOKEN, account.id, expires=old_end)
    release = threading.Event()
    reading = stall_first_read(fake, release)

    with ThreadPoolExecutor(max_workers=1) as pool:
        older = pool.submit(deliver, client, fake.keys)
        assert reading.wait(TIMEOUT)
        fake.add(TOKEN, account.id, expires=new_end)
        response = client.post(
            PURCHASES, json={"purchase_token": TOKEN}, headers=account.headers
        )
        assert response.status_code == 204
        release.set()
        assert older.result(timeout=TIMEOUT).status_code == 200

    assert abs(row(engine).period_end - new_end) < timedelta(milliseconds=1)


def test_two_reports_at_once_make_one_row(client, fake, account, engine):
    fake.add(TOKEN, account.id)
    both_reading = threading.Barrier(2, timeout=TIMEOUT)
    fake.on_call = lambda name: name == "subscription" and both_reading.wait()

    def post():
        return client.post(
            PURCHASES, json={"purchase_token": TOKEN}, headers=account.headers
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(post) for _ in range(2)]
        statuses = [result.result(timeout=TIMEOUT).status_code for result in results]

    assert statuses == [204, 204]
    assert row(engine).status == "active"
