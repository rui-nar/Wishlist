"""Apple's subscriptions into facts (Apple IAP plan D3, D5): pure, from
payloads already verified."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apple_fakes import apple_ms, renewal_claims, transaction_claims

from app.billing import apple_events
from app.billing.apple_events import AppleSubscription

USER = uuid.UUID("7e3fb20b-4cdb-47cc-936d-99d65f608138")
EXPIRES = datetime(2027, 11, 10, 12, tzinfo=UTC)
GRACE_END = EXPIRES + timedelta(days=16)
STARTED = datetime(2026, 11, 10, 12, tzinfo=UTC)


def subscription(status, auto_renew=1, grace=None, **transaction):
    claims = (
        transaction_claims("2000000001", USER, expires=EXPIRES, started=STARTED)
        | transaction
    )
    return AppleSubscription(
        status, claims, renewal_claims("2000000001", auto_renew=auto_renew, grace=grace)
    )


# D5's table: Apple's status -> (our status, period_end, Apple may charge).
CASES = {
    "active": (1, "active", EXPIRES, True),
    "billing grace period": (4, "past_due", GRACE_END, True),
    "billing retry past the grace period": (3, "ended", EXPIRES, True),
    "expired": (2, "ended", EXPIRES, False),
    "revoked": (5, "ended", EXPIRES, False),
}


@pytest.mark.parametrize("case", CASES)
def test_each_status_of_d5(case):
    apple_status, status, period_end, charges = CASES[case]

    facts = apple_events.facts(subscription(apple_status, grace=GRACE_END), USER)

    assert facts is not None
    assert (facts.source, facts.external_id, facts.user_id) == (
        "apple",
        "2000000001",
        USER,
    )
    assert (facts.status, facts.period_end) == (status, period_end)
    assert facts.started_at == STARTED
    # Auto-renew on: only what Apple can still charge is set to renew.
    assert facts.cancel_at_period_end is not charges


@pytest.mark.parametrize("apple_status", [1, 3, 4])
def test_auto_renew_off_is_set_to_stop(apple_status):
    facts = apple_events.facts(
        subscription(apple_status, auto_renew=0, grace=GRACE_END), USER
    )
    assert facts.cancel_at_period_end is True


def test_a_grace_period_without_its_date_ends_at_the_expiry():
    facts = apple_events.facts(subscription(4), USER)
    assert (facts.status, facts.period_end) == ("past_due", EXPIRES)


@pytest.mark.parametrize("apple_status", [None, 0, 6, "1"])
def test_an_undocumented_status_is_not_read(apple_status):
    assert apple_events.facts(subscription(apple_status), USER) is None


@pytest.mark.parametrize("original", [None, "", "12a", 12, "１２"])
def test_an_undocumented_id_is_not_read(original):
    assert (
        apple_events.facts(subscription(1, originalTransactionId=original), USER)
        is None
    )


def test_a_missing_date_is_none():
    facts = apple_events.facts(subscription(1, expiresDate="soon"), USER)
    assert facts.period_end is None


@pytest.mark.parametrize("value", [True, "1", 1.0])
def test_auto_renew_is_read_as_apple_writes_it(value):
    sub = subscription(1)
    sub.renewal["autoRenewStatus"] = value
    assert apple_events.facts(sub, USER).cancel_at_period_end is True


def test_the_token_is_the_account():
    assert apple_events.account_token({"appAccountToken": str(USER).upper()}) == USER
    assert apple_events.account_token({}) is None
    assert apple_events.account_token({"appAccountToken": "not an id"}) is None
    assert apple_events.account_token({"appAccountToken": 7}) is None


def test_the_pointer_of_a_notification():
    assert apple_events.signed_transaction({"data": {"signedTransactionInfo": "x"}})
    assert apple_events.signed_transaction({"summary": {}}) is None
    assert apple_events.signed_transaction({"data": "x"}) is None
    assert (
        apple_events.signed_transaction({"data": {"signedTransactionInfo": 1}}) is None
    )


def test_only_apples_two_environments():
    assert apple_events.environment({"environment": "Sandbox"}) == "Sandbox"
    assert apple_events.environment({"environment": "Production"}) == "Production"
    assert apple_events.environment({"environment": "Xcode"}) is None


def test_milliseconds():
    claims = transaction_claims("1", USER, expires=EXPIRES)
    assert claims["expiresDate"] == apple_ms(EXPIRES)
    sub = AppleSubscription(1, claims, {})
    assert apple_events.facts(sub, USER).period_end == EXPIRES
