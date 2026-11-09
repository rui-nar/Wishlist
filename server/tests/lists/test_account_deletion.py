"""Deleting an account deletes the lists its user owns alone (lists plan D9),
and takes them out of every claim (reserving plan D10)."""

from datetime import date, timedelta

from claims_invariants import assert_claims_consistent
from sqlalchemy import text

# Relative to today: a fixed date would turn into a passed occasion, where
# claims are refused (reserving plan D8, review R1-3).
FUTURE = (date.today() + timedelta(days=60)).isoformat()


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
        json={"name": "Christmas", "date": FUTURE},
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


def test_deleting_a_removed_persons_account_deletes_their_removals(
    client, make_account, rows
):
    owner = make_account("Ada")
    leaving = make_account("Bea")
    occasion = share(client, owner, add_list(client, owner, "Ada's"), leaving)
    client.delete(
        f"/api/occasions/{occasion}/members/{leaving.id}", headers=owner.headers
    )
    assert rows("occasion_removals") == 1

    client.delete("/api/me", headers=leaving.headers)

    assert rows("occasion_removals") == 0
    members = client.get(f"/api/occasions/{occasion}/members", headers=owner.headers)
    assert members.json() == []


def test_deleting_an_owners_account_deletes_the_removals_on_their_lists(
    client, make_account, rows
):
    leaving = make_account("Ada")
    removed = make_account("Bea")
    occasion = share(client, leaving, add_list(client, leaving, "Ada's"), removed)
    client.delete(
        f"/api/occasions/{occasion}/members/{removed.id}", headers=leaving.headers
    )

    client.delete("/api/me", headers=leaving.headers)

    assert rows("occasion_removals") == 0


def test_deleting_a_givers_account_leaves_no_row_naming_them(
    client, make_account, engine, rows
):
    owner = make_account("Ada")
    leaving = make_account("Bea")
    staying = make_account("Cid")
    list_id = add_list(client, owner, "Ada's")
    gifts = [
        client.post(
            f"/api/lists/{list_id}/gifts", json={"title": title}, headers=owner.headers
        ).json()["id"]
        for title in ("Pen", "Hat")
    ]
    bought, grouped = gifts
    occasion = share(client, owner, list_id, leaving, staying)
    base = f"/api/occasions/{occasion}/gifts"
    for response in (
        client.post(f"{base}/{bought}/reservation", headers=leaving.headers),
        client.post(f"{base}/{bought}/bought", headers=leaving.headers),
        client.put(
            f"{base}/{grouped}/pledge", json={"amount": None}, headers=leaving.headers
        ),
        client.put(
            f"{base}/{grouped}/pledge", json={"amount": None}, headers=staying.headers
        ),
    ):
        assert response.status_code == 200, response.text

    client.delete("/api/me", headers=leaving.headers)

    assert rows("users", "id", leaving.id) == 0
    assert rows("claim_participants", "user_id", leaving.id) == 0
    claims = client.get(f"/api/occasions/{occasion}/claims", headers=staying.headers)
    by_gift = {claim["gift_id"]: claim for claim in claims.json()["gifts"]}
    # The bought gift stays bought, with no name; the group gift keeps Cid.
    assert (by_gift[bought]["bought"], by_gift[bought]["participants"]) == (True, [])
    assert [p["display_name"] for p in by_gift[grouped]["participants"]] == ["Cid"]
    assert "Bea" not in claims.text
    assert_claims_consistent(engine)
