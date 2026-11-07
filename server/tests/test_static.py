import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

INDEX = "<html>the client</html>"
SCRIPT = "main();"


@pytest.fixture
def web_dir(tmp_path):
    web = tmp_path / "web"
    (web / "assets").mkdir(parents=True)
    (web / "index.html").write_text(INDEX)
    (web / "main.dart.js").write_text(SCRIPT)
    (web / "assets" / "data.json").write_text("{}")
    return web


@pytest.fixture
def make_app_client(database_url, tmp_path):
    def make(web_dir):
        settings = Settings(database_url=database_url, media_dir=tmp_path / "media")
        return TestClient(create_app(settings, web_dir=web_dir))

    return make


@pytest.fixture
def client(make_app_client, web_dir):
    return make_app_client(web_dir)


def test_root_serves_index(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"


def test_file_of_the_build_is_served(client):
    response = client.get("/main.dart.js")

    assert response.status_code == 200
    assert response.text == SCRIPT
    assert response.headers["cache-control"] == "no-cache"


def test_file_in_a_subdirectory_is_served(client):
    response = client.get("/assets/data.json")

    assert response.status_code == 200
    assert response.text == "{}"


@pytest.mark.parametrize("path", ["/lists", "/lists/42/gifts", "/assets", "/apiary"])
def test_unknown_non_api_path_serves_index(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.text == INDEX
    assert response.headers["cache-control"] == "no-cache"


def test_head_is_answered(client):
    response = client.head("/main.dart.js")

    assert response.status_code == 200
    assert response.headers["content-length"] == str(len(SCRIPT))


def test_unchanged_file_is_a_304(client):
    etag = client.get("/main.dart.js").headers["etag"]

    response = client.get("/main.dart.js", headers={"If-None-Match": etag})

    assert response.status_code == 304


def test_api_routes_take_precedence(client):
    response = client.get("/api/version")

    assert response.status_code == 200
    assert "version" in response.json()


@pytest.mark.parametrize("path", ["/api", "/api/", "/api/nothing", "/api/a/b"])
def test_unknown_api_path_is_a_json_404(client, path):
    response = client.get(path)

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_unknown_api_path_is_a_404_for_other_methods(client):
    # Not the catch-all's 405: the API answers as if no web build were there.
    response = client.post("/api/nothing")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_path_outside_the_build_is_not_served(client, tmp_path):
    (tmp_path / "secret.txt").write_text("secret")

    response = client.get("/..%2Fsecret.txt")

    assert "secret" not in response.text
    assert response.text == INDEX


def test_without_a_web_build_only_the_api_is_served(make_app_client, tmp_path):
    client = make_app_client(tmp_path / "no-web-build")

    assert client.get("/").status_code == 404
    assert client.get("/lists").status_code == 404
    assert client.get("/api/version").status_code == 200
