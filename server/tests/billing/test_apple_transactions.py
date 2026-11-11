"""`POST /api/billing/apple/transactions` (Apple IAP plan D2, D3, D5, D6):
the reported transaction verified and checked, then only a pointer: what is
recorded is Apple's answer (the fake's)."""

import logging
import uuid
from datetime import timedelta

import pytest
from apple_fakes import PRODUCT_ID, apple_sign, build_apple_pki
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.billing.apple_gateway import AppleUnavailable
from app.billing.models import Entitlement

ROUTE = "/api/billing/apple/transactions"
LOGGER = "app.billing.router"
ORIGINAL = "2000000001"


@pytest.fixture
def client(make_apple_client):
    return make_apple_client()


@pytest.fixture
def fake(client):
    return client.app.state.apple_gateway


@pytest.fixture
def account(make_account):
    return make_account()


def report(client, account, signed):
    return client.post(
        ROUTE, json={"signed_transaction": signed}, headers=account.headers
    )


def rows(engine):
    with Session(engine) as db:
        return db.scalars(select(Entitlement)).all()


def row(engine):
    [found] = rows(engine)
    return found


def refused(response, status, code):
    assert (response.status_code, response.json()["code"]) == (status, code), (
        response.text
    )


def plan(client, account):
    return client.get("/api/billing", headers=account.headers).json()


def test_404_without_the_gateway(make_client, account):
    response = report(make_client(), account, "x")
    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})


def test_401_signed_out(client, fake):
    fake.add(ORIGINAL, uuid.uuid4())
    response = client.post(
        ROUTE, json={"signed_transaction": fake.signed_transaction(ORIGINAL)}
    )
    assert response.status_code == 401
    assert fake.calls == []


def test_a_purchase_grants_premium(client, fake, account, engine):
    end = sessions.utc_now() + timedelta(days=365)
    fake.add(ORIGINAL, account.id, expires=end)

    response = report(client, account, fake.signed_transaction(ORIGINAL))

    assert response.status_code == 204, response.text
    found = row(engine)
    assert (found.source, found.external_id, found.user_id, found.status) == (
        "apple",
        ORIGINAL,
        account.id,
        "active",
    )
    assert found.period_end == end.replace(microsecond=found.period_end.microsecond)
    # No consent record for Apple (D10).
    assert (found.terms_accepted_at, found.terms_version) == (None, None)
    status = plan(client, account)
    assert (status["plan"], status["source"], status["status"]) == (
        "premium",
        "apple",
        "active",
    )
    assert fake.calls == [("subscription", (ORIGINAL, "Sandbox"))]


# D5, through the report: Apple's status -> (status, plan, the date shown).
STATUSES = {
    "active": (1, "active", "premium"),
    "billing grace period": (4, "past_due", "premium"),
    "billing retry past the grace period": (3, "ended", "free"),
    "expired": (2, "ended", "free"),
    "revoked": (5, "ended", "free"),
}


@pytest.mark.parametrize("case", STATUSES)
def test_each_status_of_d5(client, fake, account, engine, case):
    apple_status, status, shown = STATUSES[case]
    now = sessions.utc_now()
    expires = now - timedelta(days=1) if apple_status != 1 else now + timedelta(30)
    grace = now + timedelta(days=15)
    fake.add(ORIGINAL, account.id, status=apple_status, expires=expires, grace=grace)

    assert report(client, account, fake.signed_transaction(ORIGINAL)).status_code == 204

    found = row(engine)
    assert found.status == status
    expected_end = grace if apple_status == 4 else expires
    assert abs(found.period_end - expected_end) < timedelta(milliseconds=1)
    body = plan(client, account)
    assert body["plan"] == shown
    if apple_status == 4:
        # Premium ends with the grace period, not three days into it.
        assert body["renews_at"][:19] == grace.isoformat()[:19]


def test_a_transaction_naming_another_account_is_refused_unasked(
    client, fake, account, make_account, engine, caplog
):
    other = make_account()
    fake.add(ORIGINAL, other.id)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = report(client, account, fake.signed_transaction(ORIGINAL))

    refused(response, 409, "other_account")
    assert rows(engine) == []
    assert fake.calls == []
    assert f"transaction {ORIGINAL} names another account ({other.id})" in caplog.text


def test_a_transaction_with_no_token_is_refused(client, fake, account, engine):
    fake.add(ORIGINAL, None)
    refused(
        report(client, account, fake.signed_transaction(ORIGINAL)), 409, "other_account"
    )
    assert rows(engine) == []


def test_a_subscription_now_another_accounts_is_refused(
    client, fake, account, make_account, engine
):
    """Restored by A, resubscribed since under B: Apple's latest transaction
    names B (D4)."""
    other = make_account()
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    fake.add(ORIGINAL, other.id)

    refused(report(client, account, signed), 409, "other_account")
    assert rows(engine) == []


def test_a_latest_transaction_with_no_token_keeps_the_reported_one(
    client, fake, account, engine
):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    fake.add(ORIGINAL, None)

    assert report(client, account, signed).status_code == 204
    assert row(engine).user_id == account.id


def test_a_latest_transaction_with_no_token_is_the_stored_rows_account(
    client, fake, account, make_account, engine, caplog
):
    """A reports its old transaction; the subscription is recorded for B and
    Apple's latest transaction carries no token: it stays B's, as a
    notification would leave it (D4, review R2-1)."""
    other = make_account()
    fake.add(ORIGINAL, account.id)
    old = fake.signed_transaction(ORIGINAL)
    fake.add(ORIGINAL, other.id)
    assert report(client, other, fake.signed_transaction(ORIGINAL)).status_code == 204
    fake.add(ORIGINAL, None)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = report(client, account, old)

    refused(response, 409, "other_account")
    assert row(engine).user_id == other.id
    assert f"transaction {ORIGINAL} names another account ({other.id})" in caplog.text


def test_another_product_is_refused(client, fake, account, engine):
    fake.add(ORIGINAL, account.id, product="example.other")
    refused(
        report(client, account, fake.signed_transaction(ORIGINAL)), 409, "other_product"
    )
    assert rows(engine) == []
    assert fake.calls == []


def test_a_purchase_that_is_no_subscription_is_refused(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL, type="Consumable")
    refused(report(client, account, signed), 409, "other_product")
    assert rows(engine) == []


def test_a_latest_transaction_of_another_product_is_refused(
    client, fake, account, engine
):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    fake.add(ORIGINAL, account.id, product="example.other")

    refused(report(client, account, signed), 409, "other_product")
    assert rows(engine) == []


def test_a_tampered_transaction_is_refused_with_nothing_written(
    client, fake, account, make_account, engine
):
    """The token of another account's purchase changed to this one's."""
    other = make_account()
    fake.add(ORIGINAL, other.id)
    header, payload, signature = fake.signed_transaction(ORIGINAL).split(".")
    mine = fake.signed_transaction(ORIGINAL, appAccountToken=str(account.id))
    forged = ".".join([header, mine.split(".")[1], signature])

    refused(report(client, account, forged), 400, "invalid_transaction")
    assert rows(engine) == []
    assert fake.calls == []


def test_a_transaction_signed_through_another_root_is_refused(
    client, fake, account, engine
):
    fake.add(ORIGINAL, account.id)
    claims = fake.subscriptions[ORIGINAL].transaction
    forged = apple_sign(build_apple_pki(), claims)

    refused(report(client, account, forged), 400, "invalid_transaction")
    assert rows(engine) == []
    assert fake.calls == []


@pytest.mark.parametrize("body", [{}, {"signed_transaction": ""}, {"x": 1}])
def test_a_malformed_body_is_422(client, account, body):
    response = client.post(ROUTE, json=body, headers=account.headers)
    assert response.status_code == 422


def test_an_oversized_transaction_is_422_and_not_quoted(client, account):
    big = "x" * (64 * 1024 + 1)
    response = client.post(
        ROUTE, json={"signed_transaction": big}, headers=account.headers
    )
    assert response.status_code == 422
    assert "xxxx" not in response.text


def test_an_unknown_transaction_is_refused(client, fake, account, engine, caplog):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    del fake.subscriptions[ORIGINAL]

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        refused(report(client, account, signed), 409, "unknown_transaction")
    assert rows(engine) == []
    assert f"transaction {ORIGINAL} is unknown to Apple" in caplog.text


def test_apple_failing_writes_nothing_and_retrying_works(client, fake, account, engine):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    fake.failures["subscription"] = AppleUnavailable()

    refused(report(client, account, signed), 502, "billing_unavailable")
    assert rows(engine) == []

    del fake.failures["subscription"]
    assert report(client, account, signed).status_code == 204
    assert row(engine).status == "active"


def test_an_unreadable_answer_is_unavailable(client, fake, account, engine, caplog):
    fake.add(ORIGINAL, account.id, status=9)
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        refused(
            report(client, account, fake.signed_transaction(ORIGINAL)),
            502,
            "billing_unavailable",
        )
    assert rows(engine) == []
    assert f"subscription {ORIGINAL} could not be read" in caplog.text


def test_a_repeated_report_keeps_one_row_and_the_latest_state(
    client, fake, account, engine
):
    fake.add(ORIGINAL, account.id)
    signed = fake.signed_transaction(ORIGINAL)
    assert report(client, account, signed).status_code == 204
    fake.add(ORIGINAL, account.id, auto_renew=0)

    assert report(client, account, signed).status_code == 204

    found = row(engine)
    assert (found.status, found.cancel_at_period_end) == ("active", True)
    assert plan(client, account)["status"] == "canceling"


def test_premium_from_stripe_still_records_the_purchase(client, fake, account, engine):
    """A purchase made is never dropped: the app keeps anyone from paying
    twice (D8), the server records what was paid."""
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
    fake.add(ORIGINAL, account.id)

    assert report(client, account, fake.signed_transaction(ORIGINAL)).status_code == 204
    assert {found.source for found in rows(engine)} == {"stripe", "apple"}


# D6: the environments.


def test_val_accepts_sandbox(make_apple_client, account, engine):
    client = make_apple_client(app_env="validation")
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id)

    assert report(client, account, fake.signed_transaction(ORIGINAL)).status_code == 204
    assert row(engine).status == "active"


def test_val_refuses_production(make_apple_client, account, engine):
    client = make_apple_client(app_env="validation")
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id, environment="Production")

    refused(
        report(client, account, fake.signed_transaction(ORIGINAL)),
        400,
        "invalid_transaction",
    )
    assert rows(engine) == []
    assert fake.calls == []


def test_production_accepts_production(make_apple_client, account, engine):
    client = make_apple_client(app_env="production")
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id, environment="Production")

    assert report(client, account, fake.signed_transaction(ORIGINAL)).status_code == 204
    assert row(engine).status == "active"
    assert fake.calls == [("subscription", (ORIGINAL, "Production"))]


def test_production_refuses_sandbox_from_an_account_not_listed(
    make_apple_client, account, make_account, engine, caplog
):
    listed = make_account()
    client = make_apple_client(
        app_env="production", apple_sandbox_account_ids=str(listed.id)
    )
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id)

    with caplog.at_level(logging.WARNING, logger=LOGGER):
        response = report(client, account, fake.signed_transaction(ORIGINAL))

    refused(response, 409, "sandbox_refused")
    assert rows(engine) == []
    assert fake.calls == []
    assert f"Sandbox transaction {ORIGINAL} refused" in caplog.text


def test_production_accepts_sandbox_from_a_listed_account(
    make_apple_client, account, engine
):
    client = make_apple_client(
        app_env="production",
        apple_sandbox_account_ids=f"not-an-id, {account.id}",
    )
    fake = client.app.state.apple_gateway
    fake.add(ORIGINAL, account.id)

    assert report(client, account, fake.signed_transaction(ORIGINAL)).status_code == 204
    assert row(engine).user_id == account.id


def test_no_signed_payload_in_the_log(client, fake, account, make_account, caplog):
    other = make_account()
    fake.add(ORIGINAL, other.id)
    signed = fake.signed_transaction(ORIGINAL)
    with caplog.at_level(logging.DEBUG):
        report(client, account, signed)
        report(client, account, signed[:-4] + "AAAA")
    assert signed.split(".")[1] not in caplog.text
    assert signed.split(".")[2][:20] not in caplog.text


def test_the_offer_names_the_product(client, make_client, account):
    assert plan(client, account)["apple_offer"] == {"product_id": PRODUCT_ID}
    assert plan(make_client(), account)["apple_offer"] is None
