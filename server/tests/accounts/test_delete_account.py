from sqlalchemy import text


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def rows_of(engine, user_id: str) -> dict[str, int]:
    with engine.connect() as connection:
        return {
            table: connection.scalar(
                text(f"SELECT count(*) FROM {table} WHERE {column} = :id"),
                {"id": user_id},
            )
            for table, column in (
                ("users", "id"),
                ("user_identities", "user_id"),
                ("sessions", "user_id"),
            )
        }


def test_deleting_the_account_removes_everything_about_the_user(
    client, sign_in, engine
):
    first = sign_in("sub-1")
    second = sign_in("sub-1")
    user_id = first["user"]["id"]
    assert rows_of(engine, user_id) == {
        "users": 1,
        "user_identities": 1,
        "sessions": 2,
    }

    response = client.delete("/api/me", headers=auth(second["token"]))

    assert response.status_code == 204
    assert rows_of(engine, user_id) == {
        "users": 0,
        "user_identities": 0,
        "sessions": 0,
    }
    for token in (first["token"], second["token"]):
        assert client.get("/api/me", headers=auth(token)).status_code == 401


def test_deleting_an_account_leaves_other_users_alone(client, sign_in, engine):
    leaving = sign_in("sub-1")
    staying = sign_in("sub-2")

    client.delete("/api/me", headers=auth(leaving["token"]))

    assert client.get("/api/me", headers=auth(staying["token"])).status_code == 200
    assert rows_of(engine, staying["user"]["id"]) == {
        "users": 1,
        "user_identities": 1,
        "sessions": 1,
    }


def test_signing_in_again_after_deletion_starts_a_new_account(client, sign_in):
    before = sign_in("sub-1")
    client.delete("/api/me", headers=auth(before["token"]))

    after = sign_in("sub-1")

    assert after["user"]["id"] != before["user"]["id"]


def test_deleting_needs_a_session(client):
    assert client.delete("/api/me").status_code == 401
