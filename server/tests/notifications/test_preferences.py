"""The email switch and the language of an account (comments plan D17, D18)."""

import pytest

PATH = "/api/me/preferences"
DEFAULTS = {"email_notifications": True, "language": "en"}
NOT_SIGNED_IN = {"detail": "Not signed in"}


def preferences(client, account) -> dict:
    response = client.get(PATH, headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_an_account_starts_opted_in_and_in_english(client, make_account):
    assert preferences(client, make_account()) == DEFAULTS


@pytest.mark.parametrize(
    "change",
    [
        {"email_notifications": False},
        {"language": "fr"},
        {"email_notifications": False, "language": "fr"},
    ],
    ids=["switch", "language", "both"],
)
def test_a_patch_changes_what_it_names_and_answers_as_a_get(
    client, make_account, change
):
    account = make_account()

    response = client.patch(PATH, headers=account.headers, json=change)

    assert response.status_code == 200, response.text
    assert response.json() == DEFAULTS | change
    assert preferences(client, account) == DEFAULTS | change


def test_the_switch_turns_back_on(client, make_account):
    account = make_account()
    client.patch(PATH, headers=account.headers, json={"email_notifications": False})

    response = client.patch(
        PATH, headers=account.headers, json={"email_notifications": True}
    )

    assert response.json()["email_notifications"] is True


def test_an_empty_patch_changes_nothing(client, make_account):
    account = make_account()

    response = client.patch(PATH, headers=account.headers, json={})

    assert response.status_code == 200
    assert response.json() == DEFAULTS


def test_a_patch_is_only_the_callers(client, make_account):
    account, other = make_account(), make_account()

    client.patch(PATH, headers=account.headers, json={"language": "fr"})

    assert preferences(client, other) == DEFAULTS


@pytest.mark.parametrize(
    "body",
    [
        {"language": "de"},
        {"language": "FR"},
        {"language": ""},
        {"language": None},
        {"language": 1},
        {"email_notifications": None},
        {"email_notifications": "false"},
        {"email_notifications": 0},
        {"email": "someone@example.com"},
        {"language": "fr", "display_name": "Ada"},
    ],
    ids=[
        "another language",
        "upper case",
        "empty language",
        "null language",
        "number language",
        "null switch",
        "string switch",
        "number switch",
        "extra field",
        "valid field and extra field",
    ],
)
def test_a_refused_patch_is_a_422_and_changes_nothing(client, make_account, body):
    account = make_account()

    response = client.patch(PATH, headers=account.headers, json=body)

    assert response.status_code == 422
    assert preferences(client, account) == DEFAULTS


@pytest.mark.parametrize("method", ["GET", "PATCH"])
def test_preferences_need_a_session(client, method):
    response = client.request(
        method, PATH, json={"language": "fr"} if method == "PATCH" else None
    )

    assert response.status_code == 401
    assert response.json() == NOT_SIGNED_IN


def test_the_account_read_keeps_its_shape(client, make_account):
    response = client.get("/api/me", headers=make_account().headers)

    assert response.json().keys() == {"id", "email", "display_name"}
