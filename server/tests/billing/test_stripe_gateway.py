"""The Stripe gateway (premium plan D10): the signature for real, with the SDK
and no network; every error class reduced to a meaning, nothing of Stripe's
text leaving."""

import json
import logging
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
import stripe

from app.billing.stripe_gateway import (
    CheckoutOrder,
    GatewayUnavailable,
    InvalidWebhook,
    MissingAtStripe,
    StripeGateway,
    TermsUrlMissing,
    checkout_params,
    verify_signature,
)

SECRET = "whsec_gateway_test"
LOGGER = "app.billing.stripe_gateway"
SERVER_DIR = Path(__file__).resolve().parents[2]
LEAK = "secret-sk_live_xyz ada@example.com response body"
BODY = json.dumps({"id": "evt_1", "type": "customer.subscription.updated"})


def header(body=BODY, timestamp=None, secret=SECRET):
    return stripe.WebhookSignature.generate_signature_header(
        body, secret, timestamp=timestamp
    )


def test_a_signature_made_locally_is_accepted():
    assert verify_signature(BODY.encode(), header(), SECRET)["id"] == "evt_1"


@pytest.mark.parametrize(
    "signature",
    [
        None,
        "",
        "not a header",
        "t=abc,v1=def",
        header(secret="whsec_other"),
        header(timestamp=int(time.time()) - 301),
    ],
    ids=["none", "empty", "garbage", "bad timestamp", "other secret", "stale"],
)
def test_a_wrong_signature_is_refused(signature):
    with pytest.raises(InvalidWebhook):
        verify_signature(BODY.encode(), signature, SECRET)


def test_a_signed_body_of_the_wrong_shape_is_refused():
    with pytest.raises(InvalidWebhook):
        verify_signature(b"[1]", header(body="[1]"), SECRET)


def test_a_body_that_is_not_utf8_is_refused():
    with pytest.raises(InvalidWebhook):
        verify_signature(b"\xff\xfe", header(), SECRET)


def test_loading_the_app_with_no_keys_does_not_import_the_sdk():
    environment = os.environ | {
        "DATABASE_URL": "postgresql+psycopg://nobody@localhost/none"
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys, app.main; assert 'stripe' not in sys.modules",
        ],
        cwd=SERVER_DIR,
        env=environment,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.fixture
def gateway():
    return StripeGateway("sk_test_gateway", SECRET)


def order(automatic_tax=False):
    return CheckoutOrder(
        user_id=uuid.UUID(int=7),
        customer_id="cus_1",
        price_id="price_1",
        terms_version="v2",
        locale="fr",
        consent_text="Consent text",
        success_url="https://x.test/account/plan?checkout=success",
        cancel_url="https://x.test/account/plan?checkout=cancelled",
        automatic_tax=automatic_tax,
    )


def test_checkout_parameters_are_exactly_d12s():
    user_id = str(uuid.UUID(int=7))
    assert checkout_params(order()) == {
        "mode": "subscription",
        "line_items": [{"price": "price_1", "quantity": 1}],
        "customer": "cus_1",
        "client_reference_id": user_id,
        "subscription_data": {"metadata": {"user_id": user_id}},
        "metadata": {"terms_version": "v2"},
        "locale": "fr",
        "consent_collection": {"terms_of_service": "required"},
        "custom_text": {"terms_of_service_acceptance": {"message": "Consent text"}},
        "success_url": "https://x.test/account/plan?checkout=success",
        "cancel_url": "https://x.test/account/plan?checkout=cancelled",
    }


def test_automatic_tax_adds_its_parameters_only_when_on():
    params = checkout_params(order(automatic_tax=True))
    assert params["automatic_tax"] == {"enabled": True}
    assert params["billing_address_collection"] == "required"
    assert params["customer_update"] == {"address": "auto", "name": "auto"}
    assert not {
        "automatic_tax",
        "billing_address_collection",
        "customer_update",
    } & set(checkout_params(order()))


def failing(exc):
    def fail(*args, **kwargs):
        raise exc

    return fail


def client_with(**services):
    return SimpleNamespace(v1=SimpleNamespace(**services))


ERRORS = [
    pytest.param(stripe.APIConnectionError(LEAK), GatewayUnavailable, id="connection"),
    pytest.param(stripe.APIError(LEAK), GatewayUnavailable, id="api"),
    pytest.param(stripe.RateLimitError(LEAK), GatewayUnavailable, id="rate limit"),
    pytest.param(stripe.IdempotencyError(LEAK), GatewayUnavailable, id="idempotency"),
    pytest.param(
        stripe.CardError(LEAK, "param", "card_declined"), GatewayUnavailable, id="card"
    ),
    pytest.param(
        stripe.InvalidRequestError(LEAK, "param"), GatewayUnavailable, id="invalid"
    ),
    pytest.param(
        stripe.InvalidRequestError(LEAK, "id", code="resource_missing"),
        MissingAtStripe,
        id="missing",
    ),
    pytest.param(stripe.AuthenticationError(LEAK), GatewayUnavailable, id="auth"),
    pytest.param(stripe.PermissionError(LEAK), GatewayUnavailable, id="permission"),
]


@pytest.mark.parametrize(("error", "expected"), ERRORS)
def test_every_stripe_error_class_is_mapped(gateway, caplog, error, expected):
    gateway._client = client_with(
        subscriptions=SimpleNamespace(retrieve=failing(error))
    )

    with caplog.at_level(logging.DEBUG, logger=LOGGER), pytest.raises(expected) as info:
        gateway.subscription("sub_1")

    assert str(info.value) == ""
    assert info.value.__cause__ is None
    assert LEAK not in caplog.text
    assert "sk_test_gateway" not in caplog.text


@pytest.mark.parametrize(
    "error",
    [
        stripe.AuthenticationError(LEAK),
        stripe.PermissionError(LEAK),
    ],
    ids=["auth", "permission"],
)
def test_a_refused_key_logs_an_error(gateway, caplog, error):
    gateway._client = client_with(
        subscriptions=SimpleNamespace(retrieve=failing(error))
    )

    with (
        caplog.at_level(logging.ERROR, logger=LOGGER),
        pytest.raises(GatewayUnavailable),
    ):
        gateway.subscription("sub_1")

    assert [r.levelname for r in caplog.records] == ["ERROR"]


def test_the_subscription_comes_back_as_plain_dicts(gateway):
    source = {
        "id": "sub_1",
        "items": {"object": "list", "data": [{"current_period_end": 5}]},
    }
    gateway._client = client_with(
        subscriptions=SimpleNamespace(
            retrieve=lambda _id: stripe.Subscription.construct_from(source, "key")
        )
    )

    found = gateway.subscription("sub_1")

    assert found == source
    assert type(found["items"]) is dict
    assert type(found["items"]["data"]) is list
    assert type(found["items"]["data"][0]) is dict


def test_a_refusal_blaming_the_terms_url_is_named(gateway):
    gateway._client = client_with(
        checkout=SimpleNamespace(
            sessions=SimpleNamespace(
                create=failing(
                    stripe.InvalidRequestError(
                        "Set your terms of service URL", "consent_collection"
                    )
                )
            )
        )
    )

    with pytest.raises(TermsUrlMissing):
        gateway.checkout(order())


def test_a_checkout_answer_without_a_url_is_unavailable(gateway):
    gateway._client = client_with(
        checkout=SimpleNamespace(
            sessions=SimpleNamespace(
                create=lambda params: stripe.checkout.Session.construct_from(
                    {"url": None}, "key"
                )
            )
        )
    )

    with pytest.raises(GatewayUnavailable):
        gateway.checkout(order())


def test_cancelling_an_ended_subscription_is_a_success(gateway):
    gateway._client = client_with(
        subscriptions=SimpleNamespace(
            cancel=failing(stripe.InvalidRequestError("already", "id")),
            retrieve=lambda _id: stripe.Subscription.construct_from(
                {"status": "canceled"}, "key"
            ),
        )
    )

    gateway.cancel("sub_1")


def test_cancelling_a_running_subscription_that_refuses_fails(gateway):
    gateway._client = client_with(
        subscriptions=SimpleNamespace(
            cancel=failing(stripe.InvalidRequestError("refused", "id")),
            retrieve=lambda _id: stripe.Subscription.construct_from(
                {"status": "active"}, "key"
            ),
        )
    )

    with pytest.raises(GatewayUnavailable):
        gateway.cancel("sub_1")


class Listed:
    def __init__(self, *items):
        self._items = [stripe.StripeObject.construct_from(item, "k") for item in items]

    def auto_paging_iter(self):
        return iter(self._items)


def test_cancel_all_expires_sessions_and_cancels_what_can_still_bill(gateway):
    cancelled = []
    expired = []
    gateway._client = client_with(
        checkout=SimpleNamespace(
            sessions=SimpleNamespace(
                list=lambda params: Listed({"id": "cs_1"}),
                expire=expired.append,
            )
        ),
        subscriptions=SimpleNamespace(
            list=lambda params: Listed(
                {"id": "sub_running", "status": "active"},
                {"id": "sub_unpaid", "status": "unpaid"},
                {"id": "sub_over", "status": "canceled"},
            ),
            cancel=cancelled.append,
        ),
    )

    running = gateway.cancel_all("cus_1")

    assert expired == ["cs_1"]
    assert cancelled == ["sub_running", "sub_unpaid"]
    assert running == cancelled


def test_a_session_that_completed_since_it_was_listed_is_not_a_failure(gateway):
    gateway._client = client_with(
        checkout=SimpleNamespace(
            sessions=SimpleNamespace(
                list=lambda params: Listed({"id": "cs_1"}),
                expire=failing(stripe.InvalidRequestError("completed", "id")),
                retrieve=lambda _id: stripe.StripeObject.construct_from(
                    {"status": "complete"}, "k"
                ),
            )
        ),
    )

    gateway.expire_open_sessions("cus_1")
