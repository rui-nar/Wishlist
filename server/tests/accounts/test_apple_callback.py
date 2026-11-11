"""POST /api/auth/apple/callback: Apple's form handed to the Android app, and
nothing else (sign-in plan D16)."""

import logging
from urllib.parse import parse_qsl, urlencode

import pytest
from sqlalchemy import text

PACKAGE = "com.example.shushgift"
CALLBACK = "/api/auth/apple/callback"
FRAGMENT = f"Intent;package={PACKAGE};scheme=signinwithapple;end"
BAD_CALLBACK = {"detail": "Malformed Apple callback"}


class NeverCalled:
    def verify(self, id_token: str, nonce: str) -> None:
        raise AssertionError("the callback verifies nothing")


@pytest.fixture
def callback_client(make_client):
    client = make_client(apple_android_package=f" {PACKAGE} ")
    client.app.state.apple_verifier = NeverCalled()
    return client


def post(client, form: bytes):
    return client.post(
        CALLBACK,
        content=form,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        follow_redirects=False,
    )


def row_counts(engine) -> list[int]:
    with engine.connect() as connection:
        return [
            connection.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("users", "user_identities", "sessions", "auth_throttle")
        ]


def test_the_form_goes_to_the_configured_package(callback_client, engine, caplog):
    before = row_counts(engine)
    form = {
        "code": "a-code",
        "id_token": "a.token.value",
        "state": "s",
        "user": '{"a":1}',
    }

    with caplog.at_level(logging.DEBUG, logger="app"):
        response = post(callback_client, urlencode(form).encode())

    assert response.status_code == 303
    assert response.headers["location"] == (
        "intent://callback?code=a-code&id_token=a.token.value&state=s"
        f"&user=%7B%22a%22%3A1%7D#{FRAGMENT}"
    )
    assert row_counts(engine) == before
    assert "a.token.value" not in caplog.text


@pytest.mark.parametrize(
    "value",
    [
        "x#Intent;package=com.evil;scheme=evil;end",
        "x;package=com.evil",
        "x&code=other",
        "x\r\nLocation: https://evil.example",
        "x\x00y",
        '"><script>',
        "a b+c%20d",
        "é",
    ],
)
@pytest.mark.parametrize("where", ["value", "name"])
def test_a_hostile_field_cannot_leave_the_query(callback_client, value, where):
    pair = ("state", value) if where == "value" else (value, "1")

    response = post(callback_client, urlencode([pair]).encode())

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("intent://callback?")
    assert location.count("#") == 1
    query, fragment = location.removeprefix("intent://callback?").split("#")
    assert fragment == FRAGMENT
    assert not set(query) & set(';\r\n\x00 "<>')
    # And it arrives as it was sent.
    assert parse_qsl(query, strict_parsing=True) == [pair]


def test_every_field_is_kept_in_its_order(callback_client):
    response = post(callback_client, b"z=1&a=&z=2")

    location = response.headers["location"]
    assert location == f"intent://callback?z=1&a=&z=2#{FRAGMENT}"


@pytest.mark.parametrize(
    "form",
    [
        b"",
        b"no-equals-sign",
        b"state=%ff",
        b"\xff=1",
        b"a=1;b=2&",
        b"&".join([b"a=1"] * 17),
    ],
    ids=["empty", "not a form", "bad escape", "bad bytes", "stray end", "many fields"],
)
def test_a_malformed_form_is_refused(callback_client, form):
    response = post(callback_client, form)

    assert response.status_code == 400
    assert response.json() == BAD_CALLBACK
    assert "location" not in response.headers


def test_an_oversized_form_is_refused(callback_client):
    response = post(callback_client, b"state=" + b"x" * (8 * 1024))

    assert response.status_code == 400
    assert response.json() == BAD_CALLBACK
    assert "x" * 100 not in response.text


def test_an_oversized_stream_without_a_length_is_refused(callback_client):
    def stream():
        for _ in range(9):
            yield b"x" * 1024

    response = callback_client.post(CALLBACK, content=stream(), follow_redirects=False)

    assert response.status_code == 400
    assert response.json() == BAD_CALLBACK


@pytest.mark.parametrize("package", ["", "   "])
def test_no_package_means_no_redirect(make_client, package):
    client = make_client(apple_android_package=package)

    response = post(client, b"code=a-code")

    assert response.status_code == 503
    assert response.json() == {"detail": "Apple sign-in is not configured"}
    assert "location" not in response.headers
