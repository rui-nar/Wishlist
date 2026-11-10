"""In production, no schema or docs page tells a visitor the admin routes
exist (admin panel plan D2, review R1-2)."""

import pytest

PAGES = ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"]


@pytest.mark.parametrize("page", PAGES)
def test_production_answers_the_schema_and_docs_as_any_unknown_page(make_client, page):
    client = make_client(app_env="production")
    # With a web build, the client's own page; without one, a 404.
    unknown = client.get("/no-such-page")

    response = client.get(page)

    assert response.status_code == unknown.status_code
    assert response.content == unknown.content


def test_production_still_builds_the_schema_in_process(make_client):
    client = make_client(app_env="production")

    assert "/api/me" in client.app.openapi()["paths"]


@pytest.mark.parametrize("env", ["dev", "validation"])
def test_other_environments_keep_the_schema(make_client, env):
    client = make_client(app_env=env)

    assert client.get("/openapi.json").json()["info"]["title"] == "Wishlist"
    assert client.get("/docs").status_code == 200
