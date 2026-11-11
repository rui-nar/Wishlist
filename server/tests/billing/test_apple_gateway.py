"""The Apple gateway (Apple IAP plan D3, D6): Apple's library verifying
payloads signed by a chain built here, and Apple's API answered at the HTTP
layer, so the library's own parsing runs. Nothing reaches Apple."""

import base64
import hashlib
import json
import logging
import uuid
from typing import Any

import jwt
import pytest
import requests
from apple_fakes import (
    APP_APPLE_ID,
    BUNDLE_ID,
    apple_sign,
    build_apple_pki,
    notification_claims,
    renewal_claims,
    transaction_claims,
)
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from app.billing import apple_gateway
from app.billing.apple_events import PRODUCTION, SANDBOX
from app.billing.apple_gateway import (
    AppleGateway,
    AppleUnavailable,
    InvalidSignedData,
    MissingAtApple,
    SignedData,
)
from app.settings import Settings

USER = uuid.uuid4()
ORIGINAL = "2000000001"
LOGGERS = ("app.billing.apple_gateway",)
# Apple Root CA - G3, as Apple publishes it.
G3_SHA256 = "63343abfb89a6a03ebb57e9b3f5fa7be7c4f5c756f3017b3a8c488c3653e9179"


@pytest.fixture
def signed(apple_pki):
    return SignedData(
        [apple_pki.root_der],
        BUNDLE_ID,
        APP_APPLE_ID,
        (PRODUCTION, SANDBOX),
        online_checks=False,
    )


@pytest.fixture
def key_pem():
    key = ec.generate_private_key(ec.SECP256R1())
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


@pytest.fixture
def gateway(signed, key_pem):
    return AppleGateway(signed, BUNDLE_ID, "issuer-placeholder", "KEY", key_pem)


class Answer:
    """What `requests.request` returns, as far as the library reads it."""

    def __init__(self, status_code: int, body: Any) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._body = body

    def json(self) -> Any:
        return self._body


@pytest.fixture
def apple_api(monkeypatch):
    """Apple's API at the HTTP layer: `answer` is returned, or raised when an
    exception; each request is recorded."""

    class Api:
        def __init__(self) -> None:
            self.answer: Any = Answer(500, {})
            self.requests: list[tuple[str, str, dict[str, str]]] = []

    api = Api()

    def request(method, url, **kwargs):
        api.requests.append((method, url, kwargs["headers"]))
        if isinstance(api.answer, Exception):
            raise api.answer
        return api.answer

    monkeypatch.setattr(requests, "request", request)
    return api


def statuses(pki, status=1, environment=SANDBOX, original=ORIGINAL, renewal=True):
    item = {
        "status": status,
        "originalTransactionId": original,
        "signedTransactionInfo": apple_sign(
            pki, transaction_claims(original, USER, environment)
        ),
    }
    if renewal:
        item["signedRenewalInfo"] = apple_sign(
            pki, renewal_claims(original, environment, grace=None)
        )
    return {
        "environment": environment,
        "bundleId": BUNDLE_ID,
        "appAppleId": APP_APPLE_ID,
        "data": [{"subscriptionGroupIdentifier": "1", "lastTransactions": [item]}],
    }


def tampered(jws: str, **changes: Any) -> str:
    """The same signature over other claims."""
    header, payload, signature = jws.split(".")
    claims = json.loads(base64.urlsafe_b64decode(payload + "=="))
    body = json.dumps(claims | changes).encode()
    return ".".join(
        [header, base64.urlsafe_b64encode(body).decode().rstrip("="), signature]
    )


def assert_nothing_secret_logged(caplog, *secrets):
    text = caplog.text
    for secret in secrets:
        assert secret not in text


def test_a_transaction_signed_through_the_root_is_read(signed, apple_pki):
    claims = transaction_claims(ORIGINAL, USER)
    assert signed.transaction(apple_sign(apple_pki, claims)) == claims


def test_a_production_transaction_is_read_where_production_is_accepted(
    signed, apple_pki
):
    claims = transaction_claims(ORIGINAL, USER, PRODUCTION)
    assert signed.transaction(apple_sign(apple_pki, claims)) == claims


def test_a_tampered_transaction_is_refused(signed, apple_pki):
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER))
    with pytest.raises(InvalidSignedData):
        signed.transaction(tampered(jws, appAccountToken=str(uuid.uuid4())))


def test_a_chain_to_another_root_is_refused(signed):
    forged = build_apple_pki()
    with pytest.raises(InvalidSignedData):
        signed.transaction(apple_sign(forged, transaction_claims(ORIGINAL, USER)))


def test_a_leaf_without_apples_extension_is_refused(apple_pki):
    other = build_apple_pki(leaf_oid="1.2.3.4")
    verifier = SignedData(
        [other.root_der], BUNDLE_ID, APP_APPLE_ID, (SANDBOX,), online_checks=False
    )
    with pytest.raises(InvalidSignedData):
        verifier.transaction(apple_sign(other, transaction_claims(ORIGINAL, USER)))


def test_another_apps_transaction_is_refused(signed, apple_pki):
    claims = transaction_claims(ORIGINAL, USER) | {"bundleId": "com.example.other"}
    with pytest.raises(InvalidSignedData):
        signed.transaction(apple_sign(apple_pki, claims))


def test_an_environment_not_accepted_is_refused(apple_pki):
    sandbox_only = SignedData(
        [apple_pki.root_der], BUNDLE_ID, None, (SANDBOX,), online_checks=False
    )
    claims = transaction_claims(ORIGINAL, USER, PRODUCTION)
    with pytest.raises(InvalidSignedData):
        sandbox_only.transaction(apple_sign(apple_pki, claims))
    for name in ("Xcode", "LocalTesting"):
        with pytest.raises(InvalidSignedData):
            sandbox_only.transaction(
                apple_sign(apple_pki, claims | {"environment": name})
            )


@pytest.mark.parametrize("value", ["", "not a jws", "a.b.c", "x" * 5000])
def test_garbage_is_refused(signed, value):
    with pytest.raises(InvalidSignedData):
        signed.transaction(value)


def test_another_algorithm_is_refused(signed, apple_pki):
    claims = transaction_claims(ORIGINAL, USER)
    jws = jwt.encode(
        claims, "secret" * 8, algorithm="HS256", headers={"x5c": apple_pki.x5c}
    )
    with pytest.raises(InvalidSignedData):
        signed.transaction(jws)


def test_a_notification_is_read(signed, apple_pki):
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER))
    claims = notification_claims(jws)
    assert signed.notification(apple_sign(apple_pki, claims)) == claims


def test_production_reads_a_sandbox_notification_without_an_app_apple_id(
    signed, apple_pki
):
    """Production's verifier would refuse it for its app identifier before
    looking at its environment: the Sandbox one reads it (review R2-3)."""
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER))
    claims = notification_claims(jws, "Sandbox")
    assert "appAppleId" not in claims["data"]

    assert signed.notification(apple_sign(apple_pki, claims)) == claims


def test_a_production_notification_is_read(signed, apple_pki):
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER, PRODUCTION))
    claims = notification_claims(jws, PRODUCTION)
    assert signed.notification(apple_sign(apple_pki, claims)) == claims


def test_a_production_notification_without_the_app_apple_id_is_refused(
    signed, apple_pki
):
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER, PRODUCTION))
    claims = notification_claims(jws, PRODUCTION)
    del claims["data"]["appAppleId"]
    with pytest.raises(InvalidSignedData):
        signed.notification(apple_sign(apple_pki, claims))


@pytest.mark.parametrize("environment", [None, "Xcode", 7])
def test_a_payload_declaring_no_accepted_environment_is_refused(
    signed, apple_pki, environment
):
    claims = transaction_claims(ORIGINAL, USER) | {"environment": environment}
    with pytest.raises(InvalidSignedData):
        signed.transaction(apple_sign(apple_pki, claims))
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER))
    notification = notification_claims(jws)
    notification["data"]["environment"] = environment
    with pytest.raises(InvalidSignedData):
        signed.notification(apple_sign(apple_pki, notification))


def test_a_production_notification_of_another_app_id_is_refused(signed, apple_pki):
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER, PRODUCTION))
    claims = notification_claims(jws, PRODUCTION)
    claims["data"]["appAppleId"] = APP_APPLE_ID + 1
    with pytest.raises(InvalidSignedData):
        signed.notification(apple_sign(apple_pki, claims))


def test_a_forged_notification_is_refused(signed, apple_pki):
    forged = build_apple_pki()
    jws = apple_sign(apple_pki, transaction_claims(ORIGINAL, USER))
    with pytest.raises(InvalidSignedData):
        signed.notification(apple_sign(forged, notification_claims(jws)))


def test_the_subscription_as_apple_answers(gateway, apple_pki, apple_api):
    apple_api.answer = Answer(200, statuses(apple_pki, status=4))

    found = gateway.subscription(ORIGINAL, SANDBOX)

    assert found.status == 4
    assert (
        found.transaction["originalTransactionId"],
        found.transaction["appAccountToken"],
        found.transaction["environment"],
    ) == (ORIGINAL, str(USER), SANDBOX)
    assert found.renewal["autoRenewStatus"] == 1
    [(method, url, headers)] = apple_api.requests
    assert method == "GET"
    assert (
        url
        == f"https://api.storekit-sandbox.apple.com/inApps/v1/subscriptions/{ORIGINAL}"
    )
    assert headers["Authorization"].startswith("Bearer ")


def test_production_asks_apples_production_api(gateway, apple_pki, apple_api):
    apple_api.answer = Answer(200, statuses(apple_pki, environment=PRODUCTION))

    assert gateway.subscription(ORIGINAL, PRODUCTION).status == 1
    [(_, url, _)] = apple_api.requests
    assert url.startswith("https://api.storekit.apple.com/")


def test_no_renewal_info_is_an_empty_one(gateway, apple_pki, apple_api):
    apple_api.answer = Answer(200, statuses(apple_pki, renewal=False))
    assert gateway.subscription(ORIGINAL, SANDBOX).renewal == {}


@pytest.mark.parametrize("error", [4040005, 4040010, 4000006])
def test_unknown_to_apple(gateway, apple_api, error):
    apple_api.answer = Answer(404, {"errorCode": error, "errorMessage": "x"})
    with pytest.raises(MissingAtApple):
        gateway.subscription(ORIGINAL, SANDBOX)


def test_not_in_apples_answer_is_unknown(gateway, apple_pki, apple_api):
    apple_api.answer = Answer(200, statuses(apple_pki, original="2000000002"))
    with pytest.raises(MissingAtApple):
        gateway.subscription(ORIGINAL, SANDBOX)


@pytest.mark.parametrize(
    "answer",
    [
        Answer(404, {"errorCode": 4040006, "errorMessage": "retry"}),
        Answer(429, {"errorCode": 4290000, "errorMessage": "slow down"}),
        Answer(500, {"errorCode": 5000000, "errorMessage": "oops"}),
        Answer(401, {}),
        Answer(200, {"data": 5}),
        requests.ConnectionError("the network"),
        requests.Timeout("too late"),
    ],
)
def test_apple_failing_is_unavailable(gateway, apple_api, answer, caplog):
    apple_api.answer = answer
    with caplog.at_level(logging.WARNING, logger=LOGGERS[0]):
        with pytest.raises(AppleUnavailable):
            gateway.subscription(ORIGINAL, SANDBOX)
    assert "retry" not in caplog.text
    assert "slow down" not in caplog.text
    assert "the network" not in caplog.text


def test_a_refused_key_is_an_error(gateway, apple_api, caplog):
    apple_api.answer = Answer(401, {})
    with caplog.at_level(logging.WARNING, logger=LOGGERS[0]):
        with pytest.raises(AppleUnavailable):
            gateway.subscription(ORIGINAL, SANDBOX)
    assert [record.levelname for record in caplog.records] == ["ERROR"]


def test_an_answer_signed_by_another_root_is_unavailable(gateway, apple_api, caplog):
    forged = build_apple_pki()
    apple_api.answer = Answer(200, statuses(forged))
    with caplog.at_level(logging.WARNING, logger=LOGGERS[0]):
        with pytest.raises(AppleUnavailable):
            gateway.subscription(ORIGINAL, SANDBOX)
    assert "failed its signature check" in caplog.text


def test_an_answer_for_another_environment_is_unavailable(
    gateway, apple_pki, apple_api
):
    apple_api.answer = Answer(200, statuses(apple_pki, environment=PRODUCTION))
    with pytest.raises(AppleUnavailable):
        gateway.subscription(ORIGINAL, SANDBOX)


@pytest.mark.parametrize("original", ["", "12/../34", "12?x=1", "１２"])
def test_an_id_that_is_not_digits_asks_nothing(gateway, apple_api, original):
    with pytest.raises(MissingAtApple):
        gateway.subscription(original, SANDBOX)
    assert apple_api.requests == []


def test_an_environment_not_accepted_asks_nothing(apple_pki, key_pem, apple_api):
    sandbox_only = AppleGateway(
        SignedData(
            [apple_pki.root_der], BUNDLE_ID, None, (SANDBOX,), online_checks=False
        ),
        BUNDLE_ID,
        "issuer",
        "KEY",
        key_pem,
    )
    with pytest.raises(MissingAtApple):
        sandbox_only.subscription(ORIGINAL, PRODUCTION)
    assert apple_api.requests == []


def test_no_signed_payload_or_key_is_logged(
    gateway, apple_pki, apple_api, key_pem, caplog
):
    forged = build_apple_pki()
    answer = statuses(forged)
    apple_api.answer = Answer(200, answer)
    item = answer["data"][0]["lastTransactions"][0]
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(AppleUnavailable):
            gateway.subscription(ORIGINAL, SANDBOX)
        with pytest.raises(InvalidSignedData):
            gateway.transaction(item["signedTransactionInfo"])
    assert_nothing_secret_logged(
        caplog,
        item["signedTransactionInfo"],
        item["signedRenewalInfo"],
        key_pem.decode().splitlines()[1],
    )


def test_apples_root_is_g3():
    [root] = apple_gateway.root_certificates()
    assert hashlib.sha256(root).hexdigest() == G3_SHA256


@pytest.fixture(autouse=True)
def nothing_from_the_environment(monkeypatch):
    """A developer's shell may hold these (the dev scripts load `.env`)."""
    for name in Settings.model_fields:
        if name != "database_url":
            monkeypatch.delenv(name.upper(), raising=False)


def settings(**values) -> Settings:
    return Settings(database_url="postgresql+psycopg://x:y@localhost/z", **values)


def test_nothing_set_is_no_gateway():
    gateway, gaps = apple_gateway.from_settings(settings())
    assert gateway is None
    assert gaps == [
        "APPLE_PRODUCT_ID",
        "APPLE_BUNDLE_ID",
        "APPLE_IAP_ISSUER_ID",
        "APPLE_IAP_KEY_ID",
        "APPLE_IAP_PRIVATE_KEY",
    ]


def test_everything_set_is_a_gateway_for_sandbox_only(apple_on, apple_api):
    gateway, gaps = apple_gateway.from_settings(settings(**apple_on))
    assert (gaps, isinstance(gateway, AppleGateway)) == ([], True)
    # Nothing is asked of Production's API outside production (D6).
    with pytest.raises(MissingAtApple):
        gateway.subscription(ORIGINAL, PRODUCTION)
    assert apple_api.requests == []


def test_production_reads_both_environments(apple_on, apple_api):
    gateway, gaps = apple_gateway.from_settings(
        settings(**apple_on, app_env="production")
    )
    assert gaps == []
    for environment in (PRODUCTION, SANDBOX):
        with pytest.raises(AppleUnavailable):
            gateway.subscription(ORIGINAL, environment)
    assert [url.split("/")[2] for _, url, _ in apple_api.requests] == [
        "api.storekit.apple.com",
        "api.storekit-sandbox.apple.com",
    ]


@pytest.mark.parametrize("value", ["", "12a", " ", "１２"])
def test_production_needs_the_apps_apple_id(apple_on, value):
    gateway, gaps = apple_gateway.from_settings(
        settings(**apple_on | {"apple_app_apple_id": value}, app_env="production")
    )
    assert (gateway, gaps) == (None, ["APPLE_APP_APPLE_ID"])


def test_the_apps_apple_id_is_not_needed_elsewhere(apple_on):
    gateway, gaps = apple_gateway.from_settings(
        settings(**apple_on | {"apple_app_apple_id": ""})
    )
    assert gateway is not None and gaps == []


def test_a_key_that_does_not_load_is_named_never_quoted(apple_on, caplog):
    gateway, gaps = apple_gateway.from_settings(
        settings(**apple_on | {"apple_iap_private_key": "not-a-key-secret"})
    )
    assert (gateway, gaps) == (None, ["APPLE_IAP_PRIVATE_KEY"])
    assert "not-a-key-secret" not in caplog.text


def test_a_key_on_one_line_loads(apple_on):
    one_line = apple_on["apple_iap_private_key"].strip().replace("\n", "\\n")
    gateway, _ = apple_gateway.from_settings(
        settings(**apple_on | {"apple_iap_private_key": one_line})
    )
    assert gateway is not None
