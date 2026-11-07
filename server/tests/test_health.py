# A port nothing listens on: the connection is refused at once.
UNREACHABLE_URL = "postgresql+psycopg://nobody:secret-pw@127.0.0.1:1/nowhere"


def test_health_ok(make_client):
    response = make_client().get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok", "media": "ok"}


def test_health_database_unreachable_does_not_leak_the_error(make_client):
    response = make_client(database_url=UNREACHABLE_URL).get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "database": "unreachable",
        "media": "ok",
    }
    for fragment in ("nobody", "secret-pw", "127.0.0.1", "nowhere", "connection"):
        assert fragment not in response.text


def test_health_media_not_writable(make_client, tmp_path):
    # A regular file where the directory should be: nothing can be created in
    # it, on Windows and Linux alike, whatever the user's privileges.
    not_a_directory = tmp_path / "media-is-a-file"
    not_a_directory.write_text("")

    response = make_client(media_dir=not_a_directory).get("/api/health")

    assert response.status_code == 503
    assert response.json() == {
        "status": "error",
        "database": "ok",
        "media": "not writable",
    }
    assert str(tmp_path) not in response.text


def test_health_leaves_no_file_in_media_dir(make_client, tmp_path):
    make_client().get("/api/health")

    assert list((tmp_path / "media").iterdir()) == []


def test_startup_creates_missing_media_dir(make_client, tmp_path):
    media_dir = tmp_path / "missing" / "media"

    make_client(media_dir=media_dir)

    assert media_dir.is_dir()
