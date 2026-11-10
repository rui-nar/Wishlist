"""Signing in with an email address (sign-in plan D2, D5, D9, D10, D12, D13):
nothing reveals who has an account, a link works once, and a reset ends every
session.
"""

import json
import logging
import threading
import uuid
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session

from app.accounts import email_links, passwords
from app.accounts.models import EmailLink
from app.notifications.email_content import Digest, build_links, render

SECRET = "a-test-notification-secret"
BASE_URL = "https://wishlist.example.test"
ADDRESS = "ada@example.test"
PASSWORD = "correct horse battery"
OTHER_PASSWORD = "a different long password"
TIMEOUT_SECONDS = 30


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def empty_sign_in_tables(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE email_links, auth_throttle"))


@pytest.fixture
def client(make_client, google, clock) -> TestClient:
    client = make_client(notification_secret=SECRET, public_base_url=BASE_URL)
    client.app.state.google_verifier = google
    client.app.state.clock = clock
    return client


def count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


def link_rows(engine: Engine, address: str = ADDRESS) -> list[EmailLink]:
    with Session(engine) as db:
        return list(
            db.query(EmailLink)
            .filter(EmailLink.address == address)
            .order_by(EmailLink.created_at, EmailLink.id)
        )


def post(client: TestClient, path: str, body: dict[str, str]) -> Any:
    # As ASCII escapes, the only way a lone surrogate can arrive: httpx's own
    # JSON encoding refuses to send one, and a hostile client would not.
    return client.post(
        path,
        content=json.dumps(body),
        headers={"Content-Type": "application/json"},
    )


def start(client: TestClient, email: str = ADDRESS, language: str = "en") -> Any:
    return post(client, "/api/auth/email/start", {"email": email, "language": language})


def new_link(client: TestClient, engine: Engine, email: str = ADDRESS) -> str:
    """A token for a new link of this address, as the worker would mail it."""
    known = {row.id for row in link_rows(engine, email)}
    assert start(client, email).status_code == 202
    new = [row.id for row in link_rows(engine, email) if row.id not in known]
    assert len(new) == 1
    return email_links.make_token(SECRET, new[0])


def complete(
    client: TestClient,
    token: str,
    password: str = PASSWORD,
    display_name: str | None = "Ada",
) -> Any:
    body = {"token": token, "password": password}
    if display_name is not None:
        body["display_name"] = display_name
    return post(client, "/api/auth/email/complete", body)


def sign_in_email(
    client: TestClient, email: str = ADDRESS, password: str = PASSWORD
) -> Any:
    return post(
        client, "/api/auth/email/sign-in", {"email": email, "password": password}
    )


@pytest.fixture
def account(client, engine) -> dict:
    """An email account; returns what signing up answered."""
    response = complete(client, new_link(client, engine))
    assert response.status_code == 200, response.text
    return response.json()


def together(*calls: Callable[[], Any]) -> list[Any]:
    start_line = threading.Barrier(len(calls), timeout=TIMEOUT_SECONDS)

    def run(call: Callable[[], Any]) -> Any:
        start_line.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=TIMEOUT_SECONDS) for future in futures]


def answer(response: Any) -> tuple:
    """All a caller can tell apart, but the time."""
    return response.status_code, response.content, sorted(response.headers.items())


# Nothing reveals who has an account (D5, D10).


def test_start_answers_the_same_for_known_and_unknown_addresses(
    client, engine, account, clock
):
    # Links of one instant would come back in the order of their random ids.
    clock.advance(timedelta(seconds=1))

    known = start(client, ADDRESS)
    unknown = start(client, "nobody@example.test")

    assert known.status_code == 202
    assert answer(known) == answer(unknown)
    assert known.content == b""
    assert [row.purpose for row in link_rows(engine)] == ["create", "reset"]
    assert [row.purpose for row in link_rows(engine, "nobody@example.test")] == [
        "create"
    ]


def test_sign_in_answers_the_same_for_a_wrong_password_and_an_unknown_address(
    client, account
):
    wrong = sign_in_email(client, ADDRESS, OTHER_PASSWORD)
    unknown = sign_in_email(client, "nobody@example.test", OTHER_PASSWORD)

    assert wrong.status_code == 401
    assert answer(wrong) == answer(unknown)


def test_a_google_account_of_the_address_answers_as_an_unknown_one(
    client, sign_in, account
):
    sign_in("google-sub", email="grace@example.test")

    google = sign_in_email(client, "grace@example.test", OTHER_PASSWORD)
    unknown = sign_in_email(client, "nobody@example.test", OTHER_PASSWORD)

    assert answer(google) == answer(unknown)


def test_a_pending_link_creates_no_account(client, engine):
    assert start(client).status_code == 202

    assert count(engine, "email_links") == 1
    assert count(engine, "users") == 0
    assert count(engine, "user_identities") == 0


def test_start_is_503_when_email_is_off(make_client, engine, clock):
    for client in (make_client(), make_client(notification_secret="  ")):
        client.app.state.clock = clock
        assert start(client).status_code == 503
    no_mailer = make_client(notification_secret=SECRET)
    no_mailer.app.state.mailer = None
    assert start(no_mailer).status_code == 503
    assert count(engine, "email_links") == 0


def test_an_address_is_normalised_on_every_route(client, engine):
    token = new_link(client, engine, ADDRESS)
    assert complete(client, token).status_code == 200

    signed_in = sign_in_email(client, f"  {ADDRESS.upper()} ")

    assert signed_in.status_code == 200
    assert signed_in.json()["user"]["email"] == ADDRESS


# Creating and resetting (D2, D9).


def test_a_link_creates_the_account_and_signs_in(client, engine):
    response = complete(client, new_link(client, engine))

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == ADDRESS
    assert body["user"]["display_name"] == "Ada"
    assert client.get("/api/me", headers=auth(body["token"])).status_code == 200
    assert sign_in_email(client).status_code == 200
    assert count(engine, "password_credentials") == 1


def test_a_password_is_stored_hashed(client, engine, account):
    stored = _stored_hash(engine)
    assert PASSWORD not in stored
    assert stored.startswith("$argon2id$")


def test_a_reset_replaces_the_password_and_ends_every_session(client, engine, account):
    other = sign_in_email(client).json()["token"]

    response = complete(client, new_link(client, engine), OTHER_PASSWORD, None)

    assert response.status_code == 200
    assert response.json()["user"]["id"] == account["user"]["id"]
    # The name it had: a reset never renames.
    assert response.json()["user"]["display_name"] == "Ada"
    assert client.get("/api/me", headers=auth(account["token"])).status_code == 401
    assert client.get("/api/me", headers=auth(other)).status_code == 401
    token = response.json()["token"]
    assert client.get("/api/me", headers=auth(token)).status_code == 200
    assert sign_in_email(client, password=PASSWORD).status_code == 401
    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 200


def test_a_reset_does_not_end_another_accounts_sessions(client, engine, account):
    other = complete(
        client, new_link(client, engine, "bob@example.test"), PASSWORD, "Bob"
    ).json()

    complete(client, new_link(client, engine), OTHER_PASSWORD, None)

    assert client.get("/api/me", headers=auth(other["token"])).status_code == 200


def test_a_stale_create_link_resets_the_password_needing_no_name(
    client, engine, account
):
    stale = new_link(client, engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE email_links SET purpose = 'create'"))

    response = complete(client, stale, OTHER_PASSWORD, None)

    assert response.status_code == 200
    assert response.json()["user"]["id"] == account["user"]["id"]


def test_a_stale_reset_link_creates_the_account(client, engine):
    token = new_link(client, engine)
    with engine.begin() as connection:
        connection.execute(text("UPDATE email_links SET purpose = 'reset'"))

    response = complete(client, token, display_name=None)

    assert response.status_code == 200
    # The part before the @, when no name was chosen.
    assert response.json()["user"]["display_name"] == "ada"


def test_a_long_default_name_is_cut_to_the_limit(client, engine):
    address = f"{'a' * 150}@example.test"
    token = new_link(client, engine, address)
    with engine.begin() as connection:
        connection.execute(text("UPDATE email_links SET purpose = 'reset'"))

    response = complete(client, token, display_name=None)

    assert response.status_code == 200
    assert response.json()["user"]["display_name"] == "a" * 100


def test_a_create_link_needs_a_name_and_a_refusal_keeps_the_link(client, engine):
    token = new_link(client, engine)

    refused = complete(client, token, display_name=None)

    assert refused.status_code == 422
    assert count(engine, "users") == 0
    assert complete(client, token).status_code == 200


def test_an_email_account_stays_apart_from_a_google_one(client, engine, sign_in):
    google = sign_in("google-sub", email=ADDRESS)

    created = complete(client, new_link(client, engine)).json()

    assert created["user"]["id"] != google["user"]["id"]
    assert count(engine, "users") == 2
    assert client.get("/api/me", headers=auth(google["token"])).status_code == 200


def test_a_hash_with_old_parameters_is_replaced_at_sign_in(
    client, engine, account, monkeypatch
):
    before = _stored_hash(engine)
    monkeypatch.setattr(passwords, "needs_rehash", lambda _stored: True)

    assert sign_in_email(client).status_code == 200

    assert _stored_hash(engine) != before
    monkeypatch.undo()
    assert sign_in_email(client).status_code == 200


def _stored_hash(engine: Engine) -> str:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT password_hash FROM password_credentials"))


def test_a_sign_in_verified_before_a_reset_does_not_outlive_it(
    client, engine, account, monkeypatch
):
    # The reset commits while the sign-in is between its verification and its
    # session: a session opened by the old password would survive the reset.
    token = new_link(client, engine)
    real_verify = passwords.verify

    def verify_then_reset(stored_hash: str, password: str) -> bool:
        verified = real_verify(stored_hash, password)
        monkeypatch.setattr(passwords, "verify", real_verify)
        assert complete(client, token, OTHER_PASSWORD, None).status_code == 200
        return verified

    monkeypatch.setattr(passwords, "verify", verify_then_reset)

    assert sign_in_email(client, password=PASSWORD).status_code == 401
    assert count(engine, "sessions") == 1  # only the reset's


# Links (D8, D9).


def test_a_used_link_is_gone(client, engine):
    token = new_link(client, engine)
    assert complete(client, token).status_code == 200

    again = complete(client, token, OTHER_PASSWORD)

    assert again.status_code == 410
    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 401


def test_an_expired_link_is_gone(client, engine, clock):
    token = new_link(client, engine)
    clock.advance(timedelta(hours=1))

    assert complete(client, token).status_code == 410
    assert count(engine, "users") == 0


def test_a_link_still_works_just_before_its_hour(client, engine, clock):
    token = new_link(client, engine)
    clock.advance(timedelta(minutes=59, seconds=59))

    assert complete(client, token).status_code == 200


@pytest.mark.parametrize(
    "token",
    ["not a token", "a" * 22 + "." + "b" * 43],
    ids=["malformed", "wrong signature"],
)
def test_a_bad_token_is_the_same_gone_as_a_used_one(client, engine, token):
    used = new_link(client, engine)
    complete(client, used)

    assert answer(complete(client, token)) == answer(complete(client, used))


def test_a_signed_token_of_no_link_is_gone(client):
    token = email_links.make_token(SECRET, uuid.uuid4())

    assert complete(client, token).status_code == 410


def test_without_a_secret_no_token_is_read(make_client, clock):
    client = make_client(notification_secret="   ")
    client.app.state.clock = clock
    token = email_links.make_token("   ", uuid.uuid4())

    assert complete(client, token).status_code == 410


def test_a_second_pending_link_is_dead_once_the_first_created_the_account(
    client, engine
):
    first = new_link(client, engine)
    second = new_link(client, engine)
    assert complete(client, first).status_code == 200

    assert complete(client, second, OTHER_PASSWORD).status_code == 410
    assert sign_in_email(client, password=PASSWORD).status_code == 200
    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 401


def test_a_second_pending_link_is_dead_once_the_first_reset_the_password(
    client, engine, account
):
    first = new_link(client, engine)
    second = new_link(client, engine)
    assert complete(client, first, OTHER_PASSWORD, None).status_code == 200

    assert complete(client, second, PASSWORD, None).status_code == 410
    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 200


def test_another_addresss_link_stays_alive(client, engine, account):
    other = new_link(client, engine, "bob@example.test")

    complete(client, new_link(client, engine), OTHER_PASSWORD, None)

    assert complete(client, other, PASSWORD, "Bob").status_code == 200


def test_a_link_is_single_use_under_two_concurrent_uses(client, engine):
    token = new_link(client, engine)

    responses = together(
        lambda: complete(client, token),
        lambda: complete(client, token, OTHER_PASSWORD),
    )

    assert sorted(r.status_code for r in responses) == [200, 410]
    assert count(engine, "users") == 1
    assert count(engine, "sessions") == 1


def test_two_first_uses_of_two_links_make_one_account(client, engine):
    first = new_link(client, engine)
    second = new_link(client, engine)

    responses = together(
        lambda: complete(client, first),
        lambda: complete(client, second, OTHER_PASSWORD),
    )

    assert sorted(r.status_code for r in responses) == [200, 410]
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1
    assert count(engine, "password_credentials") == 1
    assert count(engine, "sessions") == 1


# Limits (D12).


def other_ip(client: TestClient, ip: str) -> TestClient:
    return TestClient(client.app, client=(ip, 50000))


def test_start_stays_202_over_the_address_limit_and_adds_no_row(client, engine, caplog):
    with caplog.at_level(logging.WARNING, logger="app.accounts.email_router"):
        answers = [start(client) for _ in range(4)]

    assert [r.status_code for r in answers] == [202] * 4
    assert answer(answers[0]) == answer(answers[3])
    assert count(engine, "email_links") == 3
    messages = [record.getMessage() for record in caplog.records]
    assert messages == ["email_start_address_limited"]
    assert ADDRESS not in " ".join(messages)


def test_start_over_the_ip_limit_is_429(client, engine):
    for number in range(20):
        assert start(client, f"user{number}@example.test").status_code == 202

    refused = start(client, ADDRESS)

    assert refused.status_code == 429
    assert refused.json() == {"detail": "too_many_attempts"}
    assert link_rows(engine) == []


def test_an_ip_refusal_does_not_use_up_the_addresss_quota(client, engine):
    for number in range(20):
        start(client, f"user{number}@example.test")
    # Three refused attempts: were they counted, the address's quota would be
    # gone for the next IP.
    for _ in range(3):
        assert start(client, ADDRESS).status_code == 429

    assert start(other_ip(client, "203.0.113.9"), ADDRESS).status_code == 202
    assert len(link_rows(engine)) == 1


def test_sign_in_is_limited_per_address_and_ip_together(client, account):
    for _ in range(10):
        assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 401

    refused = sign_in_email(client)

    assert refused.status_code == 429
    assert refused.json() == {"detail": "too_many_attempts"}
    # An address alone is never limited: nobody can lock its owner out.
    assert sign_in_email(other_ip(client, "203.0.113.9")).status_code == 200
    # Nor another address from this IP.
    assert sign_in_email(client, "bob@example.test", OTHER_PASSWORD).status_code == 401


def test_sign_in_is_limited_per_ip(client):
    for number in range(100):
        response = sign_in_email(client, f"user{number}@example.test")
        assert response.status_code == 401

    assert sign_in_email(client, ADDRESS).status_code == 429


def test_complete_is_limited_per_ip(client, engine, account):
    for _ in range(19):
        assert complete(client, "not a token").status_code == 410

    assert complete(client, "not a token").status_code == 429
    # The token of a good link gets the same answer.
    token = new_link(client, engine)
    assert complete(client, token, OTHER_PASSWORD, None).status_code == 429
    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 401


def test_a_window_over_lets_attempts_through_again(client, clock):
    for _ in range(11):
        sign_in_email(client, password=OTHER_PASSWORD)

    clock.advance(timedelta(minutes=15))

    assert sign_in_email(client, password=OTHER_PASSWORD).status_code == 401


# What a request may hold (D4, D11, D13).


HOSTILE_NAMES = {
    "blank": "   ",
    "too long": "a" * 101,
    "a newline": "a\nb",
    "a tab": "a\tb",
    "a nul": "a\x00b",
    "c1": "a\x85b",
    "a line separator": "a b",
    "a paragraph separator": "a b",
    "a bidi override": "a‮b",
    "a bidi isolate": "a⁦b",
    "a lone surrogate": "a\ud800b",
}


@pytest.mark.parametrize("name", HOSTILE_NAMES.values(), ids=HOSTILE_NAMES.keys())
def test_a_hostile_name_is_refused_and_keeps_the_link(client, engine, name):
    token = new_link(client, engine)

    assert complete(client, token, display_name=name).status_code == 422

    assert count(engine, "users") == 0
    assert complete(client, token).status_code == 200


def test_a_name_is_trimmed_and_may_hold_joiners(client, engine):
    response = complete(client, new_link(client, engine), display_name="  Zoé‍ ")

    assert response.json()["user"]["display_name"] == "Zoé‍"


def test_a_name_that_is_html_comes_out_escaped_in_an_email(client, engine):
    hostile = '<script>alert("x")</script>'
    name = complete(client, new_link(client, engine), display_name=hostile).json()[
        "user"
    ]["display_name"]
    assert name == hostile

    links = build_links(BASE_URL, uuid.uuid4(), uuid.uuid4(), "v1.a.b")
    message = render(
        Digest(
            recipient_name=name,
            language="en",
            occasion_name="Birthday",
            gift_title="Scarf",
            links=links,
            comments=(),
            participants_left=(name,),
        )
    )

    assert "<script>" not in message.html
    assert "&lt;script&gt;" in message.html


@pytest.mark.parametrize(
    "password",
    ["short", "a" * 129, "a\ud800" * 10],
    ids=["too short", "too long", "a lone surrogate"],
)
def test_a_refused_password_keeps_the_link(client, engine, password):
    token = new_link(client, engine)

    assert complete(client, token, password=password).status_code == 422

    assert complete(client, token).status_code == 200


@pytest.mark.parametrize(
    "address",
    ["not-an-address", "a@b@c", "a b@c", "a\x00@b", "a\ud800@b", f"{'a' * 255}@b"],
)
def test_a_malformed_address_is_refused(client, engine, address):
    assert start(client, address).status_code == 422
    assert sign_in_email(client, address).status_code == 422
    assert count(engine, "email_links") == 0


def test_an_unknown_language_is_refused(client, engine):
    assert start(client, language="de").status_code == 422
    assert count(engine, "email_links") == 0


def test_no_log_line_names_a_person(client, engine, caplog):
    with caplog.at_level(logging.DEBUG, logger="app"):
        token = new_link(client, engine)
        complete(client, token)
        sign_in_email(client)
        sign_in_email(client, password=OTHER_PASSWORD)
        complete(client, token)

    text_of_logs = " ".join(record.getMessage() for record in caplog.records)
    for secret in (ADDRESS, PASSWORD, OTHER_PASSWORD, token, "Ada"):
        assert secret not in text_of_logs


# An account's deletion (Boundaries crossed).


def test_deleting_an_email_account_deletes_its_links_and_credential(
    client, engine, account
):
    new_link(client, engine)
    new_link(client, engine, "bob@example.test")

    response = client.delete("/api/me", headers=auth(account["token"]))

    assert response.status_code == 204
    assert link_rows(engine) == []
    assert len(link_rows(engine, "bob@example.test")) == 1
    assert count(engine, "password_credentials") == 0
    assert count(engine, "users") == 0


def test_deleting_a_google_account_leaves_the_links_of_its_address(
    client, engine, sign_in
):
    google = sign_in("google-sub", email=ADDRESS)
    new_link(client, engine)

    client.delete("/api/me", headers=auth(google["token"]))

    assert len(link_rows(engine)) == 1


def test_a_link_of_a_deleted_account_is_gone(client, engine, account):
    token = new_link(client, engine)
    client.delete("/api/me", headers=auth(account["token"]))

    assert complete(client, token).status_code == 410
