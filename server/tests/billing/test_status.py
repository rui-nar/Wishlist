"""`GET /api/billing` (premium plan D11), the start-up log (D16)."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing.models import BillingCustomer, Entitlement

NOW = sessions.utc_now()
FREE_LIMITS = {"max_lists": 1, "max_gifts_per_list": 20}


@pytest.fixture
def client(make_client, billing_on):
    client = make_client(**billing_on)
    client.app.state.clock = lambda: NOW
    return client


def add_entitlement(engine, user_id, **fields):
    values = {
        "user_id": user_id,
        "source": "stripe",
        "external_id": f"sub_{uuid.uuid4().hex}",
        "status": "active",
        "period_end": NOW + timedelta(days=100),
        "cancel_at_period_end": False,
        "read_at": NOW,
    } | fields
    with Session(engine) as db, db.begin():
        db.add(Entitlement(**values))


def add_customer(engine, user_id):
    with Session(engine) as db, db.begin():
        db.add(BillingCustomer(user_id=user_id, source="stripe", customer_id="cus_1"))


def status_of(client, account):
    response = client.get("/api/billing", headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_free_with_an_offer_and_limits(client, make_account):
    body = status_of(client, make_account())
    assert body == {
        "plan": "free",
        "source": None,
        "status": None,
        "renews_at": None,
        "ends_at": None,
        "limits": FREE_LIMITS,
        "enforced": True,
        "offer": {"amount": "10.00", "currency": "EUR", "interval": "year"},
        "can_manage": False,
        "legal": {"terms_url": None, "privacy_url": None, "withdrawal_url": None},
    }


def test_premium_has_no_limits_and_a_renewal_date(client, make_account, engine):
    ada = make_account()
    add_entitlement(engine, ada.id)
    body = status_of(client, ada)
    assert (body["plan"], body["status"]) == ("premium", "active")
    assert body["limits"] == {"max_lists": None, "max_gifts_per_list": None}
    assert body["renews_at"] is not None
    assert body["ends_at"] is None
    assert body["source"] == "stripe"


def test_past_due_keeps_premium(client, make_account, engine):
    ada = make_account()
    add_entitlement(engine, ada.id, status="past_due")
    body = status_of(client, ada)
    assert (body["plan"], body["status"]) == ("premium", "past_due")


def test_canceling_shows_an_end_date(client, make_account, engine):
    ada = make_account()
    add_entitlement(engine, ada.id, cancel_at_period_end=True)
    body = status_of(client, ada)
    assert (body["plan"], body["status"]) == ("premium", "canceling")
    assert body["renews_at"] is None
    assert body["ends_at"] is not None


def test_a_lapsed_row_logs_the_grace_warning(client, make_account, engine, caplog):
    ada = make_account()
    add_entitlement(engine, ada.id, period_end=NOW - timedelta(days=4))
    with caplog.at_level(logging.WARNING, logger="app.billing.entitlements"):
        assert status_of(client, ada)["plan"] == "free"
    assert "entitlement past its grace" in caplog.text


def test_unset_means_no_offer_and_no_enforcement(make_client, make_account):
    body = status_of(make_client(), make_account())
    assert body["offer"] is None
    assert body["enforced"] is False
    assert body["limits"] == FREE_LIMITS
    assert body["can_manage"] is False


def test_the_offer_withdrawn_leaves_the_gateway_manageable(
    make_client, billing_on, make_account, engine
):
    values = billing_on | {"stripe_price_id": ""}
    client = make_client(**values)
    ada = make_account()
    add_customer(engine, ada.id)
    body = status_of(client, ada)
    assert body["offer"] is None
    assert body["enforced"] is False
    assert body["can_manage"] is True


def test_enforced_only_when_selling(make_client, billing_on, make_account):
    asked_without_price = make_client(**billing_on | {"billing_price_amount": ""})
    assert status_of(asked_without_price, make_account())["enforced"] is False


def test_can_manage_needs_a_public_base_url(
    make_client, billing_on, make_account, engine
):
    client = make_client(**billing_on | {"public_base_url": ""})
    ada = make_account()
    add_customer(engine, ada.id)
    assert status_of(client, ada)["can_manage"] is False


def test_the_legal_urls(make_client, billing_on, make_account):
    client = make_client(
        **billing_on
        | {
            "legal_terms_url": "https://x.test/terms",
            "legal_privacy_url": "https://x.test/privacy",
            "legal_withdrawal_url": "https://x.test/withdrawal",
        }
    )
    assert status_of(client, make_account())["legal"] == {
        "terms_url": "https://x.test/terms",
        "privacy_url": "https://x.test/privacy",
        "withdrawal_url": "https://x.test/withdrawal",
    }


def test_signed_out_is_refused(client):
    assert client.get("/api/billing").status_code == 401


def test_the_start_log_names_what_is_missing_and_no_value(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        make_client(stripe_secret_key="sk_test_startup_key")
    assert "STRIPE_WEBHOOK_SECRET" in caplog.text
    assert "BILLING_PRICE_AMOUNT" in caplog.text
    assert "sk_test_startup_key" not in caplog.text


def test_no_start_log_when_nothing_is_asked_for(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        make_client()
    assert "billing" not in caplog.text
