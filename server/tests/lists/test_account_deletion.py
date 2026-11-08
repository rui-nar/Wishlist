"""Deleting an account deletes the lists its user owns alone (lists plan D9)."""

from sqlalchemy import text


def add_list(client, account, title):
    found = client.post(
        "/api/lists",
        json={"title": title, "recipient_kind": "self"},
        headers=account.headers,
    ).json()
    client.post(
        f"/api/lists/{found['id']}/gifts",
        json={"title": "Book"},
        headers=account.headers,
    )
    return found["id"]


def test_deleting_the_account_deletes_its_lists_and_gifts_only(
    client, make_account, rows
):
    leaving = make_account("Ada")
    staying = make_account("Bea")
    for title in ("One", "Two"):
        add_list(client, leaving, title)
    kept = add_list(client, staying, "Bea's")

    response = client.delete("/api/me", headers=leaving.headers)

    assert response.status_code == 204
    assert rows("lists") == 1
    assert rows("gifts") == 1
    assert rows("list_owners", "user_id", leaving.id) == 0
    detail = client.get(f"/api/lists/{kept}", headers=staying.headers)
    assert detail.status_code == 200
    assert len(detail.json()["gifts"]) == 1


def test_a_list_with_another_owner_outlives_the_account(
    client, make_account, engine, rows
):
    # No endpoint adds a co-owner yet (D1); the rule is written now, so the
    # second owner is added directly.
    leaving = make_account("Ada")
    co_owner = make_account("Bea")
    shared = add_list(client, leaving, "Shared")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": shared, "user": co_owner.id},
        )

    client.delete("/api/me", headers=leaving.headers)

    assert rows("list_owners", "list_id", shared) == 1
    detail = client.get(f"/api/lists/{shared}", headers=co_owner.headers)
    assert detail.status_code == 200
    assert len(detail.json()["gifts"]) == 1
