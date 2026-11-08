"""The real GoogleVerifier, against tokens signed by a local key (GoogleKeys)."""

import logging
import time

import pytest
from google.oauth2.id_token import verify_oauth2_token

from app.accounts.google import GoogleIdentity, InvalidGoogleToken

ANDROID_CLIENT_ID = "android-client.apps.googleusercontent.com"


def refusal_reason(verifier, token: str) -> str:
    with pytest.raises(InvalidGoogleToken) as refused:
        verifier.verify(token)
    return refused.value.reason


def test_a_valid_token_gives_the_identity(google_keys):
    identity = google_keys.verifier().verify(google_keys.token())

    assert identity == GoogleIdentity(
        sub="google-sub-1", email="ada@example.com", name="Ada Lovelace"
    )


def test_any_configured_audience_is_accepted(google_keys):
    verifier = google_keys.verifier([google_keys.CLIENT_ID, ANDROID_CLIENT_ID])

    identity = verifier.verify(google_keys.token(aud=ANDROID_CLIENT_ID))

    assert identity.sub == "google-sub-1"


def test_another_audience_is_refused(google_keys):
    token = google_keys.token(aud="someone-else.apps.googleusercontent.com")

    assert refusal_reason(google_keys.verifier(), token) == "audience"


def test_an_expired_token_is_refused(google_keys):
    now = int(time.time())
    token = google_keys.token(iat=now - 7200, exp=now - 3600)

    assert refusal_reason(google_keys.verifier(), token) == "expired"


def test_a_token_from_another_issuer_is_refused(google_keys):
    token = google_keys.token(iss="https://evil.example")

    assert refusal_reason(google_keys.verifier(), token) == "issuer"


def test_an_unverified_email_is_refused(google_keys):
    token = google_keys.token(email_verified=False)

    assert refusal_reason(google_keys.verifier(), token) == "email_not_verified"


def test_a_missing_name_falls_back_to_the_email_local_part(google_keys):
    identity = google_keys.verifier().verify(google_keys.token(name=""))

    assert identity.name == "ada"


def test_the_log_carries_neither_the_token_nor_the_exception_text(google_keys, caplog):
    # google-auth quotes a malformed token in its message.
    token = "not-a-jwt-but-a-secret-value"
    with pytest.raises(ValueError) as original:
        verify_oauth2_token(token, google_keys, google_keys.CLIENT_ID)
    assert token in str(original.value)

    with caplog.at_level(logging.WARNING):
        reason = refusal_reason(google_keys.verifier(), token)

    assert reason == "malformed"
    assert "reason=malformed" in caplog.text
    assert token not in caplog.text
    assert str(original.value) not in caplog.text
