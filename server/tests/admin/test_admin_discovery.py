"""Outside DEV, no schema or docs page tells a visitor the admin routes exist
(admin panel plan D2, reviews R1-2, R2-1: VAL is public too). A wrong
ADMIN_USER_IDS entry is named at start by its position only (review R2-3)."""

import logging

import pytest

PAGES = ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("env", ["validation", "production"])
@pytest.mark.parametrize("page", PAGES)
def test_val_and_production_answer_the_schema_and_docs_as_any_unknown_page(
    make_client, env, page
):
    client = make_client(app_env=env)
    # With a web build, the client's own page; without one, a 404.
    unknown = client.get("/no-such-page")

    response = client.get(page)

    assert response.status_code == unknown.status_code
    assert response.content == unknown.content


@pytest.mark.parametrize("env", ["validation", "production"])
def test_the_schema_is_still_built_in_process(make_client, env):
    client = make_client(app_env=env)

    assert "/api/me" in client.app.openapi()["paths"]


def test_only_dev_keeps_the_schema(make_client):
    client = make_client(app_env="dev")

    assert client.get("/openapi.json").json()["info"]["title"] == "Wishlist"
    assert client.get("/docs").status_code == 200


def admin_warnings(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.main" and "ADMIN_USER_IDS" in record.getMessage()
    ]


def test_an_entry_that_is_not_an_id_is_named_by_its_position(make_client, caplog):
    valid = "0f8fad5b-d9cb-469f-a165-70867728950e"
    address = "owner@example.com"

    with caplog.at_level(logging.WARNING, logger="app.main"):
        client = make_client(admin_user_ids=f"{address}, {valid},,not-an-id")

    assert admin_warnings(caplog) == [
        "ADMIN_USER_IDS: entries at positions 1, 4 are not account ids; ignored"
    ]
    assert all(address not in record.getMessage() for record in caplog.records)
    assert all("not-an-id" not in record.getMessage() for record in caplog.records)
    assert [str(admin) for admin in client.app.state.settings.admin_ids] == [valid]


@pytest.mark.parametrize(
    "configured", ["", " , ", "0f8fad5b-d9cb-469f-a165-70867728950e"]
)
def test_valid_or_empty_ids_log_nothing(make_client, caplog, configured):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        make_client(admin_user_ids=configured)

    assert admin_warnings(caplog) == []
