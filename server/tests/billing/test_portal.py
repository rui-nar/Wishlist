"""`POST /api/billing/portal` (premium plan D11, D14)."""

import pytest
from sqlalchemy.orm import Session

from app.billing.models import BillingCustomer
from app.billing.stripe_gateway import GatewayUnavailable

BASE = "https://wishlist.example.test"


@pytest.fixture
def client(make_client, billing_on):
    return make_client(**billing_on)


@pytest.fixture
def fake(client):
    return client.app.state.stripe_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def post(client, account):
    return client.post("/api/billing/portal", headers=account.headers)


def add_customer(engine, user_id):
    with Session(engine) as db, db.begin():
        db.add(BillingCustomer(user_id=user_id, source="stripe", customer_id="cus_1"))


def test_404_with_no_gateway(make_client, account):
    assert post(make_client(), account).status_code == 404


def test_404_without_a_public_base_url(make_client, billing_on, account, engine):
    client = make_client(**billing_on | {"public_base_url": ""})
    add_customer(engine, account.id)
    assert post(client, account).status_code == 404


def test_served_with_the_offer_withdrawn(make_client, billing_on, account, engine):
    client = make_client(
        **billing_on | {"stripe_price_id": "", "billing_price_amount": ""}
    )
    add_customer(engine, account.id)
    response = post(client, account)
    assert response.status_code == 200
    assert response.json() == {"url": "https://billing.stripe.test/portal"}


def test_409_without_a_customer(client, fake, account):
    response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (409, "no_subscription")
    assert fake.called("portal") == []


def test_the_return_url(client, fake, account, engine):
    add_customer(engine, account.id)
    assert post(client, account).status_code == 200
    assert fake.called("portal") == [("cus_1", f"{BASE}/account/plan")]


def test_502_when_stripe_fails(client, fake, account, engine):
    add_customer(engine, account.id)
    fake.failures["portal"] = GatewayUnavailable()
    response = post(client, account)
    assert (response.status_code, response.json()["code"]) == (
        502,
        "billing_unavailable",
    )


def test_signed_out_is_refused(client):
    assert client.post("/api/billing/portal").status_code == 401
