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


def share(client, owner, list_id, *invitees):
    """An occasion on the list, joined by each invitee; returns its id."""
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": "2026-12-25"},
        headers=owner.headers,
    ).json()["id"]
    link = client.post(f"/api/occasions/{occasion}/link", headers=owner.headers)
    for invitee in invitees:
        joined = client.post(
            "/api/join",
            json={"token": link.json()["join_token"]},
            headers=invitee.headers,
        )
        assert joined.status_code == 200
    return occasion


def test_deleting_an_invitees_account_deletes_their_memberships_only(
    client, make_account, rows
):
    owner = make_account("Ada")
    leaving = make_account("Bea")
    staying = make_account("Cid")
    occasion = share(client, owner, add_list(client, owner, "Ada's"), leaving, staying)

    client.delete("/api/me", headers=leaving.headers)

    assert rows("occasion_members", "user_id", leaving.id) == 0
    assert rows("occasions") == 1
    members = client.get(f"/api/occasions/{occasion}/members", headers=owner.headers)
    assert [member["display_name"] for member in members.json()] == ["Cid"]


def test_deleting_an_owners_account_deletes_their_occasions_and_invitees(
    client, make_account, rows
):
    leaving = make_account("Ada")
    invitee = make_account("Bea")
    share(client, leaving, add_list(client, leaving, "Ada's"), invitee)

    client.delete("/api/me", headers=leaving.headers)

    assert rows("occasions") == 0
    assert rows("occasion_members") == 0
    assert client.get("/api/shared", headers=invitee.headers).json() == []
