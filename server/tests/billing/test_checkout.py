"""`POST /api/billing/checkout` (premium plan D11, D12, D17)."""

import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User
from app.billing.models import BillingCustomer, Entitlement
from app.billing.stripe_gateway import (
    GatewayUnavailable,
    MissingAtStripe,
    TermsUrlMissing,
    checkout_params,
)

LOGGER = "app.billing.router"
TIMEOUT = 10
NOW = sessions.utc_now()
BASE = "https://shushgift.example.test"


@pytest.fixture
def client(make_client, billing_on):
    client = make_client(**billing_on)
    client.app.state.clock = lambda: NOW
    return client


@pytest.fixture
def fake(client):
    return client.app.state.stripe_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def post(client, account):
    return client.post("/api/billing/checkout", headers=account.headers)


def customers(engine, user_id):
    with Session(engine) as db:
        return db.scalars(
            select(BillingCustomer.customer_id).where(
                BillingCustomer.user_id == user_id
            )
        ).all()


def set_language(engine, user_id, language):
    with Session(engine) as db, db.begin():
        db.get_one(User, user_id).language = language


def make_premium(engine, user_id):
    with Session(engine) as db, db.begin():
        db.add(
            Entitlement(
                user_id=user_id,
                source="apple",
                external_id="ext_1",
                status="active",
                period_end=NOW + timedelta(days=30),
                cancel_at_period_end=False,
                read_at=NOW,
            )
        )


def test_404_with_nothing_set(make_client, account):
    assert post(make_client(), account).status_code == 404


def test_404_with_the_offer_withdrawn(make_client, billing_on, account):
    client = make_client(**billing_on | {"stripe_price_id": ""})
    assert post(client, account).status_code == 404


def test_the_url_and_d12s_parameters(client, fake, account, engine):
    response = post(client, account)
    assert response.status_code == 200, response.text
    assert response.json() == {"url": "https://checkout.stripe.test/session"}
    order = fake.called("checkout")[0][0]
    user_id = str(account.id)
    customer_id = f"cus_{account.id.hex}"
    assert checkout_params(order) == {
        "mode": "subscription",
        "line_items": [{"price": "price_placeholder", "quantity": 1}],
        "customer": customer_id,
        "client_reference_id": user_id,
        "subscription_data": {"metadata": {"user_id": user_id, "app": "wishlist"}},
        "metadata": {"terms_version": "test-placeholder"},
        "locale": "en",
        "consent_collection": {"terms_of_service": "required"},
        "custom_text": {
            "terms_of_service_acceptance": {
                "message": (
                    "[TEST ONLY - placeholder, not legal text] I accept the terms of"
                    " this test."
                )
            }
        },
        "success_url": f"{BASE}/account/plan?checkout=success",
        "cancel_url": f"{BASE}/account/plan?checkout=cancelled",
    }
    assert customers(engine, account.id) == [customer_id]


def test_consent_text_and_locale_follow_the_users_language(
    make_client, billing_on, account, engine
):
    client = make_client(
        **billing_on
        | {
            "billing_consent_text_en": "Hello",
            "billing_consent_text_fr": "Bonjour",
            "billing_terms_version": "v1",
        }
    )
    fake = client.app.state.stripe_gateway
    set_language(engine, account.id, "fr")
    assert post(client, account).status_code == 200
    order = fake.called("checkout")[0][0]
    assert order.consent_text == "Bonjour"
    assert order.locale == "fr"
    assert order.terms_version == "v1"


def test_the_test_only_consent_starts_with_the_placeholder_mark(client, fake, account):
    post(client, account)
    assert fake.called("checkout")[0][0].consent_text.startswith(
        "[TEST ONLY - placeholder, not legal text]"
    )


def test_a_set_text_replaces_the_placeholder_language_by_language(
    make_client, billing_on, account
):
    client = make_client(**billing_on | {"billing_consent_text_en": "Real text"})
    fake = client.app.state.stripe_gateway
    post(client, account)
    assert fake.called("checkout")[0][0].consent_text == "Real text"


def test_production_sells_nothing_without_the_owners_texts(
    make_client, billing_on, account
):
    client = make_client(
        **billing_on | {"app_env": "production", "stripe_secret_key": "sk_live_x"}
    )
    assert post(client, account).status_code == 404


def test_tax_on_and_off(make_client, billing_on, account):
    off = make_client(**billing_on)
    post(off, account)
    assert off.app.state.stripe_gateway.called("checkout")[0][0].automatic_tax is False

    on = make_client(**billing_on | {"stripe_automatic_tax": True})
    post(on, account)
    assert on.app.state.stripe_gateway.called("checkout")[0][0].automatic_tax is True


def test_409_when_already_premium_from_any_source(client, fake, account, engine):
    make_premium(engine, account.id)
    response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (409, "already_premium")
    assert fake.called("checkout") == []


@pytest.mark.parametrize(
    "price",
    [
        {"active": False},
        {"interval": "month"},
        {"interval_count": 2},
        {"tax_behavior": "exclusive"},
        {"tax_behavior": None},
        {"unit_amount": 999},
        {"unit_amount": None},
        {"currency": "usd"},
    ],
    ids=str,
)
def test_503_when_the_price_at_stripe_does_not_match(
    client, fake, account, caplog, price
):
    fake.price_answer = replace(fake.price_answer, **price)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (
        503,
        "billing_misconfigured",
    )
    assert "does not match" in caplog.text
    assert fake.called("checkout") == []


@pytest.mark.parametrize(
    ("price", "variable"),
    [
        ({"interval": "month"}, "STRIPE_PRICE_ID"),
        ({"unit_amount": 999}, "BILLING_PRICE_AMOUNT"),
        ({"currency": "usd"}, "BILLING_PRICE_CURRENCY"),
    ],
)
def test_the_error_names_the_variable(client, fake, account, caplog, price, variable):
    fake.price_answer = replace(fake.price_answer, **price)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        post(client, account)
    assert variable in caplog.text


def test_503_when_the_price_id_does_not_exist(client, fake, account, caplog):
    fake.failures["price"] = MissingAtStripe()
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        assert post(client, account).status_code == 503
    assert "STRIPE_PRICE_ID" in caplog.text


def test_the_customer_is_reused(client, fake, account, engine):
    with Session(engine) as db, db.begin():
        db.add(
            BillingCustomer(user_id=account.id, source="stripe", customer_id="cus_old")
        )
    assert post(client, account).status_code == 200
    assert fake.called("ensure_customer") == []
    assert fake.called("checkout")[0][0].customer_id == "cus_old"
    assert customers(engine, account.id) == ["cus_old"]


def test_the_customer_is_created_with_the_users_email_and_name(
    client, fake, account, engine
):
    with Session(engine) as db:
        user = db.get_one(User, account.id)
        email, name = user.email, user.display_name
    post(client, account)
    assert fake.called("ensure_customer") == [(account.id, email, name)]


def test_a_customer_under_two_concurrent_checkouts_is_one_row(
    client, fake, account, engine
):
    start = threading.Barrier(2, timeout=TIMEOUT)

    def both_at_stripe(name):
        if name == "ensure_customer":
            start.wait()

    fake.on_call = both_at_stripe
    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.map(lambda _: post(client, account), range(2))

    assert (first.status_code, second.status_code) == (200, 200)
    assert len(fake.called("ensure_customer")) == 2
    assert customers(engine, account.id) == [f"cus_{account.id.hex}"]


def test_open_sessions_are_expired_before_the_new_one(client, fake, account):
    post(client, account)
    names = [name for name, _ in fake.calls]
    assert names.index("expire_open_sessions") < names.index("checkout")
    assert fake.called("expire_open_sessions") == [(f"cus_{account.id.hex}",)]


@pytest.mark.parametrize("stage", ["price", "expire_open_sessions", "checkout"])
def test_502_when_stripe_fails(client, fake, account, stage):
    fake.failures[stage] = GatewayUnavailable()
    response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )


def test_503_when_stripe_blames_the_terms_url(client, fake, account, caplog):
    fake.failures["checkout"] = TermsUrlMissing()
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (
        503,
        "billing_misconfigured",
    )
    assert "terms of service URL" in caplog.text


def test_no_lock_is_held_during_a_stripe_call(client, fake, account):
    reached = threading.Event()
    release = threading.Event()

    def hold_in_checkout(name):
        if name == "checkout":
            reached.set()
            assert release.wait(TIMEOUT)

    fake.on_call = hold_in_checkout
    with ThreadPoolExecutor(max_workers=1) as pool:
        running = pool.submit(post, client, account)
        assert reached.wait(TIMEOUT)
        # The deletion would block on any row lock of the user.
        deleted = client.delete("/api/me", headers=account.headers)
        release.set()
        response = running.result(timeout=TIMEOUT)

    assert deleted.status_code == 204
    assert response.status_code == 401


def test_signed_out_is_refused(client):
    assert client.post("/api/billing/checkout").status_code == 401
