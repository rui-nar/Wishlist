from app.settings import Settings


def test_version_reports_version_and_env(make_client):
    client = make_client(app_version="v1.2.3", app_env="validation")

    response = client.get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"version": "v1.2.3", "env": "validation"}


def test_version_defaults_to_dev(monkeypatch, database_url):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)

    settings = Settings(database_url=database_url)

    assert (settings.app_version, settings.app_env) == ("dev", "dev")
