"""The unsubscribe token and its route, which needs no session (comments plan
D18)."""

import logging
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import text

from app.notifications.unsubscribe import make_token, read_token

NOT_FOUND = {"detail": "Not found"}
BASE64URL = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


def url(token: str) -> str:
    return f"/api/unsubscribe/{token}"


def is_on(client, account) -> bool:
    response = client.get("/api/me/preferences", headers=account.headers)
    return response.json()["email_notifications"]


def answer(response) -> tuple:
    """A response, whole, but for the moment it was sent."""
    headers = sorted(
        (name.lower(), value)
        for name, value in response.headers.items()
        if name.lower() != "date"
    )
    return response.status_code, headers, response.content


def with_character(value: str, index: int, change: Callable[[int], int]) -> str:
    """`value` with one base64url character moved in the alphabet."""
    index %= len(value)
    moved = BASE64URL[change(BASE64URL.index(value[index])) % len(BASE64URL)]
    return value[:index] + moved + value[index + 1 :]


def test_the_format_of_links_already_sent_does_not_change():
    """Computed apart, with openssl: every email ever sent carries this
    format (D18)."""
    user_id = uuid.UUID("12345678-1234-5678-1234-567812345678")

    assert make_token("secret", user_id) == (
        "v1.EjRWeBI0VngSNFZ4EjRWeA.m77vJJGuHJ5yYEDtNTz8mgnJmDmJ6Ua2wfzjLwDwFsk"
    )


def test_a_token_reads_back_as_its_account(secret):
    user_id = uuid.uuid4()

    assert read_token(secret, make_token(secret, user_id)) == user_id


def test_a_valid_token_turns_email_off_without_a_session(client, make_account, secret):
    account = make_account()

    response = client.post(url(make_token(secret, account.id)))

    assert response.status_code == 204
    assert response.content == b""
    assert is_on(client, account) is False


def test_a_token_is_good_twice(client, make_account, secret):
    account = make_account()
    token = make_token(secret, account.id)

    assert client.post(url(token)).status_code == 204
    assert client.post(url(token)).status_code == 204
    assert is_on(client, account) is False


def test_an_old_link_works_after_the_switch_is_turned_back_on(
    client, make_account, secret
):
    account = make_account()
    token = make_token(secret, account.id)
    client.post(url(token))
    client.patch(
        "/api/me/preferences",
        headers=account.headers,
        json={"email_notifications": True},
    )

    assert client.post(url(token)).status_code == 204
    assert is_on(client, account) is False


def test_a_token_speaks_for_its_own_account_only(client, make_account, secret):
    account, signed_in = make_account(), make_account()

    response = client.post(
        url(make_token(secret, account.id)), headers=signed_in.headers
    )

    assert response.status_code == 204
    assert is_on(client, account) is False
    assert is_on(client, signed_in) is True


def test_a_deleted_accounts_token_is_answered_as_any_other(
    client, make_account, secret
):
    existing, deleted = make_account(), make_account()
    token = make_token(secret, deleted.id)
    assert client.delete("/api/me", headers=deleted.headers).status_code == 204

    for_deleted = client.post(url(token))
    for_existing = client.post(url(make_token(secret, existing.id)))

    assert for_deleted.status_code == 204
    assert answer(for_deleted) == answer(for_existing)


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "content": b"List-Unsubscribe=One-Click",
            "headers": {"Content-Type": "application/x-www-form-urlencoded"},
        },
        {"content": b"{not json", "headers": {"Content-Type": "application/json"}},
        {"json": {"anything": ["at", "all"]}},
    ],
    ids=["RFC 8058 form", "broken JSON", "JSON"],
)
def test_any_body_is_accepted(client, make_account, secret, kwargs):
    account = make_account()

    response = client.post(url(make_token(secret, account.id)), **kwargs)

    assert response.status_code == 204
    assert is_on(client, account) is False


def test_opening_the_link_unsubscribes_no_one(client, make_account, secret):
    """Mail security scanners open links (D18)."""
    account = make_account()

    response = client.get(url(make_token(secret, account.id)))

    assert response.status_code == 405
    assert is_on(client, account) is True


def part(token: str, index: int) -> str:
    return token.split(".")[index]


FORGERIES: dict[str, Callable[[str], str]] = {
    "another version": lambda t: "v2" + t[2:],
    "no version": lambda t: t[3:],
    "upper case version": lambda t: "V1" + t[2:],
    "changed signature": lambda t: (
        f"v1.{part(t, 1)}.{with_character(part(t, 2), 0, lambda c: c ^ 1)}"
    ),
    # The last character of each part has bits base64 does not use: flipping
    # one decodes to the same bytes.
    "unused bits of the signature": lambda t: (
        f"v1.{part(t, 1)}.{with_character(part(t, 2), -1, lambda c: c ^ 1)}"
    ),
    "unused bits of the user id": lambda t: (
        f"v1.{with_character(part(t, 1), -1, lambda c: c ^ 1)}.{part(t, 2)}"
    ),
    "changed user id": lambda t: (
        f"v1.{with_character(part(t, 1), 0, lambda c: c ^ 1)}.{part(t, 2)}"
    ),
    "signature cut short": lambda t: t[:-1],
    "signature too long": lambda t: t + "A",
    "user id cut short": lambda t: f"v1.{part(t, 1)[:-1]}.{part(t, 2)}",
    "padded signature": lambda t: t + "=",
    "extra part": lambda t: t + ".AAAA",
    "no signature": lambda t: f"v1.{part(t, 1)}",
    "empty signature": lambda t: f"v1.{part(t, 1)}.",
    "not base64": lambda t: f"v1.{'!' * 22}.{'!' * 43}",
    "not ascii": lambda t: f"v1.{'é' * 22}.{'é' * 43}",
    "line feed at the end": lambda t: t + "%0A",
    "not a token at all": lambda t: "hello",
}


@pytest.mark.parametrize("forge", FORGERIES.values(), ids=FORGERIES.keys())
def test_a_forged_token_is_a_404_and_changes_nothing(
    client, make_account, secret, forge
):
    account = make_account()

    response = client.post(url(forge(make_token(secret, account.id))))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert is_on(client, account) is True


def test_the_signature_of_one_account_does_not_open_another(
    client, make_account, secret
):
    account, target = make_account(), make_account()
    signature = part(make_token(secret, account.id), 2)
    forged = f"v1.{part(make_token(secret, target.id), 1)}.{signature}"

    assert client.post(url(forged)).status_code == 404
    assert is_on(client, target) is True


def test_a_token_of_another_secret_is_a_404(client, make_account):
    account = make_account()

    assert client.post(url(make_token("other", account.id))).status_code == 404
    assert is_on(client, account) is True


@pytest.mark.parametrize("signed_with", ["", "a-test-notification-secret"])
def test_without_a_secret_every_token_is_a_404(make_client, make_account, signed_with):
    client = make_client(notification_secret="")
    account = make_account()

    response = client.post(url(make_token(signed_with, account.id)))

    assert response.status_code == 404
    assert response.json() == NOT_FOUND
    assert is_on(client, account) is True


def test_a_refused_token_never_reaches_the_log_or_the_body(client, caplog):
    token = "not-a-token-a-secret-value"

    with caplog.at_level(logging.DEBUG, logger="app"):
        response = client.post(url(token))

    assert response.status_code == 404
    assert token not in response.text
    assert token not in caplog.text


def test_the_route_changes_the_switch_and_nothing_else(
    client, make_account, secret, engine
):
    account = make_account()

    def stored() -> tuple:
        with engine.connect() as connection:
            return tuple(
                connection.execute(
                    text("SELECT * FROM users WHERE id = :id"), {"id": account.id}
                ).one()
            )

    before = stored()
    client.post(url(make_token(secret, account.id)))

    changed = {index for index, value in enumerate(stored()) if value != before[index]}
    assert len(changed) == 1
