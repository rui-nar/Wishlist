import logging

import pytest
from sqlalchemy import text

from app.accounts.sessions import hash_token
from app.main import _log_email_sign_in_gap
from app.settings import Settings


def count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


def test_config_gives_the_web_client_id(make_client):
    client = make_client(google_client_ids=" web-id , android-id ")

    response = client.get("/api/config")

    assert response.status_code == 200
    assert response.json() == {
        "google_client_id": "web-id",
        "public_base_url": None,
        "apple_client_id": None,
        "apple_redirect_uri": None,
        "email_sign_in": False,
    }


def test_config_without_google(make_client):
    response = make_client(google_client_ids="").get("/api/config")

    assert response.json() == {
        "google_client_id": None,
        "public_base_url": None,
        "apple_client_id": None,
        "apple_redirect_uri": None,
        "email_sign_in": False,
    }


def test_config_gives_the_apple_client_id(make_client):
    client = make_client(apple_client_ids=" services-id , bundle-id ")

    assert client.get("/api/config").json()["apple_client_id"] == "services-id"


def test_config_gives_the_apple_redirect_uri(make_client):
    client = make_client(public_base_url=" https://shushgift.example.com/ ")

    assert (
        client.get("/api/config").json()["apple_redirect_uri"]
        == "https://shushgift.example.com/api/auth/apple/callback"
    )


def test_config_offers_email_sign_in_with_a_mailer_and_a_secret(make_client):
    client = make_client(notification_secret="a-secret")

    assert client.get("/api/config").json()["email_sign_in"] is True


def test_config_does_not_offer_email_sign_in_without_a_mailer(make_client):
    client = make_client(notification_secret="a-secret")
    client.app.state.mailer = None

    assert client.get("/api/config").json()["email_sign_in"] is False


def test_config_does_not_offer_email_sign_in_without_a_secret(make_client):
    client = make_client(notification_secret=" ")

    assert client.get("/api/config").json()["email_sign_in"] is False


EMAIL_ON = {
    "brevo_api_key": "a-key",
    "email_sender_address": "sender@example.test",
    "notification_secret": "a-secret",
    "public_base_url": "https://shushgift.example.test",
}
EMAIL_OFF = dict.fromkeys(EMAIL_ON, "")
WORKER_OFF_WARNING = "NOTIFICATIONS_WORKER is off"


def test_starting_with_email_sign_in_and_no_worker_warns(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        make_client(notifications_worker=False, **EMAIL_ON)

    assert WORKER_OFF_WARNING in caplog.text
    assert EMAIL_ON["brevo_api_key"] not in caplog.text


@pytest.mark.parametrize(
    "values", [{**EMAIL_ON, "notifications_worker": True}, EMAIL_OFF]
)
def test_no_warning_when_the_links_can_go_or_none_are_made(values, caplog):
    settings = Settings(database_url="postgresql+psycopg://x:y@localhost/z", **values)

    with caplog.at_level(logging.WARNING, logger="app.main"):
        _log_email_sign_in_gap(settings)

    assert WORKER_OFF_WARNING not in caplog.text


def test_config_gives_the_share_links_base_url(make_client):
    # Share links are <base>/join#<token> (lists plan D5): no trailing slash.
    client = make_client(public_base_url=" https://shushgift.example.com/ ")

    response = client.get("/api/config")

    assert response.json()["public_base_url"] == "https://shushgift.example.com"


def test_first_sign_in_creates_one_user_and_a_working_token(client, google, engine):
    id_token = google.issue("sub-1", "ada@example.com", "Ada")

    response = client.post("/api/auth/google", json={"id_token": id_token})

    assert response.status_code == 200
    body = response.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["user"]["display_name"] == "Ada"
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1
    me = client.get("/api/me", headers={"Authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json() == body["user"] | {"is_admin": False}


def test_second_sign_in_finds_the_same_user_and_refreshes_it(sign_in, client, engine):
    first = sign_in("sub-1", "old@example.com", "Old name")

    second = sign_in("sub-1", "new@example.com", "New name")

    assert second["user"] == {
        "id": first["user"]["id"],
        "email": "new@example.com",
        "display_name": "New name",
    }
    assert second["token"] != first["token"]
    assert count(engine, "users") == 1
    for token in (first["token"], second["token"]):
        me = client.get("/api/me", headers={"Authorization": f"Bearer {token}"})
        assert me.json()["email"] == "new@example.com"


def test_a_user_is_found_by_google_sub_never_by_email(sign_in, engine):
    first = sign_in("sub-1", "shared@example.com")

    second = sign_in("sub-2", "shared@example.com")

    assert second["user"]["id"] != first["user"]["id"]
    assert count(engine, "users") == 2


def test_an_invalid_token_is_refused_with_a_fixed_body(client, engine):
    response = client.post("/api/auth/google", json={"id_token": "made-up"})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Google ID token"}
    assert count(engine, "users") == 0


def test_a_refused_token_never_reaches_the_log_or_the_body(client, google_keys, caplog):
    # Through the real verifier: a well-formed token with a wrong signature.
    client.app.state.google_verifier = google_keys.verifier()
    forged = google_keys.token()[:-8] + "AAAAAAAA"

    with caplog.at_level(logging.DEBUG):
        response = client.post("/api/auth/google", json={"id_token": forged})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Google ID token"}
    assert "Google ID token refused" in caplog.text
    assert forged not in caplog.text
    for segment in forged.split("."):
        assert segment not in caplog.text


def test_an_unverified_email_is_refused(client, google_keys, engine):
    client.app.state.google_verifier = google_keys.verifier()
    id_token = google_keys.token(email_verified=False)

    response = client.post("/api/auth/google", json={"id_token": id_token})

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid Google ID token"}
    assert count(engine, "users") == 0


def test_a_valid_token_signs_in_through_the_real_verifier(client, google_keys):
    client.app.state.google_verifier = google_keys.verifier()

    response = client.post(
        "/api/auth/google", json={"id_token": google_keys.token(sub="real-sub")}
    )

    assert response.status_code == 200
    assert response.json()["user"]["email"] == "ada@example.com"


def test_google_not_configured_answers_503(make_client):
    client = make_client(google_client_ids="")

    response = client.post("/api/auth/google", json={"id_token": "anything"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Google sign-in is not configured"}


def test_an_oversized_id_token_is_refused_without_being_echoed(client):
    id_token = "x" * (4 * 1024 + 1)

    response = client.post("/api/auth/google", json={"id_token": id_token})

    assert response.status_code == 422
    assert "x" * 100 not in response.text


def test_the_database_stores_no_raw_token(sign_in, engine):
    token = sign_in()["token"]

    with engine.connect() as connection:
        rows = connection.scalars(text("SELECT CAST(s AS text) FROM sessions s"))
        stored = " ".join(rows)
    assert token not in stored
    assert hash_token(token) in stored
