"""POST /api/auth/apple and the real AppleVerifier, against tokens signed by a
key made here and a fake key source: no test calls Apple (sign-in plan D14, D15).
"""

import base64
import hashlib
import hmac
import json
import logging
import time
from collections.abc import Callable
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm
from sqlalchemy import text

from app.accounts.apple import AppleKeys, AppleKeysUnavailable, AppleVerifier

ISSUER = "https://appleid.apple.com"
SERVICES_ID = "com.example.shushgift.web"
BUNDLE_ID = "com.example.shushgift"
KEY_ID = "test-key"
NONCE = "a-random-nonce"
ADDRESS = "ada@example.com"
RELAY_ADDRESS = "x7f3k9@privaterelay.appleid.com"
REFUSED_BODY = {"detail": "Invalid Apple ID token"}
# Left out of the token altogether.
ABSENT = object()

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PUBLIC_PEM = KEY.public_key().public_bytes(
    serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
)


def hashed(nonce: str) -> str:
    return hashlib.sha256(nonce.encode()).hexdigest()


def claims(**overrides: Any) -> dict[str, Any]:
    """What Apple signs, valid now unless overridden."""
    now = int(time.time())
    payload = {
        "iss": ISSUER,
        "aud": SERVICES_ID,
        "sub": "apple-sub-1",
        "email": ADDRESS,
        "email_verified": "true",
        "nonce": hashed(NONCE),
        "iat": now,
        "exp": now + 600,
    } | overrides
    return {name: value for name, value in payload.items() if value is not ABSENT}


def token(
    key: rsa.RSAPrivateKey = KEY,
    kid: str = KEY_ID,
    algorithm: str = "RS256",
    **overrides: Any,
) -> str:
    return jwt.encode(
        claims(**overrides), key, algorithm=algorithm, headers={"kid": kid}
    )


def _encoded(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forged(algorithm: str, sign: Callable[[bytes], bytes]) -> str:
    """By hand: PyJWT itself refuses to make these."""
    header = _encoded(json.dumps({"alg": algorithm, "kid": KEY_ID}).encode())
    payload = _encoded(json.dumps(claims()).encode())
    signed = f"{header}.{payload}"
    return f"{signed}.{_encoded(sign(signed.encode()))}"


def signed_with_the_public_key(message: bytes) -> bytes:
    return hmac.new(PUBLIC_PEM, message, hashlib.sha256).digest()


def ago(seconds: int) -> int:
    return int(time.time()) - seconds


class FakeKeys:
    """Stands in for Apple's key endpoint."""

    def __init__(self) -> None:
        self.unavailable = False

    def key(self, kid: str) -> Any | None:
        if self.unavailable:
            raise AppleKeysUnavailable
        return KEY.public_key() if kid == KEY_ID else None


class OfflineClient(jwt.PyJWKClient):
    """PyJWT's own client and cache, answering from here instead of the network:
    a JWK set, anything else Apple might answer, or an exception to raise."""

    def __init__(self, answer: Any) -> None:
        super().__init__("https://apple.test/auth/keys", lifespan=3600)
        self.answer = answer
        self.fetches = 0

    def fetch_data(self) -> Any:
        self.fetches += 1
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def jwk_set() -> dict[str, Any]:
    key = RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True)
    return {"keys": [key | {"kid": KEY_ID, "use": "sig", "alg": "RS256"}]}


def count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


def post(client, id_token: str, nonce: str = NONCE, **extra: Any) -> Any:
    # Encoded here, with its escapes: httpx cannot send a lone surrogate.
    return client.post(
        "/api/auth/apple",
        content=json.dumps({"id_token": id_token, "nonce": nonce} | extra),
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture
def keys(client) -> FakeKeys:
    fake = FakeKeys()
    client.app.state.apple_verifier = AppleVerifier([SERVICES_ID, BUNDLE_ID], fake)
    return fake


REFUSALS = {
    "another issuer": (lambda: token(iss="https://evil.example"), "issuer"),
    "no issuer": (lambda: token(iss=ABSENT), "missing_claim"),
    "another audience": (lambda: token(aud="com.example.other"), "audience"),
    "no audience": (lambda: token(aud=ABSENT), "missing_claim"),
    "the nonce of another sign-in": (lambda: token(nonce=hashed("x")), "nonce"),
    "the nonce unhashed": (lambda: token(nonce=NONCE), "nonce"),
    "no nonce": (lambda: token(nonce=ABSENT), "nonce"),
    "algorithm none": (lambda: forged("none", lambda _: b""), "algorithm"),
    "HS256 signed with the public key": (
        lambda: forged("HS256", signed_with_the_public_key),
        "algorithm",
    ),
    "another RSA algorithm": (lambda: token(algorithm="RS512"), "algorithm"),
    "signed by another key": (lambda: token(key=OTHER_KEY), "signature"),
    "a key Apple does not have": (lambda: token(kid="made-up"), "key"),
    "expired": (lambda: token(iat=ago(7200), exp=ago(3600)), "expired"),
    "expired past the leeway": (lambda: token(iat=ago(600), exp=ago(11)), "expired"),
    "issued in the future": (lambda: token(iat=ago(-3600)), "too_early"),
    "no expiry": (lambda: token(exp=ABSENT), "missing_claim"),
    "no issue time": (lambda: token(iat=ABSENT), "missing_claim"),
    "no subject": (lambda: token(sub=ABSENT), "missing_claim"),
    "an empty subject": (lambda: token(sub=""), "no_subject"),
    "an unverified address": (
        lambda: token(email_verified="false"),
        "email_not_verified",
    ),
    "an address verified false": (
        lambda: token(email_verified=False),
        "email_not_verified",
    ),
    "an address without a verified claim": (
        lambda: token(email_verified=ABSENT),
        "email_not_verified",
    ),
    "an address that is none": (lambda: token(email="no-at-sign"), "bad_address"),
    "an address that is no text": (lambda: token(email=["a@b.c"]), "bad_address"),
    "not a token": (lambda: "bm90aGluZw.c2VjcmV0LXBhcnQ.c2lnbmF0dXJl", "malformed"),
}


@pytest.mark.parametrize("case", REFUSALS)
def test_a_refused_token_gets_one_body(client, keys, engine, caplog, case):
    make, reason = REFUSALS[case]
    id_token = make()

    with caplog.at_level(logging.DEBUG):
        response = post(client, id_token)

    assert response.status_code == 401
    assert response.json() == REFUSED_BODY
    assert count(engine, "users") == 0
    assert count(engine, "sessions") == 0
    # Refused for this reason, and not some other on the way.
    assert f"reason={reason}" in caplog.text
    assert id_token not in caplog.text
    for segment in id_token.split("."):
        if segment:
            assert segment not in caplog.text


def test_a_first_sign_in_makes_an_account_with_the_name(client, keys, engine):
    response = post(client, token(), name="  Ada Lovelace ")

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == ADDRESS
    assert body["user"]["display_name"] == "Ada Lovelace"
    assert count(engine, "users") == 1
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json() == body["user"] | {"is_admin": False}


def test_a_later_sign_in_without_name_or_address_keeps_both(client, keys, engine):
    first = post(client, token(), name="Ada Lovelace").json()

    later = post(client, token(email=ABSENT, email_verified=ABSENT))

    assert later.status_code == 200
    assert later.json()["user"] == first["user"]
    assert later.json()["token"] != first["token"]
    assert count(engine, "users") == 1


def test_a_later_sign_in_refreshes_the_address_and_never_the_name(client, keys):
    first = post(client, token(), name="Ada Lovelace").json()

    later = post(client, token(email="new@example.com"), name="Someone Else")

    assert later.json()["user"] == {
        "id": first["user"]["id"],
        "email": "new@example.com",
        "display_name": "Ada Lovelace",
    }


def test_no_address_on_a_first_sign_in_is_refused(client, keys, engine, caplog):
    id_token = token(email=ABSENT, email_verified=ABSENT)

    with caplog.at_level(logging.WARNING):
        response = post(client, id_token, name="Ada Lovelace")

    assert response.status_code == 401
    assert response.json() == REFUSED_BODY
    assert count(engine, "users") == 0
    assert "reason=no_address" in caplog.text


def test_without_a_name_the_address_gives_one(client, keys):
    response = post(client, token(email="Grace.Hopper@example.com"))

    assert response.json()["user"] == {
        "id": response.json()["user"]["id"],
        "email": "grace.hopper@example.com",
        "display_name": "grace.hopper",
    }


def test_a_long_address_gives_a_name_within_the_limit(client, keys):
    response = post(client, token(email=f"{'a' * 150}@example.com"))

    assert response.json()["user"]["display_name"] == "a" * 100


def test_a_relay_address_gets_apple_user(client, keys):
    response = post(client, token(email=RELAY_ADDRESS))

    assert response.json()["user"]["email"] == RELAY_ADDRESS
    assert response.json()["user"]["display_name"] == "Apple user"


def test_a_relay_address_keeps_a_name_it_was_given(client, keys):
    response = post(client, token(email=RELAY_ADDRESS), name="Ada Lovelace")

    assert response.json()["user"]["display_name"] == "Ada Lovelace"


@pytest.mark.parametrize(
    "name",
    [
        "",
        "   ",
        "a" * 101,
        "a" * 401,
        "Ada\x07",
        "Ada\r\nBcc: someone@example.com",
        "Ada‮Lovelace",
        "Ada\ud800",
    ],
)
def test_a_hostile_name_is_refused(client, keys, engine, name):
    response = post(client, token(), name=name)

    assert response.status_code == 422
    assert count(engine, "users") == 0


def test_a_lone_surrogate_in_the_nonce_is_refused(client, keys):
    assert post(client, token(), nonce="\ud800").status_code == 422


@pytest.mark.parametrize(
    "body",
    [
        {"id_token": "x" * (4 * 1024 + 1), "nonce": NONCE},
        {"id_token": "a.b.c", "nonce": "x" * 257},
    ],
)
def test_oversized_fields_are_refused_without_being_echoed(client, keys, body):
    response = client.post("/api/auth/apple", json=body)

    assert response.status_code == 422
    assert "x" * 100 not in response.text


def test_every_configured_audience_is_accepted(client, keys):
    assert post(client, token(aud=BUNDLE_ID)).status_code == 200


def test_a_verified_claim_may_be_a_boolean(client, keys):
    assert post(client, token(email_verified=True)).status_code == 200


def test_a_token_within_the_leeway_is_accepted(client, keys):
    assert post(client, token(iat=ago(600), exp=ago(5))).status_code == 200


def test_an_account_is_never_found_by_its_address(client, keys, sign_in, engine):
    google = sign_in("google-sub", ADDRESS, "Ada on Google")

    apple = post(client, token(), name="Ada on Apple")

    assert apple.json()["user"]["id"] != google["user"]["id"]
    assert count(engine, "users") == 2


def test_the_log_carries_no_address_or_name(client, keys, caplog):
    with caplog.at_level(logging.DEBUG):
        post(client, token(email_verified="false"), name="Ada Lovelace")
        post(client, token(), name="Ada Lovelace")

    assert ADDRESS not in caplog.text
    assert "Ada Lovelace" not in caplog.text


def test_keys_unreachable_answers_502(client, keys, engine):
    keys.unavailable = True

    response = post(client, token())

    assert response.status_code == 502
    assert response.json() == {"detail": "Apple could not be reached"}
    assert count(engine, "users") == 0


def test_not_configured_answers_503(client):
    response = post(client, "anything")

    assert response.status_code == 503
    assert response.json() == {"detail": "Apple sign-in is not configured"}


def test_the_app_makes_a_verifier_only_with_client_ids(make_client):
    configured = make_client(apple_client_ids=f" {SERVICES_ID} , {BUNDLE_ID} ")

    assert isinstance(configured.app.state.apple_verifier, AppleVerifier)
    assert make_client().app.state.apple_verifier is None


def with_keys(client, source: OfflineClient) -> None:
    client.app.state.apple_verifier = AppleVerifier([SERVICES_ID], AppleKeys(source))


def test_a_valid_token_signs_in_through_pyjwts_client(client):
    source = OfflineClient(jwk_set())
    with_keys(client, source)

    assert post(client, token()).status_code == 200
    assert post(client, token()).status_code == 200
    assert source.fetches == 1


def test_made_up_key_ids_do_not_each_call_apple(client):
    source = OfflineClient(jwk_set())
    with_keys(client, source)

    for _ in range(5):
        response = post(client, token(kid="made-up"))
        assert response.status_code == 401
        assert response.json() == REFUSED_BODY

    # The first fetch, and the one forced refresh of the cooldown.
    assert source.fetches == 2


SECRET_MESSAGE = "the text of a provider message"


@pytest.mark.parametrize(
    "answer",
    [
        jwt.PyJWKClientConnectionError(SECRET_MESSAGE),
        TimeoutError(SECRET_MESSAGE),
        json.JSONDecodeError(SECRET_MESSAGE, "", 0),
        [{"not": "an object"}],
        {"keys": []},
        {"no keys": True},
    ],
    ids=["unreachable", "timeout", "no JSON", "no object", "empty", "no keys"],
)
def test_any_bad_answer_from_apple_is_502(client, engine, caplog, answer):
    with_keys(client, OfflineClient(answer))

    with caplog.at_level(logging.DEBUG):
        response = post(client, token())

    assert response.status_code == 502
    assert response.json() == {"detail": "Apple could not be reached"}
    assert count(engine, "users") == 0
    assert "Apple keys unavailable" in caplog.text
    assert SECRET_MESSAGE not in caplog.text
