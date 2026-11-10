"""Stripe's objects into facts (premium plan D13 step 4): pure, no database."""

import uuid
from datetime import UTC, datetime

import pytest

from app.billing.models import ACTIVE, ENDED, INCOMPLETE, PAST_DUE
from app.billing.stripe_events import (
    customer_id,
    facts,
    is_finished,
    is_ours,
    metadata_user_id,
    pointer,
    price_id,
)

USER = uuid.uuid4()
END = 1_798_000_000
START = 1_700_000_000


def subscription(**fields):
    return {
        "id": "sub_1",
        "status": "active",
        "cancel_at_period_end": False,
        "cancel_at": None,
        "start_date": START,
        "items": {"data": [{"current_period_end": END, "price": {"id": "price_1"}}]},
    } | fields


@pytest.mark.parametrize(
    ("stripe_status", "expected"),
    [
        ("active", ACTIVE),
        ("trialing", ACTIVE),
        ("past_due", PAST_DUE),
        ("incomplete", INCOMPLETE),
        ("incomplete_expired", ENDED),
        ("canceled", ENDED),
        ("unpaid", ENDED),
        ("paused", ENDED),
    ],
)
def test_each_status_mapping(stripe_status, expected):
    result = facts(subscription(status=stripe_status), USER)
    assert result is not None
    assert result.status == expected


@pytest.mark.parametrize("status", ["nonsense", "", None, 3])
def test_a_status_stripe_does_not_document_gives_no_facts(status):
    assert facts(subscription(status=status), USER) is None


def test_the_period_end_on_the_items_since_api_2025_03_31():
    assert facts(subscription(), USER).period_end == datetime.fromtimestamp(END, UTC)


def test_the_period_end_on_the_subscription_before_it():
    sub = subscription(current_period_end=START, items={"data": []})
    assert facts(sub, USER).period_end == datetime.fromtimestamp(START, UTC)


def test_the_latest_period_end_of_several_items():
    sub = subscription(
        items={
            "data": [
                {"current_period_end": START},
                {"current_period_end": END},
            ]
        }
    )
    assert facts(sub, USER).period_end == datetime.fromtimestamp(END, UTC)


@pytest.mark.parametrize(
    "items", [None, {}, {"data": None}, {"data": []}, {"data": ["x"]}, "wrong"]
)
def test_no_period_end_when_stripe_gives_none(items):
    assert facts(subscription(items=items), USER).period_end is None


@pytest.mark.parametrize("value", ["1798000000", 1.5, True, None, 10**30])
def test_a_malformed_period_end_is_none(value):
    sub = subscription(items={"data": [{"current_period_end": value}]})
    assert facts(sub, USER).period_end is None


def test_cancel_at_period_end_and_cancel_at():
    assert facts(subscription(), USER).cancel_at_period_end is False
    assert (
        facts(subscription(cancel_at_period_end=True), USER).cancel_at_period_end
        is True
    )
    assert facts(subscription(cancel_at=END), USER).cancel_at_period_end is True
    assert facts(subscription(cancel_at="soon"), USER).cancel_at_period_end is False


def test_started_at_and_identity():
    result = facts(subscription(), USER)
    assert result.source == "stripe"
    assert result.external_id == "sub_1"
    assert result.user_id == USER
    assert result.started_at == datetime.fromtimestamp(START, UTC)


def test_no_id_gives_no_facts():
    assert facts(subscription(id=""), USER) is None
    assert facts(subscription(id=None), USER) is None


def test_finished_is_only_stripes_final_states():
    assert is_finished(subscription(status="canceled"))
    assert is_finished(subscription(status="incomplete_expired"))
    assert not is_finished(subscription(status="unpaid"))
    assert not is_finished(subscription(status="active"))


def test_only_our_marker_proves_a_subscription_ours():
    assert is_ours(subscription(metadata={"app": "wishlist"}))
    for metadata in (None, {}, {"app": "other"}, {"app": 1}, "wishlist"):
        assert not is_ours(subscription(metadata=metadata))


def test_the_metadata_user_id_is_a_valid_uuid_only():
    assert metadata_user_id(subscription(metadata={"user_id": str(USER)})) == USER
    for metadata in (None, {}, {"user_id": "nope"}, {"user_id": 7}, "wrong"):
        assert metadata_user_id(subscription(metadata=metadata)) is None


def test_customer_bare_or_expanded():
    assert customer_id(subscription(customer="cus_1")) == "cus_1"
    assert customer_id(subscription(customer={"id": "cus_2"})) == "cus_2"
    assert customer_id(subscription(customer=None)) is None


def test_price_of_the_first_item_or_the_old_plan_shape():
    assert price_id(subscription()) == "price_1"
    assert (
        price_id(subscription(items={"data": [{"plan": {"id": "plan_1"}}]})) == "plan_1"
    )
    assert price_id(subscription(items={"data": []})) is None


def event(kind, obj, **fields):
    return {"type": kind, "data": {"object": obj}} | fields


@pytest.mark.parametrize(
    "kind",
    [
        "customer.subscription.created",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    ],
)
def test_a_subscription_event_points_at_its_object(kind):
    found = pointer(event(kind, {"id": "sub_1"}))
    assert found.subscription_id == "sub_1"
    assert found.consent is None


def test_a_completed_session_points_at_its_subscription():
    found = pointer(
        event(
            "checkout.session.completed",
            {
                "subscription": "sub_1",
                "consent": {"terms_of_service": "accepted"},
                "metadata": {"terms_version": "v3"},
            },
            created=START,
        )
    )
    assert found.subscription_id == "sub_1"
    assert found.consent.version == "v3"
    assert found.consent.accepted_at == datetime.fromtimestamp(START, UTC)


def test_a_session_without_the_consent_records_none():
    found = pointer(
        event("checkout.session.completed", {"subscription": "sub_1"}, created=START)
    )
    assert found.consent is None


def test_a_consent_without_a_version_keeps_the_proof():
    found = pointer(
        event(
            "checkout.session.completed",
            {"subscription": "sub_1", "consent": {"terms_of_service": "accepted"}},
            created=START,
        )
    )
    assert found.consent.version == "unknown"


def test_a_session_with_no_subscription_points_nowhere():
    assert (
        pointer(event("checkout.session.completed", {"mode": "payment"}, created=START))
        is None
    )


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"type": "invoice.paid", "data": {"object": {"id": "in_1"}}},
        {"type": "customer.subscription.updated"},
        {"type": "customer.subscription.updated", "data": "wrong"},
        {"type": "customer.subscription.updated", "data": {"object": {}}},
        {"type": "customer.subscription.updated", "data": {"object": {"id": 3}}},
    ],
)
def test_anything_else_points_nowhere(value):
    assert pointer(value) is None
