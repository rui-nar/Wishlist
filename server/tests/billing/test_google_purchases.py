"""`POST /api/billing/google/purchases` (Android release plan D6): the token
only a pointer, what is recorded is Google's answer (the fake's), and an
accepted purchase acknowledged."""

import logging
import uuid
from datetime import timedelta

import pytest
from google_fakes import ORDER, PRODUCT_ID, TOKEN
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing import google_events
from app.billing.google_events import (
    CANCELED,
    EXPIRED,
    IN_GRACE_PERIOD,
    ON_HOLD,
    PAUSED,
    STATE_ACTIVE,
)
from app.billing.google_gateway import GoogleUnavailable, MissingAtGoogle
from app.billing.models import Entitlement

ROUTE = "/api/billing/google/purchases"
LOGGER = "app.billing.router"
ACKNOWLEDGED = "ACKNOWLEDGEMENT_STATE_ACKNOWLEDGED"


@pytest.fixture
def client(make_google_client):
    return make_google_client()


@pytest.fixture
def fake(client):
    return client.app.state.google_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def report(client, account, token=TOKEN):
    return client.post(ROUTE, json={"purchase_token": token}, headers=account.headers)


def rows(engine):
    with Session(engine) as db:
        return db.scalars(select(Entitlement).order_by(Entitlement.created_at)).all()


def row(engine):
    [found] = rows(engine)
    return found


def refused(response, status, code):
    assert (response.status_code, response.json()["code"]) == (status, code), (
        response.text
    )


def plan(client, account):
    return client.get("/api/billing", headers=account.headers).json()


def add_row(engine, user_id, token, **fields):
    now = sessions.utc_now()
    values = {
        "user_id": user_id,
        "source": "google",
        "external_id": token,
        "status": "ended",
        "period_end": now - timedelta(days=10),
        "cancel_at_period_end": True,
        "read_at": now - timedelta(days=10),
    } | fields
    with Session(engine) as db, db.begin():
        db.add(Entitlement(**values))


def test_404_without_the_gateway(make_client, account):
    response = report(make_client(), account)
    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})


def test_401_signed_out(client, fake):
    fake.add(TOKEN, uuid.uuid4())
    response = client.post(ROUTE, json={"purchase_token": TOKEN})
    assert response.status_code == 401
    assert fake.calls == []


def test_a_purchase_grants_premium_and_is_acknowledged(client, fake, account, engine):
    end = sessions.utc_now() + timedelta(days=365)
    fake.add(TOKEN, account.id, expires=end)

    response = report(client, account)

    assert response.status_code == 204, response.text
    found = row(engine)
    assert (found.source, found.external_id, found.user_id, found.status) == (
        "google",
        TOKEN,
        account.id,
        "active",
    )
    assert abs(found.period_end - end) < timedelta(milliseconds=1)
    assert found.cancel_at_period_end is False
    status = plan(client, account)
    assert (status["plan"], status["source"], status["status"]) == (
        "premium",
        "google",
        "active",
    )
    assert status["google_renewing"] is True
    assert fake.calls == [("subscription", (TOKEN,)), ("acknowledge", (TOKEN,))]
    assert fake.purchases[TOKEN]["acknowledgementState"] == ACKNOWLEDGED


def test_an_acknowledged_purchase_is_not_acknowledged_again(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id, acknowledged=True)
    assert report(client, account).status_code == 204
    assert fake.called("acknowledge") == []
    assert row(engine).status == "active"


# D6, through the report: Play's state -> (status, plan, renewing).
STATES = {
    "active": (STATE_ACTIVE, True, "active", "premium", True),
    "cancelled, still paid": (CANCELED, False, "active", "premium", False),
    "grace period": (IN_GRACE_PERIOD, True, "past_due", "premium", True),
    "on hold": (ON_HOLD, True, "ended", "free", True),
    "paused": (PAUSED, True, "ended", "free", True),
    "expired": (EXPIRED, False, "ended", "free", False),
}


@pytest.mark.parametrize("case", STATES)
def test_each_state_of_d6(client, fake, account, engine, case):
    state, auto_renew, status, shown, renewing = STATES[case]
    now = sessions.utc_now()
    granting = state in (google_events.STATE_ACTIVE, google_events.CANCELED)
    # In the grace period, Google extends `expiryTime` to its end.
    end = now + timedelta(days=30 if granting else -1)
    if state == google_events.IN_GRACE_PERIOD:
        end = now + timedelta(days=7)
    fake.add(TOKEN, account.id, state=state, auto_renew=auto_renew, expires=end)

    assert report(client, account).status_code == 204

    found = row(engine)
    assert found.status == status
    assert abs(found.period_end - end) < timedelta(milliseconds=1)
    body = plan(client, account)
    assert (body["plan"], body["google_renewing"]) == (shown, renewing)
    if state == google_events.IN_GRACE_PERIOD:
        # Premium ends with the grace period, not three days into it.
        assert body["renews_at"][:19] == end.isoformat()[:19]
    if state == google_events.CANCELED:
        assert body["status"] == "canceling"


def test_an_expired_one_is_not_acknowledged(client, fake, account):
    fake.add(TOKEN, account.id, state=google_events.EXPIRED)
    assert report(client, account).status_code == 204
    assert fake.called("acknowledge") == []


def test_a_purchase_naming_another_account_is_refused_unacknowledged(
    client, fake, account, make_account, engine, caplog
):
    other = make_account()
    fake.add(TOKEN, other.id)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = report(client, account)

    refused(response, 409, "other_account")
    assert rows(engine) == []
    assert fake.called("acknowledge") == []
    assert f"purchase {ORDER} names another account ({other.id})" in caplog.text


def test_a_purchase_naming_no_account_and_nothing_stored_is_refused(
    client, fake, account, engine
):
    fake.add(TOKEN, None)
    refused(report(client, account), 409, "other_account")
    assert rows(engine) == []


def test_an_account_id_naming_no_account_falls_back_to_the_stored_row(
    client, fake, account, engine
):
    """D6, the account order: the id first only when it names an existing
    account; then the stored row's."""
    add_row(engine, account.id, TOKEN)
    fake.add(TOKEN, uuid.uuid4())

    assert report(client, account).status_code == 204
    assert row(engine).user_id == account.id


def test_the_account_id_wins_over_the_stored_row(
    client, fake, account, make_account, engine
):
    other = make_account()
    add_row(engine, other.id, TOKEN)
    fake.add(TOKEN, account.id)

    assert report(client, account).status_code == 204
    assert row(engine).user_id == account.id


def test_a_play_store_resubscription_is_the_expired_ones_account(
    client, fake, account, make_account, engine
):
    """Review R1-1: a resubscription made in the Play Store after expiry
    carries no account id, only the expired purchase's token."""
    add_row(engine, account.id, "old-token")
    fake.add(TOKEN, None, expired_token="old-token")

    assert report(client, account).status_code == 204
    assert {(found.external_id, found.user_id) for found in rows(engine)} == {
        ("old-token", account.id),
        (TOKEN, account.id),
    }


def test_a_play_store_resubscription_of_another_account_is_refused(
    client, fake, account, make_account, engine
):
    other = make_account()
    add_row(engine, other.id, "old-token")
    fake.add(TOKEN, None, expired_token="old-token")

    refused(report(client, account), 409, "other_account")
    assert fake.called("acknowledge") == []


def test_a_replacing_token_ends_the_one_it_replaces(client, fake, account, engine):
    """A re-signup gets a new token linked to the old one: Google reads,
    acknowledges and cancels by the new one only, and the old row ends."""
    add_row(
        engine,
        account.id,
        "old-token",
        status="active",
        period_end=sessions.utc_now() + timedelta(days=20),
        cancel_at_period_end=False,
    )
    fake.add(TOKEN, None, linked="old-token")

    assert report(client, account).status_code == 204

    found = {entry.external_id: entry for entry in rows(engine)}
    assert (found["old-token"].status, found["old-token"].cancel_at_period_end) == (
        "ended",
        True,
    )
    assert (found[TOKEN].status, found[TOKEN].user_id) == ("active", account.id)
    assert google_renewing_tokens(engine, account.id) == [TOKEN]


def google_renewing_tokens(engine, user_id):
    with Session(engine) as db:
        return google_events.renewing(db, user_id)


def test_another_product_is_refused(client, fake, account, engine):
    fake.add(TOKEN, account.id, product="example.other")
    refused(report(client, account), 409, "other_product")
    assert rows(engine) == []
    assert fake.called("acknowledge") == []


@pytest.mark.parametrize("token", ["has space", "slash/../x", "x" * 2049, "é", "a\nb"])
def test_a_token_that_is_no_token_is_refused_unasked(client, fake, account, token):
    response = report(client, account, token)
    if len(token) > 2048:
        assert response.status_code == 422
    else:
        refused(response, 400, "invalid_purchase")
    assert fake.calls == []


@pytest.mark.parametrize("body", [{}, {"purchase_token": ""}, {"x": 1}])
def test_a_malformed_body_is_422(client, account, body):
    assert client.post(ROUTE, json=body, headers=account.headers).status_code == 422


def test_an_oversized_token_is_422_and_not_quoted(client, account):
    big = "y" * 3000
    response = report(client, account, big)
    assert response.status_code == 422
    assert "yyyy" not in response.text


def test_an_unknown_purchase_is_refused(client, fake, account, engine, caplog):
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        refused(report(client, account), 409, "unknown_purchase")
    assert rows(engine) == []
    assert "a reported purchase is unknown to Google" in caplog.text


def test_google_failing_writes_nothing_and_retrying_works(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id)
    fake.failures["subscription"] = GoogleUnavailable()

    refused(report(client, account), 502, "billing_unavailable")
    assert rows(engine) == []

    del fake.failures["subscription"]
    assert report(client, account).status_code == 204
    assert row(engine).status == "active"


def test_a_failed_acknowledgement_writes_nothing_and_retrying_works(
    client, fake, account, engine, caplog
):
    fake.add(TOKEN, account.id)
    fake.failures["acknowledge"] = GoogleUnavailable()

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        refused(report(client, account), 502, "billing_unavailable")
    assert rows(engine) == []
    assert f"purchase {ORDER} could not be acknowledged" in caplog.text

    del fake.failures["acknowledge"]
    assert report(client, account).status_code == 204
    assert row(engine).status == "active"
    assert fake.purchases[TOKEN]["acknowledgementState"] == ACKNOWLEDGED


def test_an_acknowledgement_refused_once_acknowledged_meanwhile_is_fine(
    client, fake, account, engine
):
    """Two reports at once: the second's call fails, yet Google holds the
    purchase acknowledged."""
    fake.add(TOKEN, account.id)

    def acknowledged_meanwhile(name):
        if name == "acknowledge":
            fake.purchases[TOKEN]["acknowledgementState"] = ACKNOWLEDGED
            raise MissingAtGoogle()

    fake.on_call = acknowledged_meanwhile

    assert report(client, account).status_code == 204
    assert row(engine).status == "active"


def test_an_unreadable_answer_is_unavailable(client, fake, account, engine, caplog):
    fake.add(TOKEN, account.id, state="SUBSCRIPTION_STATE_UNSPECIFIED")
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        refused(report(client, account), 502, "billing_unavailable")
    assert rows(engine) == []
    assert fake.called("acknowledge") == []
    assert f"purchase {ORDER} could not be read" in caplog.text


def test_a_repeated_report_keeps_one_row_and_the_latest_state(
    client, fake, account, engine
):
    fake.add(TOKEN, account.id)
    assert report(client, account).status_code == 204
    fake.add(
        TOKEN,
        account.id,
        state=google_events.CANCELED,
        auto_renew=False,
        acknowledged=True,
    )

    assert report(client, account).status_code == 204

    found = row(engine)
    assert (found.status, found.cancel_at_period_end) == ("active", True)
    assert plan(client, account)["status"] == "canceling"


def test_premium_from_stripe_still_records_the_purchase(client, fake, account, engine):
    with Session(engine) as db, db.begin():
        db.add(
            Entitlement(
                user_id=account.id,
                source="stripe",
                external_id="sub_1",
                status="active",
                period_end=sessions.utc_now() + timedelta(days=30),
                cancel_at_period_end=False,
                read_at=sessions.utc_now(),
            )
        )
    fake.add(TOKEN, account.id)

    assert report(client, account).status_code == 204
    assert {found.source for found in rows(engine)} == {"stripe", "google"}


def test_a_long_token_is_stored_whole(client, fake, account, engine):
    """Review R1-5: longer than the former 255 characters."""
    token = "t" * 600
    fake.add(token, account.id)
    assert report(client, account, token).status_code == 204
    assert row(engine).external_id == token


# D6: test purchases.


def test_dev_and_val_accept_a_test_purchase(make_google_client, account, engine):
    for env in ("dev", "validation"):
        client = make_google_client(app_env=env)
        fake = client.app.state.google_gateway
        fake.add(TOKEN, account.id, test=True)
        assert report(client, account).status_code == 204
    assert row(engine).status == "active"


@pytest.mark.parametrize("env", ["dev", "validation"])
def test_val_refuses_a_real_purchase_unacknowledged(
    make_google_client, account, engine, caplog, env
):
    """VAL's data is wiped at each seed: Google refunds what is left
    unacknowledged (owner's instruction, 2026-11-11)."""
    client = make_google_client(app_env=env)
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, test=False)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = report(client, account)

    refused(response, 409, "real_refused")
    assert rows(engine) == []
    assert fake.called("acknowledge") == []
    assert f"purchase {ORDER} refused for account {account.id}" in caplog.text


def test_production_accepts_a_real_purchase(make_google_client, account, engine):
    client = make_google_client(app_env="production")
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, test=False)

    assert report(client, account).status_code == 204
    assert row(engine).status == "active"
    assert fake.called("acknowledge") == [(TOKEN,)]


def test_production_refuses_a_test_purchase_from_an_account_not_listed(
    make_google_client, account, make_account, engine
):
    listed = make_account()
    client = make_google_client(
        app_env="production", google_play_test_account_ids=str(listed.id)
    )
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, test=True)

    refused(report(client, account), 409, "test_refused")
    assert rows(engine) == []
    assert fake.called("acknowledge") == []


def test_production_accepts_a_test_purchase_from_a_listed_account(
    make_google_client, account, engine
):
    client = make_google_client(
        app_env="production",
        google_play_test_account_ids=f"not-an-id, {account.id}",
    )
    fake = client.app.state.google_gateway
    fake.add(TOKEN, account.id, test=True)

    assert report(client, account).status_code == 204
    assert row(engine).user_id == account.id


def test_no_token_in_the_log(client, fake, account, make_account, caplog):
    other = make_account()
    fake.add(TOKEN, other.id)
    with caplog.at_level(logging.DEBUG):
        report(client, account)
        report(client, account, "unknown-token")
        fake.add(TOKEN, account.id, product="example.other")
        report(client, account)
    assert TOKEN not in caplog.text
    assert "unknown-token" not in caplog.text


def test_the_offer_names_the_product(client, make_client, account):
    assert plan(client, account)["google_offer"] == {"product_id": PRODUCT_ID}
    assert plan(make_client(), account)["google_offer"] is None
