"""`POST /api/billing/webhook` (premium plan D13): signature first, the event
only a pointer, every state read back from Stripe (the fake)."""

import json
import logging
import time
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing.models import ACTIVE, BillingCustomer, Entitlement
from app.billing.stripe_gateway import GatewayUnavailable, MissingAtStripe

LOGGER = "app.billing.router"
UPDATED = "customer.subscription.updated"
CREATED = "customer.subscription.created"
DELETED = "customer.subscription.deleted"
COMPLETED = "checkout.session.completed"


@pytest.fixture
def client(make_client, billing_on):
    client = make_client(**billing_on)
    client.app.state.clock = sessions.utc_now
    return client


@pytest.fixture
def fake(client):
    return client.app.state.stripe_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def rows(engine):
    with Session(engine) as db:
        return db.scalars(select(Entitlement)).all()


def row(engine):
    found = rows(engine)
    assert len(found) == 1
    return found[0]


def post_raw(client, body, signature=None):
    headers = {"Stripe-Signature": signature} if signature else {}
    return client.post("/api/billing/webhook", content=body, headers=headers)


def test_404_with_no_gateway(make_client):
    assert post_raw(make_client(), b"{}").status_code == 404


def test_with_the_offer_withdrawn_events_are_still_recorded(
    make_client, billing_on, account, engine
):
    client = make_client(**billing_on | {"stripe_price_id": ""})
    fake = client.app.state.stripe_gateway
    fake.add_subscription("sub_1", account.id)

    assert fake.deliver(client, CREATED, {"id": "sub_1"}).status_code == 204
    first_end = row(engine).period_end

    fake.add_subscription(
        "sub_1", account.id, period_end=sessions.utc_now() + timedelta(days=800)
    )
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).period_end > first_end
    premium = client.get("/api/billing", headers=account.headers).json()
    assert premium["plan"] == "premium"
    assert premium["offer"] is None


def test_400_with_a_bad_signature(client, fake, engine, account):
    fake.add_subscription("sub_1", account.id)
    body = json.dumps({"type": UPDATED, "data": {"object": {"id": "sub_1"}}})
    wrong = fake.sign(body).replace("v1=", "v1=0")

    response = post_raw(client, body.encode(), wrong)

    assert (response.status_code, response.json()) == (
        400,
        {"detail": "Invalid webhook"},
    )
    assert rows(engine) == []
    assert fake.calls == []


def test_400_with_no_signature(client, fake, engine, account):
    fake.add_subscription("sub_1", account.id)
    body = json.dumps({"type": UPDATED, "data": {"object": {"id": "sub_1"}}})

    assert post_raw(client, body.encode()).status_code == 400
    assert rows(engine) == []
    assert fake.calls == []


def test_400_with_a_stale_signature(client, fake, engine, account):
    fake.add_subscription("sub_1", account.id)
    body = json.dumps({"type": UPDATED, "data": {"object": {"id": "sub_1"}}})
    stale = fake.sign(body, timestamp=int(time.time()) - 400)

    assert post_raw(client, body.encode(), stale).status_code == 400
    assert rows(engine) == []


def test_400_for_a_body_over_one_mebibyte(client, fake, engine):
    body = b"x" * (1024 * 1024 + 1)
    assert post_raw(client, body, fake.sign(body.decode())).status_code == 400
    assert rows(engine) == []


def test_an_unhandled_type_answers_204_and_does_nothing(client, fake, engine):
    response = fake.deliver(client, "invoice.paid", {"id": "in_1"})
    assert response.status_code == 204
    assert fake.called("subscription") == []
    assert rows(engine) == []


def test_a_deleted_before_an_updated_stays_ended(client, fake, account, engine):
    fake.add_subscription("sub_1", account.id, status="canceled")
    assert fake.deliver(client, DELETED, {"id": "sub_1"}).status_code == 204
    # A late `updated`: the state read is Stripe's, still cancelled.
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).status == "ended"


def test_a_created_read_as_active_grants_at_once(client, fake, account, engine):
    fake.add_subscription("sub_1", account.id, status="active")
    assert fake.deliver(client, CREATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).status == ACTIVE


def test_a_duplicate_leaves_one_row(client, fake, account, engine):
    fake.add_subscription("sub_1", account.id)
    for _ in range(2):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).status == ACTIVE


def test_a_failure_at_stripe_answers_502_then_a_redelivery_applies(
    client, fake, account, engine
):
    fake.add_subscription("sub_1", account.id)
    fake.failures["subscription"] = GatewayUnavailable()

    failed = fake.deliver(client, UPDATED, {"id": "sub_1"})
    assert (failed.status_code, failed.json()["code"]) == (502, "billing_unavailable")
    assert rows(engine) == []

    fake.failures.clear()
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).status == ACTIVE


def test_a_subscription_missing_at_stripe_is_a_retry(client, fake, engine):
    fake.failures["subscription"] = MissingAtStripe()
    assert fake.deliver(client, UPDATED, {"id": "sub_x"}).status_code == 502
    assert rows(engine) == []


def consent_event(fake, client, created):
    return fake.deliver(
        client,
        COMPLETED,
        {
            "subscription": "sub_1",
            "mode": "subscription",
            "consent": {"terms_of_service": "accepted"},
            "metadata": {"terms_version": "v7"},
        },
        created=created,
    )


def test_consent_recorded_once_on_a_completed_checkout(client, fake, account, engine):
    fake.add_subscription("sub_1", account.id)
    accepted = int(time.time()) - 60

    assert consent_event(fake, client, accepted).status_code == 204
    assert consent_event(fake, client, accepted + 500).status_code == 204

    written = row(engine)
    assert written.terms_version == "v7"
    assert written.terms_accepted_at == datetime.fromtimestamp(accepted, UTC)


def test_an_unknown_price_grants_with_a_warning(client, fake, account, engine, caplog):
    fake.add_subscription("sub_1", account.id, price="price_other")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).status == ACTIVE
    assert "another price" in caplog.text


def test_a_subscription_with_no_known_user_answers_204_with_no_row(
    client, fake, engine, caplog
):
    fake.add_subscription("sub_1", None, customer="cus_unknown")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert rows(engine) == []
    assert "no known user" in caplog.text


def test_the_customer_row_finds_the_user_without_metadata(
    client, fake, account, engine
):
    with Session(engine) as db, db.begin():
        db.add(
            BillingCustomer(user_id=account.id, source="stripe", customer_id="cus_x")
        )
    fake.add_subscription("sub_1", None, customer="cus_x")
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert row(engine).user_id == account.id


def test_a_status_stripe_does_not_document_is_logged_and_writes_nothing(
    client, fake, account, engine, caplog
):
    fake.add_subscription("sub_1", account.id, status="brand_new")
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert rows(engine) == []
    assert "could not be read" in caplog.text


def gone_user(engine, account):
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": account.id})


def add_ours(fake, account, **fields):
    """A subscription with the marker Wishlist's checkout writes."""
    fake.add_subscription("sub_1", account.id, **fields)["metadata"]["app"] = "wishlist"


def test_a_gone_users_running_subscription_is_cancelled(client, fake, account, engine):
    add_ours(fake, account)
    gone_user(engine, account)
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert fake.called("cancel") == [("sub_1",)]
    assert rows(engine) == []


def test_without_the_marker_a_uuid_with_no_user_is_never_cancelled(
    client, fake, account, engine, caplog
):
    fake.add_subscription("sub_1", account.id)
    gone_user(engine, account)
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert fake.called("cancel") == []
    assert rows(engine) == []
    assert "no known user" in caplog.text


def test_a_traxjourney_shaped_subscription_is_never_cancelled(
    client, fake, engine, caplog
):
    subscription = fake.add_subscription("sub_1", None, customer="cus_trax")
    subscription["metadata"] = {"user_info_id": "42", "plan": "tier_1"}
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert fake.called("cancel") == []
    assert rows(engine) == []
    assert "no known user" in caplog.text


@pytest.mark.parametrize("status", ["canceled", "incomplete_expired"])
def test_a_gone_users_finished_subscription_is_left(
    client, fake, account, engine, status
):
    add_ours(fake, account, status=status)
    gone_user(engine, account)
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert fake.called("cancel") == []


def test_a_gone_users_unpaid_subscription_is_cancelled_all_the_same(
    client, fake, account, engine
):
    # `ended` for premium, but Stripe can still resume it.
    add_ours(fake, account, status="unpaid")
    gone_user(engine, account)
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert fake.called("cancel") == [("sub_1",)]


def test_a_failed_cancellation_of_a_gone_user_is_retried(client, fake, account, engine):
    add_ours(fake, account)
    gone_user(engine, account)
    fake.failures["cancel"] = GatewayUnavailable()
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 502


def test_two_subscriptions_in_force_is_an_error(client, fake, account, engine, caplog):
    fake.add_subscription("sub_1", account.id)
    fake.add_subscription("sub_2", account.id)
    assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_2"}).status_code == 204
    assert len(rows(engine)) == 2
    assert "subscriptions in force" in caplog.text


def test_one_subscription_in_force_is_no_error(client, fake, account, caplog):
    fake.add_subscription("sub_1", account.id)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert fake.deliver(client, UPDATED, {"id": "sub_1"}).status_code == 204
    assert "subscriptions in force" not in caplog.text


def test_no_secret_email_or_body_in_any_log(
    client, fake, account, engine, caplog, billing_on
):
    with Session(engine) as db:
        email = db.scalar(
            text("SELECT email FROM users WHERE id = :id"), {"id": account.id}
        )
    fake.add_subscription("sub_1", account.id, price="price_other")
    fake.add_subscription("sub_2", account.id)
    body = {"id": "sub_1", "note": "a-body-word", "customer_email": email}
    with caplog.at_level(logging.DEBUG):
        fake.deliver(client, UPDATED, body)
        fake.deliver(client, UPDATED, {"id": "sub_2"})
        post_raw(client, b"not-a-json-body", "t=1,v1=sig-value")
        fake.failures["subscription"] = GatewayUnavailable()
        fake.deliver(client, UPDATED, {"id": "sub_1"})
    text_logged = "\n".join(record.getMessage() for record in caplog.records)
    for forbidden in (
        billing_on["stripe_secret_key"],
        billing_on["stripe_webhook_secret"],
        email,
        "a-body-word",
        "not-a-json-body",
        "sig-value",
    ):
        assert forbidden not in text_logged
