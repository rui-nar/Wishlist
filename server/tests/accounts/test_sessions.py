import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User

NOT_SIGNED_IN = {"detail": "Not signed in"}


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def stored_expiry(engine, token: str):
    with engine.connect() as connection:
        return connection.scalar(
            text("SELECT expires_at FROM sessions WHERE token_hash = :hash"),
            {"hash": sessions.hash_token(token)},
        )


def assert_not_signed_in(response) -> None:
    assert response.status_code == 401
    assert response.json() == NOT_SIGNED_IN
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "Bearer"},
        {"Authorization": "bearer-without-scheme"},
        {"Authorization": "Bearer unknown-token"},
    ],
    ids=["missing", "other scheme", "no token", "malformed", "unknown"],
)
def test_a_request_without_a_valid_session_gets_the_same_401(client, headers):
    assert_not_signed_in(client.get("/api/me", headers=headers))


def test_an_expired_session_gets_the_same_401(client, sign_in, clock):
    token = sign_in()["token"]

    clock.advance(sessions.LIFETIME + timedelta(seconds=1))

    assert_not_signed_in(client.get("/api/me", headers=auth(token)))


def test_a_refused_bearer_token_never_reaches_the_log_or_the_body(
    client, sign_in, clock, caplog
):
    unknown = "unknown-token-a-secret-value"
    expired = sign_in()["token"]
    clock.advance(sessions.LIFETIME + timedelta(seconds=1))

    with caplog.at_level(logging.DEBUG):
        responses = [
            client.get("/api/me", headers=auth(token)) for token in (unknown, expired)
        ]

    for response, token in zip(responses, (unknown, expired), strict=True):
        assert_not_signed_in(response)
        assert token not in response.text
        assert token not in caplog.text


def test_a_session_is_used_until_90_days_after_its_last_use(client, sign_in, clock):
    token = sign_in()["token"]

    # Used every 80 days: never more than 90 days apart, so it lives on.
    for _ in range(3):
        clock.advance(timedelta(days=80))
        assert client.get("/api/me", headers=auth(token)).status_code == 200


def test_two_requests_an_hour_apart_move_the_expiry_in_the_database(
    client, sign_in, clock, engine
):
    # Through the request path: GET /api/me writes nothing itself, so the touch
    # is kept only because the request's unit of work is committed (R1-2).
    token = sign_in()["token"]
    signed_in_expiry = stored_expiry(engine, token)

    clock.advance(timedelta(minutes=30))
    client.get("/api/me", headers=auth(token))
    assert stored_expiry(engine, token) == signed_in_expiry

    clock.advance(timedelta(minutes=31))
    client.get("/api/me", headers=auth(token))
    assert stored_expiry(engine, token) == clock.now + sessions.LIFETIME
    assert stored_expiry(engine, token) > signed_in_expiry


@pytest.fixture
def db(engine):
    with Session(engine) as db:
        yield db
        db.rollback()


@pytest.fixture
def user_id(db) -> uuid.UUID:
    user = User(email="a@example.com", display_name="A")
    db.add(user)
    db.flush()
    return user.id


def test_find_refuses_an_expired_session(db, user_id, clock):
    token = sessions.create(db, user_id, clock.now)

    assert sessions.find(db, token, clock.now + sessions.LIFETIME) is None
    assert sessions.find(db, token, clock.now + sessions.LIFETIME / 2) is not None


def test_touch_moves_the_expiry_at_most_once_per_hour(db, user_id, clock):
    token = sessions.create(db, user_id, clock.now)
    session = sessions.find(db, token, clock.now)
    created_expiry = session.expires_at

    sessions.touch(session, clock.now + timedelta(minutes=59))
    assert session.expires_at == created_expiry

    later = clock.now + sessions.TOUCH_INTERVAL
    sessions.touch(session, later)
    assert session.last_used_at == later
    assert session.expires_at == later + sessions.LIFETIME

    sessions.touch(session, later + timedelta(minutes=59))
    assert session.expires_at == later + sessions.LIFETIME


def test_sign_out_deletes_only_that_session(client, sign_in, engine):
    first = sign_in()["token"]
    second = sign_in()["token"]

    response = client.post("/api/auth/sign-out", headers=auth(first))

    assert response.status_code == 204
    assert_not_signed_in(client.get("/api/me", headers=auth(first)))
    assert client.get("/api/me", headers=auth(second)).status_code == 200
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM sessions")) == 1


def test_sign_out_needs_a_session(client):
    assert_not_signed_in(client.post("/api/auth/sign-out"))
