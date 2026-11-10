"""`DELETE /api/me` stops the account's billing first (premium plan D15)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User
from app.billing.models import BillingCustomer, Entitlement
from app.billing.stripe_gateway import GatewayUnavailable, MissingAtStripe

LOGGER = "app.billing.closing"
TIMEOUT = 10


@pytest.fixture
def client(make_client, billing_on):
    return make_client(**billing_on)


@pytest.fixture
def fake(client):
    return client.app.state.stripe_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def delete_account(client, account):
    return client.delete("/api/me", headers=account.headers)


def add_customer(engine, user_id):
    with Session(engine) as db, db.begin():
        db.add(BillingCustomer(user_id=user_id, source="stripe", customer_id="cus_1"))


def add_purchase(engine, user_id, status="active", started_days_ago=100):
    now = sessions.utc_now()
    with Session(engine) as db, db.begin():
        db.add(
            Entitlement(
                user_id=user_id,
                source="stripe",
                external_id="sub_1",
                status=status,
                period_end=now + timedelta(days=30),
                cancel_at_period_end=False,
                started_at=now - timedelta(days=started_days_ago),
                read_at=now,
            )
        )


def count(engine, model, user_id):
    column = model.id if model is User else model.user_id
    with Session(engine) as db:
        return db.scalar(
            select(func.count()).select_from(model).where(column == user_id)
        )


def all_gone(engine, user_id):
    return not any(
        count(engine, model, user_id) for model in (User, BillingCustomer, Entitlement)
    )


def test_no_customer_no_call_to_stripe(client, fake, account, engine):
    assert delete_account(client, account).status_code == 204
    assert fake.calls == []
    assert all_gone(engine, account.id)


def test_a_billable_row_with_no_customer_is_cancelled_by_its_own_id_first(
    client, fake, account, engine
):
    add_purchase(engine, account.id)
    seen = []
    fake.on_call = lambda name: seen.append(count(engine, User, account.id))

    assert delete_account(client, account).status_code == 204

    assert fake.calls == [("cancel", ("sub_1",))]
    assert seen == [1]
    assert all_gone(engine, account.id)


def test_an_ended_row_with_no_customer_calls_no_one(client, fake, account, engine):
    add_purchase(engine, account.id, status="ended")

    assert delete_account(client, account).status_code == 204

    assert fake.calls == []
    assert all_gone(engine, account.id)


def test_a_failed_cancel_by_id_deletes_nothing_and_retrying_works(
    client, fake, account, engine
):
    add_purchase(engine, account.id)
    fake.failures["cancel"] = GatewayUnavailable()

    response = delete_account(client, account)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )
    assert count(engine, User, account.id) == 1
    assert count(engine, Entitlement, account.id) == 1

    del fake.failures["cancel"]
    assert delete_account(client, account).status_code == 204
    assert all_gone(engine, account.id)


def test_a_row_covered_by_cancel_all_gets_no_second_call(client, fake, account, engine):
    add_customer(engine, account.id)
    add_purchase(engine, account.id)

    assert delete_account(client, account).status_code == 204

    assert fake.calls == [("cancel_all", ("cus_1",))]


def late_purchase_errors(caplog):
    return [
        record
        for record in caplog.records
        if record.levelno == logging.ERROR
        and "recorded during its deletion" in record.getMessage()
    ]


@pytest.mark.parametrize(
    ("answer", "errors"),
    [([], 1), (["sub_1"], 0)],
    ids=["not cancelled", "cancelled"],
)
def test_a_row_recorded_during_the_stripe_call_is_reported(
    client, fake, account, engine, caplog, answer, errors
):
    # Review R6-1: a webhook recorded it after `stop_billing` read the rows.
    add_customer(engine, account.id)

    def cancel_all(customer_id):
        add_purchase(engine, account.id)
        return answer

    fake.cancel_all = cancel_all

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    assert len(late_purchase_errors(caplog)) == errors
    assert all_gone(engine, account.id)


def test_a_row_covered_by_cancel_all_is_not_reported(client, account, engine, caplog):
    add_customer(engine, account.id)
    add_purchase(engine, account.id)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    assert late_purchase_errors(caplog) == []


def test_a_customer_has_their_billing_stopped_before_the_rows_go(
    client, fake, account, engine
):
    add_customer(engine, account.id)
    add_purchase(engine, account.id)
    seen = []
    fake.on_call = lambda name: seen.append(count(engine, User, account.id))

    assert delete_account(client, account).status_code == 204

    assert seen == [1]
    assert all_gone(engine, account.id)


def test_the_stripe_customer_is_never_deleted(client, fake, account, engine):
    # `cancel_all` is the only call: it expires open sessions and cancels
    # subscriptions (test_stripe_gateway.py), and leaves the customer.
    add_customer(engine, account.id)
    assert delete_account(client, account).status_code == 204
    assert fake.calls == [("cancel_all", ("cus_1",))]


@pytest.mark.parametrize(
    "failure",
    [GatewayUnavailable(), MissingAtStripe()],
    ids=["unavailable", "missing"],
)
def test_stripe_failing_deletes_nothing_and_retrying_works(
    client, fake, account, engine, failure
):
    add_customer(engine, account.id)
    add_purchase(engine, account.id)
    fake.failures["cancel_all"] = failure

    response = delete_account(client, account)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )
    assert count(engine, User, account.id) == 1
    assert count(engine, Entitlement, account.id) == 1

    del fake.failures["cancel_all"]
    assert delete_account(client, account).status_code == 204
    assert all_gone(engine, account.id)
    assert len(fake.called("cancel_all")) == 2


def test_cancelled_at_stripe_with_the_offer_withdrawn(
    make_client, billing_on, account, engine
):
    client = make_client(
        **billing_on | {"stripe_price_id": "", "billing_price_amount": ""}
    )
    fake = client.app.state.stripe_gateway
    add_customer(engine, account.id)
    add_purchase(engine, account.id)

    assert delete_account(client, account).status_code == 204

    assert fake.called("cancel_all") == [("cus_1",)]
    assert all_gone(engine, account.id)


@pytest.mark.parametrize("status", ["active", "past_due", "incomplete"])
def test_409_with_no_gateway_and_a_row_that_can_bill(
    make_client, account, engine, caplog, status
):
    client = make_client()
    add_customer(engine, account.id)
    add_purchase(engine, account.id, status=status)

    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = delete_account(client, account)

    assert (response.status_code, response.json()["code"]) == (
        409,
        "billing_unavailable",
    )
    assert str(account.id) in caplog.text
    assert count(engine, User, account.id) == 1
    assert count(engine, Entitlement, account.id) == 1


def test_no_gateway_and_an_ended_row_is_deleted(make_client, account, engine):
    client = make_client()
    add_customer(engine, account.id)
    add_purchase(engine, account.id, status="ended")

    assert delete_account(client, account).status_code == 204
    assert all_gone(engine, account.id)


def test_no_gateway_and_no_purchase_is_deleted(make_client, account, engine):
    assert delete_account(make_client(), account).status_code == 204
    assert all_gone(engine, account.id)


def test_a_repeated_call_is_not_signed_in(client, account, engine):
    add_customer(engine, account.id)
    assert delete_account(client, account).status_code == 204

    response = delete_account(client, account)

    assert (response.status_code, response.json()) == (
        401,
        {"detail": "Not signed in"},
    )


@pytest.mark.parametrize(
    ("days", "warned"), [(13, True), (15, False)], ids=["inside", "after"]
)
def test_a_warning_inside_the_withdrawal_period(
    client, account, engine, caplog, days, warned
):
    add_customer(engine, account.id)
    add_purchase(engine, account.id, started_days_ago=days)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    assert ("sub_1" in caplog.text) is warned


def test_a_warning_for_a_cancelled_subscription_with_no_row_yet(
    client, fake, account, engine, caplog
):
    # Bought a moment ago, its event still on its way: the start is unknown.
    add_customer(engine, account.id)
    fake.cancel_all = lambda customer_id: ["sub_new"]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    assert "sub_new" in caplog.text


def test_the_warning_survives_a_failed_first_attempt(
    client, fake, account, engine, caplog
):
    # The first attempt cancelled at Stripe and failed later, so the retry's
    # `cancel_all` answers nothing: the row still names the subscription.
    add_customer(engine, account.id)
    add_purchase(engine, account.id, started_days_ago=1)
    fake.failures["cancel_all"] = GatewayUnavailable()
    assert delete_account(client, account).status_code == 502
    del fake.failures["cancel_all"]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        assert delete_account(client, account).status_code == 204

    assert "sub_1" in caplog.text


@pytest.mark.parametrize("stored", [True, False], ids=["cancel_all", "cancel by id"])
def test_a_concurrent_request_does_not_wait_during_the_stripe_call(
    client, fake, account, engine, stored
):
    if stored:
        add_customer(engine, account.id)
    else:
        add_purchase(engine, account.id)
    reached = threading.Event()
    proceed = threading.Event()

    def hold(name):
        reached.set()
        assert proceed.wait(TIMEOUT)

    fake.on_call = hold
    with ThreadPoolExecutor(max_workers=2) as pool:
        deleting = pool.submit(delete_account, client, account)
        try:
            assert reached.wait(TIMEOUT)
            # `FOR KEY SHARE` on the user: it would wait on a `FOR UPDATE`.
            asking = pool.submit(client.get, "/api/me", headers=account.headers)
            assert asking.result(timeout=TIMEOUT).status_code == 200
        finally:
            proceed.set()
        assert deleting.result(timeout=TIMEOUT).status_code == 204

    assert all_gone(engine, account.id)


def test_a_sign_out_during_the_stripe_call_does_not_stop_the_deletion(
    client, fake, account, engine
):
    # Stripe has been told by then: the account must not stay.
    add_customer(engine, account.id)

    def sign_out(name):
        signed_out = client.post("/api/auth/sign-out", headers=account.headers)
        assert signed_out.status_code == 204

    fake.on_call = sign_out

    assert delete_account(client, account).status_code == 204
    assert all_gone(engine, account.id)
