"""The Google gateway (Android release plan D6): Pub/Sub's push tokens
verified by google-auth against a key made here, and the Play Developer API
answered at the HTTP layer. Nothing reaches Google."""

import json
import logging
from types import SimpleNamespace
from typing import Any

import pytest
import requests
from google.auth import exceptions as google_exceptions
from google_fakes import (
    AUDIENCE,
    PACKAGE,
    PRODUCT_ID,
    PUSH_ACCOUNT,
    TOKEN,
    GoogleKeys,
    other_signer,
    purchase,
)

from app.billing import google_gateway
from app.billing.google_gateway import (
    GoogleGateway,
    GoogleUnavailable,
    InvalidPush,
    MissingAtGoogle,
)
from app.settings import Settings

LOGGER = "app.billing.google_gateway"
API = "https://androidpublisher.googleapis.com/androidpublisher/v3/applications"


# Pub/Sub's push authentication.


@pytest.fixture
def keys():
    return GoogleKeys()


def bearer(token):
    return f"Bearer {token}"


def test_a_valid_push_token_passes(keys):
    keys.verifier().verify(bearer(keys.token()))
    assert keys.fetches == 1


@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "https://elsewhere.example"},
        {"email": "other@example-project.iam.gserviceaccount.com"},
        {"email_verified": False},
        {"email_verified": "false"},
        {"iss": "https://evil.example"},
        {"exp": 1_000_000_000, "iat": 999_996_400},
    ],
)
def test_a_push_token_with_wrong_claims_is_refused(keys, claims):
    with pytest.raises(InvalidPush):
        keys.verifier().verify(bearer(keys.token(**claims)))


def test_a_string_true_email_verified_passes(keys):
    keys.verifier().verify(bearer(keys.token(email_verified="true")))


def test_a_push_token_signed_by_another_key_is_refused(keys):
    with pytest.raises(InvalidPush):
        keys.verifier().verify(bearer(keys.token(signer=other_signer())))


@pytest.mark.parametrize(
    "authorization",
    [None, "", "Bearer", "Basic x", "Bearer x", "Bearer a.b.c", "bearer  "],
)
def test_junk_is_refused_before_any_fetch(keys, authorization):
    with pytest.raises(InvalidPush):
        keys.verifier().verify(authorization)
    assert keys.fetches == 0


def test_another_algorithm_is_refused_before_any_fetch(keys):
    import jwt as pyjwt

    token = pyjwt.encode(
        {"aud": AUDIENCE, "email": PUSH_ACCOUNT},
        "secret-secret-secret-secret-secret!",
        algorithm="HS256",
        headers={"kid": GoogleKeys.KEY_ID},
    )
    with pytest.raises(InvalidPush):
        keys.verifier().verify(bearer(token))
    assert keys.fetches == 0


def test_certificates_unavailable_is_unavailable(keys, caplog):
    keys.unavailable = True
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        with pytest.raises(GoogleUnavailable):
            keys.verifier().verify(bearer(keys.token()))
    assert "certificates could not be fetched" in caplog.text


# The Play Developer API, at the HTTP layer.


class Session:
    """What `AuthorizedSession` is to the gateway: `answer` returned, or
    raised when an exception; each request recorded."""

    def __init__(self) -> None:
        self.answer: Any = None
        self.requests: list[tuple[str, str, Any]] = []

    def request(self, method, url, json=None, timeout=None):
        self.requests.append((method, url, json))
        assert timeout is not None
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def http(status: int, body: Any = None) -> Any:
    content = b"" if body is None else json.dumps(body).encode()
    return SimpleNamespace(
        status_code=status, content=content, json=lambda: json.loads(content)
    )


@pytest.fixture
def session():
    return Session()


@pytest.fixture
def gateway(session, keys):
    return GoogleGateway(keys.verifier(), PACKAGE, PRODUCT_ID, session)


def test_a_subscription_is_read_from_subscriptionsv2(gateway, session):
    answer = purchase(None)
    session.answer = http(200, answer)

    assert gateway.subscription(TOKEN) == answer
    assert session.requests == [
        ("GET", f"{API}/{PACKAGE}/purchases/subscriptionsv2/tokens/{TOKEN}", None)
    ]


def test_acknowledge_and_cancel_name_the_product(gateway, session):
    session.answer = http(204)
    gateway.acknowledge(TOKEN)
    gateway.cancel(TOKEN)
    base = f"{API}/{PACKAGE}/purchases/subscriptions/{PRODUCT_ID}/tokens/{TOKEN}"
    assert session.requests == [
        ("POST", f"{base}:acknowledge", {}),
        ("POST", f"{base}:cancel", None),
    ]


@pytest.mark.parametrize("status", [400, 404, 410])
def test_not_found_is_missing(gateway, session, status):
    session.answer = http(status, {"error": {"message": f"token {TOKEN}"}})
    with pytest.raises(MissingAtGoogle):
        gateway.subscription(TOKEN)


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_a_failure_is_unavailable_and_logged_without_its_text(
    gateway, session, caplog, status
):
    session.answer = http(status, {"error": {"message": f"token {TOKEN}"}})
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        with pytest.raises(GoogleUnavailable):
            gateway.subscription(TOKEN)
    assert f"HTTP {status}" in caplog.text
    assert TOKEN not in caplog.text


def test_a_refused_key_is_an_error(gateway, session, caplog):
    session.answer = google_exceptions.RefreshError(f"invalid_grant {TOKEN}")
    with caplog.at_level(logging.ERROR, logger=LOGGER):
        with pytest.raises(GoogleUnavailable):
            gateway.cancel(TOKEN)
    assert "the service account's key was refused" in caplog.text
    assert TOKEN not in caplog.text


def test_a_network_failure_logs_no_url(gateway, session, caplog):
    session.answer = requests.ConnectionError(f"failed for {API}/x/tokens/{TOKEN}")
    with caplog.at_level(logging.WARNING, logger=LOGGER):
        with pytest.raises(GoogleUnavailable):
            gateway.subscription(TOKEN)
    assert "ConnectionError" in caplog.text
    assert TOKEN not in caplog.text


@pytest.mark.parametrize("body", [None, [], "text"])
def test_an_answer_that_is_no_purchase_is_unavailable(gateway, session, body):
    session.answer = http(200, body)
    with pytest.raises(GoogleUnavailable):
        gateway.subscription(TOKEN)


def test_an_answer_that_is_no_json_is_unavailable(gateway, session):
    def broken():
        raise ValueError("not json")

    session.answer = SimpleNamespace(status_code=200, content=b"<html>", json=broken)
    with pytest.raises(GoogleUnavailable):
        gateway.subscription(TOKEN)


@pytest.mark.parametrize("token", ["a/b", "../x", "a b", "", "x" * 2049])
def test_a_token_that_is_no_token_is_never_sent(gateway, session, token):
    with pytest.raises(MissingAtGoogle):
        gateway.subscription(token)
    with pytest.raises(MissingAtGoogle):
        gateway.cancel(token)
    assert session.requests == []


# From the settings.


def settings(**values: Any) -> Settings:
    return Settings(database_url="postgresql+psycopg://x@localhost/x", **values)


def test_the_gateway_is_made_once_everything_is_set(google_on):
    gateway, gaps = google_gateway.from_settings(settings(**google_on))
    assert gaps == []
    assert isinstance(gateway, GoogleGateway)
    assert gateway.product_id == PRODUCT_ID


@pytest.mark.parametrize(
    "variable",
    [
        "google_play_product_id",
        "google_play_package_name",
        "google_play_service_account_json",
        "google_play_pubsub_audience",
        "google_play_pubsub_service_account",
    ],
)
def test_each_variable_is_needed(google_on, variable):
    """Without the Pub/Sub ones, renewals, grace and refunds would go
    unrecorded: nothing is sold (review R1-2)."""
    gateway, gaps = google_gateway.from_settings(
        settings(**google_on | {variable: " "})
    )
    assert gateway is None
    assert gaps == [variable.upper()]


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        "[]",
        '{"type": "service_account"}',
        '{"type": "service_account", "client_email": "a@b", "token_uri": "x",'
        ' "private_key": "-----BEGIN PRIVATE KEY-----\\nsecret-text"}',
    ],
)
def test_a_key_that_does_not_load_is_named_never_quoted(google_on, text, caplog):
    with caplog.at_level(logging.DEBUG):
        gateway, gaps = google_gateway.from_settings(
            settings(**google_on | {"google_play_service_account_json": text})
        )
    assert gateway is None
    assert gaps == ["GOOGLE_PLAY_SERVICE_ACCOUNT_JSON"]
    assert "secret-text" not in caplog.text
