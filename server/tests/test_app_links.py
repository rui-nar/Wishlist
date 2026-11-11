"""The app-link files (Shush Gift plan D7): what each holds, how it is
answered, and that the web catch-all never takes their place."""

import logging

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

AASA = "/.well-known/apple-app-site-association"
ASSETLINKS = "/.well-known/assetlinks.json"

APPLE_IDS = ["ABCDE12345.com.example.shushgift", "ABCDE12345.com.example.shushgift.val"]
PACKAGE = "com.example.shushgift"
SIGNING = ":".join(["AB"] * 32)
UPLOAD = ":".join(["0F"] * 32)

CONFIGURED = {
    "app_links_apple_app_ids": " , ".join(APPLE_IDS),
    "app_links_android_package": f" {PACKAGE} ",
    "app_links_android_sha256": f"{SIGNING}, {UPLOAD.lower()}",
}


def components(client):
    [details] = client.get(AASA).json()["applinks"]["details"]
    return details["components"]


def test_the_apple_file_lists_the_app_ids_and_exactly_the_app_paths(make_client):
    client = make_client(**CONFIGURED)

    [details] = client.get(AASA).json()["applinks"]["details"]

    assert details["appIDs"] == APPLE_IDS
    assert details["components"] == [
        {"/": "/join"},
        {"/": "/shared/*"},
        {"/": "/create-account"},
        {"/": "/reset-password"},
        {"/": "/account"},
    ]


def test_no_component_restricts_the_query_or_the_fragment(make_client):
    # A missing `?` or `#` key matches any: `/join#<token>` and
    # `/shared/<id>?gift=<id>` open the app.
    client = make_client(**CONFIGURED)

    for component in components(client):
        assert set(component) == {"/"}


@pytest.mark.parametrize(
    "path", ["/account/plan", "/unsubscribe", "/legal/terms", "/api/me", "/welcome"]
)
def test_the_browser_paths_are_claimed_by_no_component(make_client, path):
    # No pattern ends in a bare `*` that could reach them, and none names them.
    client = make_client(**CONFIGURED)

    patterns = [component["/"] for component in components(client)]

    assert path not in patterns
    assert all(
        not path.startswith(pattern.removesuffix("*"))
        for pattern in patterns
        if pattern.endswith("*")
    )


def test_the_android_file_holds_the_package_and_every_fingerprint(make_client):
    client = make_client(**CONFIGURED)

    assert client.get(ASSETLINKS).json() == [
        {
            "relation": ["delegate_permission/common.handle_all_urls"],
            "target": {
                "namespace": "android_app",
                "package_name": PACKAGE,
                "sha256_cert_fingerprints": [SIGNING, UPLOAD],
            },
        }
    ]


@pytest.mark.parametrize("path", [AASA, ASSETLINKS])
def test_each_file_is_json_answered_directly(make_client, path):
    client = make_client(**CONFIGURED)

    response = client.get(path, follow_redirects=False)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"


@pytest.mark.parametrize("path", [AASA, ASSETLINKS])
def test_head_is_answered(make_client, path):
    client = make_client(**CONFIGURED)

    response = client.head(path)

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    assert response.content == b""


@pytest.mark.parametrize(
    ("path", "emptied"),
    [
        (AASA, {"app_links_apple_app_ids": ""}),
        (ASSETLINKS, {"app_links_android_package": ""}),
        (ASSETLINKS, {"app_links_android_sha256": " , "}),
    ],
)
def test_a_file_without_its_settings_is_a_404(make_client, path, emptied):
    client = make_client(**(CONFIGURED | emptied))

    assert client.get(path).status_code == 404
    assert client.head(path).status_code == 404


def test_each_file_needs_only_its_own_settings(make_client):
    client = make_client(app_links_apple_app_ids=APPLE_IDS[0])

    assert client.get(AASA).status_code == 200
    assert client.get(ASSETLINKS).status_code == 404


@pytest.fixture
def web_client(database_url, tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<html>the client</html>")

    def make(**overrides):
        settings = Settings(
            database_url=database_url, media_dir=tmp_path / "media", **overrides
        )
        return TestClient(create_app(settings, web_dir=web))

    return make


@pytest.mark.parametrize("path", [AASA, ASSETLINKS])
def test_the_web_client_does_not_take_their_place(web_client, path):
    configured = web_client(**CONFIGURED).get(path)
    empty = web_client().get(path)

    assert configured.status_code == 200
    assert configured.headers["content-type"] == "application/json"
    assert empty.status_code == 404
    assert "the client" not in empty.text


def test_invalid_entries_are_left_out_and_named_by_position(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        client = make_client(
            app_links_apple_app_ids=f"com.example.shushgift, {APPLE_IDS[0]}",
            app_links_android_package=PACKAGE,
            app_links_android_sha256=f"{SIGNING},,AB:CD, {UPLOAD}",
        )

    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "app.main" and "app links" in record.getMessage()
    ] == [
        "app links: invalid entries ignored: APP_LINKS_APPLE_APP_IDS at positions 1;"
        " APP_LINKS_ANDROID_SHA256 at positions 3"
    ]
    [details] = client.get(AASA).json()["applinks"]["details"]
    assert details["appIDs"] == [APPLE_IDS[0]]
    [statement] = client.get(ASSETLINKS).json()
    assert statement["target"]["sha256_cert_fingerprints"] == [SIGNING, UPLOAD]


def test_an_invalid_package_is_named_and_the_android_file_is_a_404(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        client = make_client(
            app_links_android_package="not a package", app_links_android_sha256=SIGNING
        )

    assert "APP_LINKS_ANDROID_PACKAGE" in caplog.text
    assert client.get(ASSETLINKS).status_code == 404


def test_valid_or_empty_settings_log_nothing(make_client, caplog):
    with caplog.at_level(logging.WARNING, logger="app.main"):
        make_client(**CONFIGURED)
        make_client()

    assert "app links" not in caplog.text


def test_the_files_are_not_in_the_schema(make_client):
    client = make_client(**CONFIGURED)

    assert AASA not in client.app.openapi()["paths"]
    assert ASSETLINKS not in client.app.openapi()["paths"]
