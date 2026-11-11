"""Every `/api/admin` route answers anyone but the admin as an unknown path
does (admin panel plan D2, Conventions; review R1-2): signed out, signed in,
with an old session, and the admin too when no admin is configured. Whatever
the method, the path parameter, the query or the body: nothing is read before
`AdminUser`. Anything the admin calls that is no route gets the same 404.
"""

import uuid
from datetime import timedelta

import pytest
from fastapi.routing import APIRoute

from app.admin.router import router as admin_router

# The routes, by method and path, and what each gets called with.
ROUTES = {
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/users/{user_id}"),
    ("POST", "/api/admin/users/{user_id}/premium"),
    ("DELETE", "/api/admin/users/{user_id}/premium"),
    ("DELETE", "/api/admin/users/{user_id}"),
}
CATCH_ALL = "/api/admin{rest:path}"
METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "PROPFIND"]
# Valid, then refused by validation were it read: neither tells a route apart.
BODIES = [
    ({"json": {"email": "someone@example.test", "period_end": "2027-01-01"}}, {}),
    ({"content": b"{not json"}, {"Content-Type": "application/json"}),
]
QUERIES = ["", "?cursor=not-a-cursor", f"?q={'x' * 1000}"]


def declared_routes() -> set[tuple[str, str]]:
    return {
        (method, route.path)
        for route in admin_router.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }


def test_the_matrix_lists_every_admin_route():
    """A new admin route fails here until it is added to `ROUTES`, and so
    checked below."""
    assert declared_routes() == ROUTES
    # The catch-all, with no methods: it matches every one.
    [catch_all] = [
        route
        for route in admin_router.routes
        if isinstance(route, APIRoute) and route.path == CATCH_ALL
    ]
    assert catch_all.methods == set()


def unknown_answer(client, method):
    return client.request(method, "/api/no-such-route")


def assert_like_no_route(client, method, response):
    unknown = unknown_answer(client, method)
    assert unknown.status_code == 404
    assert response.status_code == 404, (method, response.text)
    assert response.content == unknown.content
    assert response.headers.get("content-type") == unknown.headers.get("content-type")
    assert "www-authenticate" not in response.headers
    assert "allow" not in response.headers


def calls(user_id: str):
    """Every route, with each id, query and body, as (method, url, kwargs)."""
    for method, path in sorted(ROUTES):
        for target in (user_id, "not-an-id"):
            url = path.format(user_id=target)
            for query in QUERIES:
                for body in BODIES:
                    yield method, url + query, *body


@pytest.fixture
def other(make_account):
    return make_account()


@pytest.fixture
def headers_of(make_account, other, now):
    """The callers who are not the admin, by name."""
    old = make_account(signed_in_at=now - timedelta(days=30))
    return {
        "signed out": {},
        "unknown token": {"Authorization": "Bearer unknown-token"},
        "signed in": other.headers,
        "old session": old.headers,
    }


@pytest.mark.parametrize(
    "who", ["signed out", "unknown token", "signed in", "old session"]
)
def test_anyone_but_the_admin_gets_404_from_every_route(client, headers_of, who):
    headers = headers_of[who]
    for method, url, body, extra in calls(str(uuid.uuid4())):
        response = client.request(method, url, **body, headers=headers | extra)
        assert_like_no_route(client, method, response)


def test_with_no_admin_configured_the_admin_gets_404_from_every_route(
    make_client, admin, other, now
):
    client = make_client(admin_user_ids="")
    client.app.state.clock = lambda: now
    for method, url, body, extra in calls(str(other.id)):
        response = client.request(method, url, **body, headers=admin.headers | extra)
        assert_like_no_route(client, method, response)


PATHS = [
    "/api/admin",
    "/api/admin/",
    "/api/admin/users/",
    "/api/admin/nothing",
    "/api/admin/users/{user_id}/nothing",
    "/api/admin/users/{user_id}/premium/",
    "/api/adminx",
]


@pytest.mark.parametrize("method", METHODS)
@pytest.mark.parametrize("path", PATHS)
def test_no_admin_path_is_told_apart_by_anyone(
    client, admin, headers_of, other, method, path
):
    url = path.format(user_id=other.id)
    for headers in [*headers_of.values(), admin.headers]:
        assert_like_no_route(
            client, method, client.request(method, url, headers=headers)
        )


@pytest.mark.parametrize("method", METHODS)
def test_another_method_on_a_route_gets_404_not_405(
    client, admin, other, headers_of, method
):
    for path in sorted({path for _, path in ROUTES}):
        if (method, path) in ROUTES:
            continue
        url = path.format(user_id=other.id)
        for headers in [*headers_of.values(), admin.headers]:
            response = client.request(method, url, headers=headers)
            assert_like_no_route(client, method, response)


def test_the_catch_all_does_not_shadow_the_routes(client, admin, other):
    assert client.get("/api/admin/users", headers=admin.headers).status_code == 200
    detail = client.get(f"/api/admin/users/{other.id}", headers=admin.headers)
    assert detail.status_code == 200


def test_the_schema_in_dev_shows_the_routes_not_the_catch_all(client):
    paths = client.app.openapi()["paths"]
    admin_paths = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith("/api/admin")
        for method in operations
    }
    assert admin_paths == ROUTES
