"""Google Play's purchases into facts (Android release plan D6): pure, no
database."""

import base64
import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from google_fakes import ORDER, PRODUCT_ID, TOKEN, developer_notification, purchase

from app.billing import google_events
from app.billing.google_events import (
    CANCELED,
    EXPIRED,
    IN_GRACE_PERIOD,
    ON_HOLD,
    PAUSED,
    PENDING,
    PENDING_PURCHASE_CANCELED,
    STATE_ACTIVE,
)

USER = uuid.uuid4()
END = datetime(2027, 11, 11, 12, 30, 15, 123000, tzinfo=UTC)


def facts(answer, token=TOKEN):
    return google_events.facts(answer, token, USER, PRODUCT_ID)


# Play's state -> (status, cancel_at_period_end) with auto-renew as given.
MAPPING = {
    "active": (STATE_ACTIVE, True, "active", False),
    "active, auto-renew off": (STATE_ACTIVE, False, "active", True),
    "cancelled, still paid": (CANCELED, False, "active", True),
    "grace period": (IN_GRACE_PERIOD, True, "past_due", False),
    "on hold": (ON_HOLD, True, "ended", False),
    "paused": (PAUSED, True, "ended", False),
    "expired": (EXPIRED, False, "ended", True),
    "pending": (PENDING, True, "incomplete", False),
    "pending, cancelled": (PENDING_PURCHASE_CANCELED, False, "ended", True),
}


@pytest.mark.parametrize("case", MAPPING)
def test_the_mapping_of_d6(case):
    state, auto_renew, status, cancel = MAPPING[case]
    started = END - timedelta(days=365)
    found = facts(
        purchase(USER, state=state, auto_renew=auto_renew, expires=END, started=started)
    )
    assert found is not None
    assert (found.source, found.external_id, found.user_id) == ("google", TOKEN, USER)
    assert (found.status, found.cancel_at_period_end) == (status, cancel)
    assert found.period_end == END
    assert found.started_at == started


def test_an_undocumented_state_is_nothing_known():
    assert facts(purchase(USER, state="SUBSCRIPTION_STATE_UNSPECIFIED")) is None
    assert facts(purchase(USER, state="SOMETHING_NEW")) is None
    answer = purchase(USER)
    del answer["subscriptionState"]
    assert facts(answer) is None


def test_another_product_is_nothing_known():
    assert facts(purchase(USER, product="example.other")) is None


def test_a_bad_date_is_none():
    answer = purchase(USER)
    answer["lineItems"][0]["expiryTime"] = "tomorrow"
    answer["startTime"] = 12
    found = facts(answer)
    assert (found.period_end, found.started_at) == (None, None)


def test_nanoseconds_are_read():
    answer = purchase(USER)
    answer["lineItems"][0]["expiryTime"] = "2027-11-11T12:30:15.123456789Z"
    assert facts(answer).period_end == datetime(
        2027, 11, 11, 12, 30, 15, 123456, tzinfo=UTC
    )


def test_auto_renew_must_be_true_itself():
    answer = purchase(USER)
    answer["lineItems"][0]["autoRenewingPlan"]["autoRenewEnabled"] = "true"
    assert google_events.can_charge(answer, PRODUCT_ID) is False
    del answer["lineItems"][0]["autoRenewingPlan"]
    assert google_events.can_charge(answer, PRODUCT_ID) is False


def test_the_account_id():
    assert google_events.account_id(purchase(USER)) == USER
    assert google_events.account_id(purchase(None)) is None
    assert google_events.account_id(purchase("not-a-uuid")) is None


def test_test_purchases():
    assert google_events.is_test(purchase(USER, test=True))
    assert not google_events.is_test(purchase(USER, test=False))


@pytest.mark.parametrize(
    "state, acknowledged, needed",
    [
        (STATE_ACTIVE, False, True),
        (STATE_ACTIVE, True, False),
        (IN_GRACE_PERIOD, False, True),
        (CANCELED, False, True),
        (PENDING, False, False),
        (EXPIRED, False, False),
        (ON_HOLD, False, False),
    ],
)
def test_needs_acknowledgement(state, acknowledged, needed):
    answer = purchase(USER, state=state, acknowledged=acknowledged)
    assert google_events.needs_acknowledgement(answer) is needed


def test_linked_and_expired_tokens():
    answer = purchase(USER, linked="old.token", expired_token="older-token")
    assert google_events.linked_token(answer) == "old.token"
    assert google_events.expired_token(answer) == "older-token"
    assert google_events.linked_token(purchase(USER, linked="no token")) is None


def test_the_order_id_names_a_purchase_never_its_token():
    assert google_events.order_id(purchase(USER), PRODUCT_ID) == ORDER
    assert (
        google_events.order_id(purchase(USER, order=TOKEN), PRODUCT_ID)
        == "(no order id)"
    )


@pytest.mark.parametrize(
    "token, valid",
    [
        (TOKEN, True),
        ("a" * 2048, True),
        ("a" * 2049, False),
        ("", False),
        ("a b", False),
        ("a/b", False),
        ("é", False),
        (None, False),
        (12, False),
    ],
)
def test_is_token(token, valid):
    assert google_events.is_token(token) is valid


def encoded(value):
    data = base64.b64encode(json.dumps(value).encode()).decode()
    return json.dumps({"message": {"data": data}}).encode()


def test_a_push_carries_a_developer_notification():
    notification = developer_notification()
    decoded = google_events.developer_notification(encoded(notification))
    assert decoded == notification
    assert google_events.notification_token(decoded) == TOKEN
    assert google_events.notification_package(decoded) == "com.example.wishlist"


def test_a_voided_subscription_is_a_pointer():
    notification = developer_notification(kind="voided")
    assert google_events.notification_token(notification) == TOKEN
    assert google_events.notification_order(notification) == ORDER
    notification["voidedPurchaseNotification"]["productType"] = 2
    assert google_events.notification_token(notification) is None


def test_a_test_notification_points_at_nothing():
    assert google_events.notification_token(developer_notification(kind="test")) is None
