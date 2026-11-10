"""Who the admin is (admin panel plan D1–D3): `AdminUser` answers 404 to
everyone else, exactly as an unknown path does, and `RecentAdminUser` asks the
admin to sign in again after 12 hours.

U1 has no admin route yet: each test adds two probes to its app, one reading
and one changing, behind the two dependencies.
"""

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.accounts.deps import AdminUser, RecentAdminUser

READ = "/api/admin/probe"
CHANGE = "/api/admin/probe-change"


def with_probes(client: TestClient, now: datetime) -> TestClient:
    def read(user: AdminUser) -> dict[str, str]:
        return {"id": str(user.id)}

    def change(user: RecentAdminUser) -> dict[str, str]:
        return {"id": str(user.id)}

    client.app.add_api_route(READ, read, methods=["GET"])
    client.app.add_api_route(CHANGE, change, methods=["POST"])
    client.app.state.clock = lambda: now
    return client


@pytest.fixture
def admin(make_account):
    return make_account()


@pytest.fixture
def other(make_account):
    return make_account()


@pytest.fixture
def client(make_client, admin, now):
    return with_probes(make_client(admin_user_ids=f" {admin.id} , "), now)


def call(client, path, headers=None):
    method = "POST" if path == CHANGE else "GET"
    return client.request(method, path, headers=headers or {})


def assert_like_no_route(client, response):
    """The same answer as a path nothing serves: nothing tells an admin route
    apart (D2)."""
    unknown = client.get("/api/no-such-route")
    assert unknown.status_code == 404
    assert response.status_code == 404
    assert response.content == unknown.content
    assert response.headers.get("content-type") == unknown.headers.get("content-type")
    assert "www-authenticate" not in response.headers


def test_the_admin_reads_and_changes(client, admin):
    for path in (READ, CHANGE):
        response = call(client, path, admin.headers)

        assert response.status_code == 200, response.text
        assert response.json() == {"id": str(admin.id)}


@pytest.mark.parametrize("path", [READ, CHANGE])
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer unknown-token"},
        {"Authorization": "Basic YWRhOmFkYQ=="},
        {"Authorization": "Bearer"},
    ],
    ids=["signed-out", "unknown-token", "other-scheme", "no-token"],
)
def test_anyone_signed_out_gets_the_unknown_path_answer(client, path, headers):
    assert_like_no_route(client, call(client, path, headers))


@pytest.mark.parametrize("path", [READ, CHANGE])
def test_a_signed_in_user_who_is_not_admin_gets_the_same(client, other, path):
    assert_like_no_route(client, call(client, path, other.headers))


@pytest.mark.parametrize("path", [READ, CHANGE])
def test_an_expired_admin_session_gets_the_same(client, make_account, now, path):
    old = make_account(signed_in_at=now - timedelta(days=200))
    client.app.state.settings = client.app.state.settings.model_copy(
        update={"admin_user_ids": str(old.id)}
    )

    assert_like_no_route(client, call(client, path, old.headers))


@pytest.mark.parametrize("path", [READ, CHANGE])
@pytest.mark.parametrize("configured", ["", " , ", "not-an-id"])
def test_with_no_admin_configured_the_admin_too_gets_the_same(
    make_client, admin, now, path, configured
):
    client = with_probes(make_client(admin_user_ids=configured), now)

    assert_like_no_route(client, call(client, path, admin.headers))


@pytest.mark.parametrize("path", [READ, CHANGE])
def test_a_deleted_admin_account_gets_the_same(client, admin, engine, path):
    token = admin.headers
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM users WHERE id = :id"), {"id": admin.id})

    assert_like_no_route(client, call(client, path, token))


def test_a_non_admin_request_records_no_use_of_the_session(
    client, make_account, engine, now
):
    stale = make_account(signed_in_at=now - timedelta(days=2))

    call(client, READ, stale.headers)

    with engine.connect() as connection:
        last_used = connection.scalar(
            text("SELECT last_used_at FROM sessions WHERE user_id = :id"),
            {"id": stale.id},
        )
    assert last_used == now - timedelta(days=2)


# A recent sign-in for changes (D3).


def test_a_session_just_under_12_hours_old_may_change(make_client, make_account, now):
    admin = make_account(signed_in_at=now - timedelta(hours=12) + timedelta(seconds=1))
    client = with_probes(make_client(admin_user_ids=str(admin.id)), now)

    assert call(client, CHANGE, admin.headers).status_code == 200


@pytest.mark.parametrize("age", [timedelta(hours=12), timedelta(days=30)])
def test_a_session_12_hours_old_reads_but_must_sign_in_again_to_change(
    make_client, make_account, now, age
):
    admin = make_account(signed_in_at=now - age)
    client = with_probes(make_client(admin_user_ids=str(admin.id)), now)

    assert call(client, READ, admin.headers).status_code == 200
    response = call(client, CHANGE, admin.headers)
    assert response.status_code == 401
    assert response.json() == {"detail": "reauth_required"}


def test_an_old_session_of_someone_else_still_gets_404_not_reauth(
    client, make_account, now
):
    old = make_account(signed_in_at=now - timedelta(days=30))

    assert_like_no_route(client, call(client, CHANGE, old.headers))


# `GET /api/me` (D2).


def test_me_says_who_is_admin(client, admin, other):
    me = client.get("/api/me", headers=admin.headers)
    assert me.status_code == 200
    assert me.json()["is_admin"] is True

    assert client.get("/api/me", headers=other.headers).json()["is_admin"] is False


def test_me_says_no_one_is_admin_when_none_is_configured(make_client, admin, now):
    client = make_client()
    client.app.state.clock = lambda: now

    assert client.get("/api/me", headers=admin.headers).json()["is_admin"] is False
