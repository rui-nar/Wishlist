"""Apple's token kept at sign-in and revoked at account deletion (iOS app plan
D5): the endpoint and the deletion against a fake of Apple's token endpoints,
and the real client against a recording transport. No test calls Apple.
"""

import json
import logging
import uuid
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_apple import BUNDLE_ID, SERVICES_ID, FakeKeys, count, post, token

from app.accounts import apple_tokens
from app.accounts.apple import (
    AppleVerifier,
    ClientSecretSigner,
    load_private_key,
)
from app.accounts.apple_tokens import AppleTokenError, AppleTokens, Grant
from app.accounts.sessions import utc_now
from app.billing.models import Entitlement
from app.billing.stripe_gateway import GatewayUnavailable

PUBLIC_BASE_URL = "https://wishlist.example.test"
REDIRECT_URI = f"{PUBLIC_BASE_URL}/api/auth/apple/callback"
TEAM_ID = "TEAM123456"
SIGNING_KEY_ID = "KEY1234567"
SIGNING_KEY = ec.generate_private_key(ec.SECP256R1())
SIGNING_PEM = SIGNING_KEY.private_bytes(
    serialization.Encoding.PEM,
    serialization.PrivateFormat.PKCS8,
    serialization.NoEncryption(),
).decode()
# As a `.env` holds it: one line, each line break written `\n`.
SIGNING_PEM_ONE_LINE = SIGNING_PEM.replace("\n", "\\n")
SIGNER = ClientSecretSigner(TEAM_ID, SIGNING_KEY_ID, SIGNING_KEY)
REVOCATION = {
    "apple_team_id": TEAM_ID,
    "apple_key_id": SIGNING_KEY_ID,
    "apple_private_key": SIGNING_PEM_ONE_LINE,
}
MAIN_LOGGER = "app.main"
SECRET_MESSAGE = "the text of an Apple message"


class FakeAppleTokens:
    """Stands in for `app.state.apple_tokens`, an AppleTokens. A code is good
    once, for the client it was issued to, as at Apple. `failure` is raised by
    every call; `on_revoke` runs inside each revocation."""

    def __init__(self) -> None:
        self.codes: dict[str, tuple[str, str]] = {}
        self.refresh_tokens: dict[str, str] = {}
        self.exchanges: list[tuple[str, str, str | None]] = []
        self.revoked: list[tuple[str, str]] = []
        self.failure: Exception | None = None
        self.on_revoke: Callable[[], None] | None = None

    def issue(self, client_id: str = SERVICES_ID, subject: str = "apple-sub-1") -> str:
        code = f"c{uuid.uuid4().hex}.0.mrst.code"
        self.codes[code] = (client_id, subject)
        self.refresh_tokens[code] = f"r{uuid.uuid4().hex}.0.mrst.refresh"
        return code

    def exchange(self, code: str, client_id: str, redirect_uri: str | None) -> Grant:
        self.exchanges.append((code, client_id, redirect_uri))
        if self.failure is not None:
            raise self.failure
        issued = self.codes.pop(code, None)
        if issued is None or issued[0] != client_id:
            raise AppleTokenError("error:invalid_grant")
        return Grant(self.refresh_tokens[code], issued[1])

    def revoke(self, refresh_token: str, client_id: str) -> None:
        self.revoked.append((refresh_token, client_id))
        if self.on_revoke is not None:
            self.on_revoke()
        if self.failure is not None:
            raise self.failure


def configure(client, fake: Any) -> Any:
    client.app.state.apple_verifier = AppleVerifier(
        [SERVICES_ID, BUNDLE_ID], FakeKeys()
    )
    client.app.state.apple_tokens = fake
    return client


@pytest.fixture
def client(make_client, clock):
    client = make_client(
        apple_client_ids=f"{SERVICES_ID},{BUNDLE_ID}",
        public_base_url=PUBLIC_BASE_URL,
        **REVOCATION,
    )
    client.app.state.clock = clock
    return client


@pytest.fixture
def apple(client) -> FakeAppleTokens:
    return configure(client, FakeAppleTokens()).app.state.apple_tokens


def stored(engine) -> list[tuple[str, str, str]]:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT user_id, client_id, refresh_token FROM apple_tokens"
                " ORDER BY client_id"
            )
        )
        return [(str(user), client_id, refresh) for user, client_id, refresh in rows]


def signed_in(response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()


def delete(client, body: dict) -> Any:
    return client.delete(
        "/api/me", headers={"Authorization": f"Bearer {body['token']}"}
    )


# The exchange at sign-in.


def test_a_web_or_android_code_is_exchanged_for_the_services_id(client, apple, engine):
    code = apple.issue()

    body = signed_in(post(client, token(), authorization_code=code))

    assert apple.exchanges == [(code, SERVICES_ID, REDIRECT_URI)]
    assert stored(engine) == [
        (body["user"]["id"], SERVICES_ID, apple.refresh_tokens[code])
    ]


def test_an_ios_code_is_exchanged_for_the_bundle_id_without_redirect(
    client, apple, engine
):
    code = apple.issue(BUNDLE_ID)

    body = signed_in(post(client, token(aud=BUNDLE_ID), authorization_code=code))

    assert apple.exchanges == [(code, BUNDLE_ID, None)]
    assert stored(engine) == [
        (body["user"]["id"], BUNDLE_ID, apple.refresh_tokens[code])
    ]


def test_a_code_from_another_client_still_signs_in(client, apple, engine, caplog):
    code = apple.issue(BUNDLE_ID)

    with caplog.at_level(logging.DEBUG):
        response = post(client, token(aud=SERVICES_ID), authorization_code=code)

    signed_in(response)
    # Sent for the client the identity token names, and refused by Apple.
    assert apple.exchanges == [(code, SERVICES_ID, REDIRECT_URI)]
    assert stored(engine) == []
    assert "reason=error:invalid_grant" in caplog.text
    assert code not in caplog.text


def test_a_code_of_another_apple_account_is_not_kept(client, apple, engine, caplog):
    code = apple.issue(subject="someone-else")

    with caplog.at_level(logging.WARNING):
        signed_in(post(client, token(), authorization_code=code))

    assert stored(engine) == []
    assert "reason=subject" in caplog.text
    assert apple.refresh_tokens[code] not in caplog.text


def test_a_replayed_code_keeps_the_first_token(client, apple, engine):
    code = apple.issue()
    first = signed_in(post(client, token(), authorization_code=code))

    signed_in(post(client, token(), authorization_code=code))

    assert stored(engine) == [
        (first["user"]["id"], SERVICES_ID, apple.refresh_tokens[code])
    ]


@pytest.mark.parametrize(
    "failure",
    [
        AppleTokenError("transport:ConnectTimeout"),
        RuntimeError(SECRET_MESSAGE),
    ],
    ids=["Apple failed", "anything else"],
)
def test_an_exchange_that_fails_still_signs_in(client, apple, engine, caplog, failure):
    apple.failure = failure
    code = apple.issue()

    with caplog.at_level(logging.DEBUG):
        body = signed_in(post(client, token(), authorization_code=code))

    assert count(engine, "users") == 1
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert stored(engine) == []
    assert "code not exchanged" in caplog.text
    assert SECRET_MESSAGE not in caplog.text
    assert code not in caplog.text


def test_without_a_code_nothing_is_exchanged(client, apple, engine):
    signed_in(post(client, token()))

    assert apple.exchanges == []
    assert stored(engine) == []


def test_a_refused_identity_token_exchanges_nothing(client, apple):
    response = post(client, token(aud="com.example.other"), authorization_code="c1")

    assert response.status_code == 401
    assert apple.exchanges == []


def test_the_token_is_replaced_at_the_next_sign_in(client, apple, engine, clock):
    first = signed_in(post(client, token(), authorization_code=apple.issue()))
    clock.advance(timedelta(days=3))
    code = apple.issue()

    signed_in(post(client, token(), authorization_code=code))

    assert stored(engine) == [
        (first["user"]["id"], SERVICES_ID, apple.refresh_tokens[code])
    ]
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT updated_at FROM apple_tokens")) == (
            clock.now
        )


def test_each_client_keeps_its_own_token(client, apple, engine):
    web = apple.issue()
    ios = apple.issue(BUNDLE_ID)
    body = signed_in(post(client, token(), authorization_code=web))

    signed_in(post(client, token(aud=BUNDLE_ID), authorization_code=ios))

    user = body["user"]["id"]
    assert stored(engine) == [
        (user, BUNDLE_ID, apple.refresh_tokens[ios]),
        (user, SERVICES_ID, apple.refresh_tokens[web]),
    ]


@pytest.mark.parametrize(
    "code",
    ["", "x" * 513, "code with spaces", "cødé", "code\n", "\ud800"],
    ids=["empty", "too long", "spaces", "not ASCII", "line break", "surrogate"],
)
def test_a_malformed_code_is_refused_without_being_echoed(client, apple, code):
    response = post(client, token(), authorization_code=code)

    assert response.status_code == 422
    assert "x" * 100 not in response.text
    assert apple.exchanges == []


def test_the_longest_code_is_taken(client, apple):
    assert post(client, token(), authorization_code="x" * 512).status_code == 200


def test_with_revocation_off_a_code_is_ignored(make_client, engine):
    client = make_client(apple_client_ids=SERVICES_ID)
    assert client.app.state.apple_tokens is None
    configure(client, None)

    signed_in(post(client, token(), authorization_code="c1"))

    assert stored(engine) == []


# The start-up.


def test_the_app_makes_a_client_only_with_everything_set(make_client):
    assert isinstance(
        make_client(apple_client_ids=SERVICES_ID, **REVOCATION).app.state.apple_tokens,
        AppleTokens,
    )
    # Without Apple sign-in, there is nothing to revoke.
    assert make_client(**REVOCATION).app.state.apple_tokens is None


@pytest.mark.parametrize(
    "overrides, named",
    [
        ({"apple_team_id": ""}, "APPLE_TEAM_ID"),
        ({"apple_key_id": " "}, "APPLE_KEY_ID"),
        ({"apple_private_key": ""}, "APPLE_PRIVATE_KEY"),
        ({"apple_private_key": "not a key"}, "APPLE_PRIVATE_KEY"),
        (
            {"apple_team_id": "", "apple_key_id": "", "apple_private_key": ""},
            "APPLE_TEAM_ID, APPLE_KEY_ID, APPLE_PRIVATE_KEY",
        ),
    ],
    ids=["team", "key id", "key", "unloadable key", "none"],
)
def test_a_gap_is_named_once_at_start(make_client, caplog, overrides, named):
    with caplog.at_level(logging.WARNING, logger=MAIN_LOGGER):
        client = make_client(apple_client_ids=SERVICES_ID, **(REVOCATION | overrides))

    assert client.app.state.apple_tokens is None
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.name == MAIN_LOGGER and "revocation" in record.getMessage()
    ]
    assert warnings == [
        f"Apple token revocation is off; missing or unloadable: {named}"
    ]
    assert SIGNING_PEM.splitlines()[1] not in caplog.text


@pytest.mark.parametrize(
    "settings",
    [
        {"apple_client_ids": SERVICES_ID, **REVOCATION},
        # Apple sign-in off: nothing to revoke, whatever is set.
        {"apple_team_id": TEAM_ID},
    ],
    ids=["everything set", "Apple sign-in off"],
)
def test_no_gap_is_logged_otherwise(make_client, caplog, settings):
    with caplog.at_level(logging.WARNING, logger=MAIN_LOGGER):
        make_client(**settings)

    assert "revocation" not in caplog.text


# The deletion.


def test_deleting_revokes_every_token_of_the_account(client, apple, engine):
    web, ios = apple.issue(), apple.issue(BUNDLE_ID)
    body = signed_in(post(client, token(), authorization_code=web))
    signed_in(post(client, token(aud=BUNDLE_ID), authorization_code=ios))
    other_code = apple.issue(subject="apple-sub-2")
    other = signed_in(
        post(client, token(sub="apple-sub-2"), authorization_code=other_code)
    )

    assert delete(client, body).status_code == 204

    assert sorted(apple.revoked) == sorted(
        [
            (apple.refresh_tokens[ios], BUNDLE_ID),
            (apple.refresh_tokens[web], SERVICES_ID),
        ]
    )
    assert [row[0] for row in stored(engine)] == [other["user"]["id"]]


def test_an_apple_failure_still_deletes(client, apple, engine, caplog):
    code = apple.issue()
    body = signed_in(post(client, token(), authorization_code=code))
    apple.failure = AppleTokenError("status:503")

    with caplog.at_level(logging.DEBUG):
        response = delete(client, body)

    assert response.status_code == 204
    assert count(engine, "users") == 0
    assert stored(engine) == []
    assert (
        f"token of account {body['user']['id']} for {SERVICES_ID} not revoked"
        " (reason=status:503)"
    ) in caplog.text
    assert apple.refresh_tokens[code] not in caplog.text


def test_with_revocation_off_a_kept_token_is_logged_and_the_account_deleted(
    client, apple, engine, caplog
):
    body = signed_in(post(client, token(), authorization_code=apple.issue()))
    client.app.state.apple_tokens = None

    with caplog.at_level(logging.WARNING):
        response = delete(client, body)

    assert response.status_code == 204
    assert count(engine, "users") == 0
    assert "not revoked (reason=off)" in caplog.text


def test_an_account_without_a_token_revokes_nothing(client, apple, engine):
    body = signed_in(post(client, token()))

    assert delete(client, body).status_code == 204
    assert apple.revoked == []


def test_tokens_are_revoked_before_any_lock(client, apple, engine):
    body = signed_in(post(client, token(), authorization_code=apple.issue()))
    locked: list[bool] = []

    def check_the_account_is_not_locked() -> None:
        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT id FROM users WHERE id = :id FOR UPDATE SKIP LOCKED"),
                {"id": body["user"]["id"]},
            ).first()
            locked.append(row is None)

    apple.on_revoke = check_the_account_is_not_locked

    assert delete(client, body).status_code == 204
    assert locked == [False]


def test_a_billing_refusal_revokes_nothing(make_client, billing_on, engine):
    client = configure(
        make_client(**billing_on, apple_client_ids=SERVICES_ID, **REVOCATION),
        FakeAppleTokens(),
    )
    apple = client.app.state.apple_tokens
    body = signed_in(post(client, token(), authorization_code=apple.issue()))
    now = utc_now()
    with Session(engine) as db, db.begin():
        db.add(
            Entitlement(
                user_id=uuid.UUID(body["user"]["id"]),
                source="stripe",
                external_id="sub_1",
                status="active",
                period_end=now + timedelta(days=30),
                cancel_at_period_end=False,
                started_at=now - timedelta(days=100),
                read_at=now,
            )
        )
    client.app.state.stripe_gateway.failures["cancel"] = GatewayUnavailable()

    response = delete(client, body)

    assert response.status_code == 502
    assert apple.revoked == []
    assert len(stored(engine)) == 1


def test_a_token_stored_during_the_deletion_is_named(client, apple, engine, caplog):
    body = signed_in(post(client, token(), authorization_code=apple.issue()))

    def a_sign_in_on_ios_meanwhile() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO apple_tokens (user_id, client_id, refresh_token,"
                    " updated_at) VALUES (:user, :client, 'late-token', now())"
                ),
                {"user": body["user"]["id"], "client": BUNDLE_ID},
            )

    apple.on_revoke = a_sign_in_on_ios_meanwhile

    with caplog.at_level(logging.WARNING):
        assert delete(client, body).status_code == 204

    assert (
        f"token of account {body['user']['id']} for {BUNDLE_ID} was stored during"
        " its deletion and not revoked"
    ) in caplog.text
    assert "late-token" not in caplog.text
    assert stored(engine) == []


# The real client, against a recording transport.


class Apple:
    """Answers each request with `status` and `body`, or raises `failure`, and
    keeps the requests."""

    def __init__(self, status: int = 200, body: Any = None) -> None:
        self.status = status
        self.body: Any = body
        self.failure: Exception | None = None
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.failure is not None:
            raise self.failure
        content = (
            self.body
            if isinstance(self.body, bytes)
            else b""
            if self.body is None
            else json.dumps(self.body).encode()
        )
        return httpx.Response(self.status, content=content)

    def tokens(self) -> AppleTokens:
        return AppleTokens(SIGNER, transport=httpx.MockTransport(self.handle))

    def form(self, index: int = 0) -> dict[str, str]:
        fields = parse_qs(self.requests[index].content.decode(), strict_parsing=True)
        return {name: values[0] for name, values in fields.items()}


def identity_token(sub: str = "apple-sub-1") -> str:
    return jwt.encode({"sub": sub, "aud": SERVICES_ID}, "x" * 32, algorithm="HS256")


def granted(sub: str = "apple-sub-1") -> dict[str, Any]:
    return {
        "access_token": "access",
        "token_type": "Bearer",
        "expires_in": 3600,
        "refresh_token": "the-refresh-token",
        "id_token": identity_token(sub),
    }


def test_the_exchange_sends_what_apple_asks_for():
    apple = Apple(body=granted())

    grant = apple.tokens().exchange("the-code", SERVICES_ID, REDIRECT_URI)

    assert grant == Grant("the-refresh-token", "apple-sub-1")
    request = apple.requests[0]
    assert (request.method, str(request.url)) == ("POST", apple_tokens.TOKEN_URL)
    assert request.headers["Content-Type"] == "application/x-www-form-urlencoded"
    form = apple.form()
    secret = form.pop("client_secret")
    assert form == {
        "client_id": SERVICES_ID,
        "code": "the-code",
        "grant_type": "authorization_code",
        "redirect_uri": REDIRECT_URI,
    }
    assert jwt.get_unverified_header(secret) == {
        "alg": "ES256",
        "kid": SIGNING_KEY_ID,
        "typ": "JWT",
    }
    claims = jwt.decode(
        secret,
        SIGNING_KEY.public_key(),
        algorithms=["ES256"],
        audience="https://appleid.apple.com",
        issuer=TEAM_ID,
    )
    assert claims["sub"] == SERVICES_ID
    assert claims["exp"] - claims["iat"] == 300


def test_a_native_code_is_exchanged_without_redirect():
    apple = Apple(body=granted())

    apple.tokens().exchange("the-code", BUNDLE_ID, None)

    assert "redirect_uri" not in apple.form()
    secret = apple.form()["client_secret"]
    assert jwt.decode(secret, options={"verify_signature": False})["sub"] == BUNDLE_ID


def test_every_call_has_timeouts():
    apple = Apple(body=granted())

    apple.tokens().exchange("the-code", SERVICES_ID, None)
    apple.tokens().revoke("the-refresh-token", SERVICES_ID)

    for request in apple.requests:
        assert request.extensions["timeout"] == {
            "connect": 5.0,
            "read": 10.0,
            "write": 10.0,
            "pool": 5.0,
        }


def test_revoking_sends_the_token_and_takes_an_empty_answer():
    apple = Apple()

    apple.tokens().revoke("the-refresh-token", BUNDLE_ID)

    assert str(apple.requests[0].url) == apple_tokens.REVOKE_URL
    form = apple.form()
    form.pop("client_secret")
    assert form == {
        "client_id": BUNDLE_ID,
        "token": "the-refresh-token",
        "token_type_hint": "refresh_token",
    }


def test_a_grant_without_an_identity_token_has_no_subject():
    answer = granted()
    del answer["id_token"]

    grant = Apple(body=answer).tokens().exchange("the-code", SERVICES_ID, None)

    assert grant.subject is None
    assert "the-refresh-token" not in repr(grant)


BAD_ANSWERS = {
    "Apple's error": (
        400,
        {"error": "invalid_grant", "error_description": SECRET_MESSAGE},
        "error:invalid_grant",
    ),
    "an unknown error": (400, {"error": SECRET_MESSAGE}, "status:400"),
    "a server error": (500, SECRET_MESSAGE.encode(), "status:500"),
    "a redirect": (302, b"", "status:302"),
    "no JSON": (200, SECRET_MESSAGE.encode(), "malformed"),
    "no object": (200, ["refresh_token"], "malformed"),
    "no refresh token": (200, {"id_token": "x"}, "no_refresh_token"),
    "a refresh token that is no text": (200, {"refresh_token": 1}, "no_refresh_token"),
    "too long": (200, b" " * (64 * 1024 + 1), "oversized"),
}


@pytest.mark.parametrize("case", BAD_ANSWERS)
def test_a_bad_answer_is_a_fixed_label(case):
    status, body, reason = BAD_ANSWERS[case]
    apple = Apple(status, body)

    with pytest.raises(AppleTokenError) as raised:
        apple.tokens().exchange("the-code", SERVICES_ID, None)

    assert raised.value.reason == reason
    assert str(raised.value) == reason
    # Nothing of Apple's chained to it, for a traceback to show.
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None or raised.value.__suppress_context__


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectTimeout(SECRET_MESSAGE),
        httpx.ReadTimeout(SECRET_MESSAGE),
        httpx.ConnectError(SECRET_MESSAGE),
    ],
)
def test_a_transport_failure_is_a_fixed_label(failure):
    apple = Apple()
    apple.failure = failure

    with pytest.raises(AppleTokenError) as raised:
        apple.tokens().revoke("the-refresh-token", SERVICES_ID)

    assert raised.value.reason == f"transport:{type(failure).__name__}"
    assert SECRET_MESSAGE not in str(raised.value)


def test_signing_in_and_deleting_through_the_real_client(client, engine, caplog):
    apple = Apple(body=granted())
    configure(client, apple.tokens())

    with caplog.at_level(logging.DEBUG):
        body = signed_in(post(client, token(), authorization_code="the-code"))
        assert stored(engine)[0][2] == "the-refresh-token"
        apple.body = None
        assert delete(client, body).status_code == 204

    assert [str(request.url) for request in apple.requests] == [
        apple_tokens.TOKEN_URL,
        apple_tokens.REVOKE_URL,
    ]
    assert apple.form(1)["token"] == "the-refresh-token"
    for secret in ("the-code", "the-refresh-token", apple.form(0)["client_secret"]):
        assert secret not in caplog.text


# The key.


def test_the_key_loads_with_its_line_breaks_or_on_one_line():
    for text_form in (SIGNING_PEM, SIGNING_PEM_ONE_LINE, f"  {SIGNING_PEM_ONE_LINE}\n"):
        key = load_private_key(text_form)
        assert key is not None
        assert key.private_numbers() == SIGNING_KEY.private_numbers()


def pem_of(key: Any) -> str:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


@pytest.mark.parametrize(
    "make",
    [
        lambda: "not a key",
        lambda: SIGNING_PEM[: len(SIGNING_PEM) // 2],
        lambda: pem_of(rsa.generate_private_key(public_exponent=65537, key_size=2048)),
        lambda: pem_of(ec.generate_private_key(ec.SECP384R1())),
    ],
    ids=["text", "cut short", "RSA", "another curve"],
)
def test_anything_but_a_p256_private_key_is_no_key(make):
    assert load_private_key(make()) is None


def test_the_signer_never_shows_its_key():
    assert "key=" not in repr(SIGNER)
