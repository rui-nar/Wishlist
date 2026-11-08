ALLOWED = "http://localhost:5500"
OTHER = "http://evil.example"


def test_allowed_origin_gets_the_header(make_client):
    client = make_client(frontend_origin=f"{ALLOWED}, http://localhost:5501")

    response = client.get("/api/version", headers={"Origin": ALLOWED})

    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_allowed_origin_preflight(make_client):
    client = make_client(frontend_origin=ALLOWED)

    response = client.options(
        "/api/version",
        headers={"Origin": ALLOWED, "Access-Control-Request-Method": "GET"},
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ALLOWED


def test_other_origin_does_not_get_the_header(make_client):
    client = make_client(frontend_origin=ALLOWED)

    response = client.get("/api/version", headers={"Origin": OTHER})

    assert "access-control-allow-origin" not in response.headers


def test_no_origin_allowed_when_empty(make_client):
    client = make_client(frontend_origin="")

    response = client.get("/api/version", headers={"Origin": ALLOWED})

    assert "access-control-allow-origin" not in response.headers
