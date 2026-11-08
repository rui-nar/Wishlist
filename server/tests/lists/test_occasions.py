"""Occasions, their links and their invitees (lists plan D4-D6, D8).

Who may call what is `test_roles.py`'s business; these tests check what the
endpoints do for the callers who may.
"""

import pytest

FOR_ME = {"title": "Birthday", "recipient_kind": "self"}
FOR_LEO = {
    "title": "Leo's birthday",
    "recipient_kind": "other",
    "recipient_name": "Leo",
}
CHRISTMAS = {"name": "Christmas 2026", "date": "2026-12-25"}


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


@pytest.fixture
def bea(make_account):
    return make_account("Bea")


def create_list(client, account, body=FOR_ME):
    response = client.post("/api/lists", json=body, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def create_occasion(client, account, list_id, body=CHRISTMAS):
    response = client.post(
        f"/api/lists/{list_id}/occasions", json=body, headers=account.headers
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_link(client, account, occasion_id):
    response = client.post(
        f"/api/occasions/{occasion_id}/link", headers=account.headers
    )
    assert response.status_code == 200, response.text
    return response.json()["join_token"]


def join(client, account, token):
    return client.post("/api/join", json={"token": token}, headers=account.headers)


def preview(client, account, token):
    return client.post(
        "/api/join/preview", json={"token": token}, headers=account.headers
    )


@pytest.fixture
def shared(client, ada, bea):
    """Ada's "for me" list with a gift and an occasion that Bea joined."""
    list_id = create_list(client, ada)
    client.post(
        f"/api/lists/{list_id}/gifts",
        json={"title": "Book", "price_amount": "12.5", "price_currency": "EUR"},
        headers=ada.headers,
    )
    occasion = create_occasion(client, ada, list_id)
    token = create_link(client, ada, occasion["id"])
    assert join(client, bea, token).status_code == 200
    return {"list_id": list_id, "occasion_id": occasion["id"], "token": token}


# Occasions


def test_creating_an_occasion(client, ada):
    list_id = create_list(client, ada)

    created = create_occasion(client, ada, list_id, CHRISTMAS | {"name": " Xmas "})

    assert created == {
        "id": created["id"],
        "list_id": list_id,
        "name": "Xmas",
        "date": "2026-12-25",
        # No link until the owner creates one.
        "join_token": None,
        "member_count": 0,
    }


def test_the_list_shows_its_occasions_by_date_with_links_and_members(client, ada, bea):
    list_id = create_list(client, ada)
    later = create_occasion(client, ada, list_id, CHRISTMAS)
    sooner = create_occasion(
        client, ada, list_id, {"name": "Party", "date": "2026-06-01"}
    )
    token = create_link(client, ada, later["id"])
    join(client, bea, token)

    detail = client.get(f"/api/lists/{list_id}", headers=ada.headers).json()

    assert detail["occasions"] == [
        sooner,
        later | {"join_token": token, "member_count": 1},
    ]
    summary = client.get("/api/lists", headers=ada.headers).json()
    assert [found["occasion_count"] for found in summary] == [2]


def test_renaming_and_moving_an_occasion(client, ada):
    list_id = create_list(client, ada)
    occasion = create_occasion(client, ada, list_id)
    url = f"/api/occasions/{occasion['id']}"

    renamed = client.patch(url, json={"name": "Noël"}, headers=ada.headers)
    moved = client.patch(url, json={"date": "2026-12-24"}, headers=ada.headers)

    assert renamed.json() == occasion | {"name": "Noël"}
    assert moved.json() == occasion | {"name": "Noël", "date": "2026-12-24"}


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"date": "2026-12-25"}, id="no name"),
        pytest.param({"name": " ", "date": "2026-12-25"}, id="blank name"),
        pytest.param({"name": "n" * 101, "date": "2026-12-25"}, id="name of 101"),
        pytest.param({"name": "Xmas"}, id="no date"),
        pytest.param({"name": "Xmas", "date": "2026-02-30"}, id="no such date"),
        pytest.param({"name": "Xmas", "date": "25/12/2026"}, id="not ISO"),
        pytest.param(CHRISTMAS | {"join_token": "x"}, id="a token"),
    ],
)
def test_invalid_occasions_are_refused(client, ada, rows, body):
    list_id = create_list(client, ada)

    response = client.post(
        f"/api/lists/{list_id}/occasions", json=body, headers=ada.headers
    )

    assert response.status_code == 422
    assert rows("occasions") == 0


@pytest.mark.parametrize(
    "body", [{"name": None}, {"date": None}, {"name": ""}, {"join_token": "x"}]
)
def test_invalid_occasion_updates_are_refused(client, ada, body):
    list_id = create_list(client, ada)
    occasion = create_occasion(client, ada, list_id)

    response = client.patch(
        f"/api/occasions/{occasion['id']}", json=body, headers=ada.headers
    )

    assert response.status_code == 422


def test_deleting_an_occasion_deletes_its_memberships_only(
    client, ada, bea, rows, shared
):
    other = create_occasion(client, ada, shared["list_id"])
    join(client, bea, create_link(client, ada, other["id"]))

    response = client.delete(
        f"/api/occasions/{shared['occasion_id']}", headers=ada.headers
    )

    assert response.status_code == 204
    assert rows("occasions") == 1
    assert rows("occasion_members") == 1
    assert rows("gifts") == 1
    gone = client.get(f"/api/occasions/{shared['occasion_id']}", headers=bea.headers)
    assert gone.status_code == 404


def test_deleting_a_list_deletes_its_occasions_and_memberships(
    client, ada, rows, shared
):
    client.delete(f"/api/lists/{shared['list_id']}", headers=ada.headers)

    assert rows("occasions") == 0
    assert rows("occasion_members") == 0


# Links


def test_a_link_is_a_random_url_safe_token(client, ada):
    list_id = create_list(client, ada)
    first = create_occasion(client, ada, list_id)
    second = create_occasion(client, ada, list_id)

    tokens = {
        create_link(client, ada, first["id"]),
        create_link(client, ada, second["id"]),
    }

    assert len(tokens) == 2
    for token in tokens:
        # secrets.token_urlsafe(16): 128 random bits in 22 characters.
        assert len(token) == 22
        assert token.replace("-", "").replace("_", "").isalnum()


def test_regenerating_a_link_retires_the_old_one_and_keeps_the_members(
    client, ada, bea, make_account, shared
):
    new_token = create_link(client, ada, shared["occasion_id"])

    assert new_token != shared["token"]
    cid = make_account("Cid")
    assert preview(client, cid, shared["token"]).status_code == 404
    assert join(client, cid, shared["token"]).status_code == 404
    assert join(client, cid, new_token).status_code == 200
    members = client.get(
        f"/api/occasions/{shared['occasion_id']}/members", headers=ada.headers
    ).json()
    assert [member["display_name"] for member in members] == ["Bea", "Cid"]
    still = client.get(f"/api/occasions/{shared['occasion_id']}", headers=bea.headers)
    assert still.status_code == 200


def test_revoking_a_link_stops_new_joins_and_keeps_the_members(
    client, ada, bea, make_account, shared
):
    response = client.delete(
        f"/api/occasions/{shared['occasion_id']}/link", headers=ada.headers
    )

    assert response.status_code == 204
    cid = make_account("Cid")
    assert preview(client, cid, shared["token"]).status_code == 404
    assert join(client, cid, shared["token"]).status_code == 404
    detail = client.get(f"/api/lists/{shared['list_id']}", headers=ada.headers).json()
    assert detail["occasions"][0]["join_token"] is None
    still = client.get(f"/api/occasions/{shared['occasion_id']}", headers=bea.headers)
    assert still.status_code == 200


# Joining


def test_the_preview_says_what_would_be_joined_and_joins_nothing(
    client, make_account, rows, shared
):
    cid = make_account("Cid")

    response = preview(client, cid, shared["token"])

    assert response.status_code == 200
    assert response.json() == {
        "name": "Christmas 2026",
        "date": "2026-12-25",
        "list_title": "Birthday",
        "recipient_name": "Ada",
        "owner_names": ["Ada"],
        "role": "none",
        "list_id": None,
        "occasion_id": None,
    }
    assert rows("occasion_members", "user_id", cid.id) == 0


def test_joining_twice_is_one_membership(client, bea, rows, shared):
    again = join(client, bea, shared["token"])

    assert again.status_code == 200
    assert again.json() == {"occasion_id": shared["occasion_id"]}
    assert rows("occasion_members") == 1


@pytest.mark.parametrize("body", [FOR_ME, FOR_LEO], ids=["for me", "for someone"])
def test_an_owner_cannot_join_their_own_occasion(client, ada, rows, body):
    list_id = create_list(client, ada, body)
    occasion = create_occasion(client, ada, list_id)
    token = create_link(client, ada, occasion["id"])

    joined = join(client, ada, token)
    previewed = preview(client, ada, token)

    assert joined.status_code == 409
    assert joined.json()["list_id"] == list_id
    assert (previewed.json()["role"], previewed.json()["list_id"]) == ("owner", list_id)
    assert rows("occasion_members") == 0


def test_the_token_is_taken_from_the_body_only(client, make_account, rows, shared):
    cid = make_account("Cid")

    in_path = client.post(f"/api/join/{shared['token']}", headers=cid.headers)
    in_query = client.post(
        "/api/join", params={"token": shared["token"]}, headers=cid.headers
    )

    assert in_path.status_code == 404
    assert in_query.status_code == 422
    assert rows("occasion_members", "user_id", cid.id) == 0


@pytest.mark.parametrize("path", ["/api/join", "/api/join/preview"])
@pytest.mark.parametrize(
    ("body", "status"),
    [
        pytest.param({"token": "t" * 65}, 422, id="65 characters"),
        pytest.param({"token": ""}, 422, id="empty"),
        pytest.param({}, 422, id="missing"),
        pytest.param({"token": 12}, 422, id="not a string"),
        pytest.param({"token": "t", "occasion_id": "x"}, 422, id="unknown field"),
        pytest.param({"token": "t" * 64}, 404, id="64 characters, unknown"),
        pytest.param({"token": "unknown"}, 404, id="unknown"),
    ],
)
def test_bad_tokens(client, ada, rows, path, body, status):
    response = client.post(path, json=body, headers=ada.headers)

    assert response.status_code == status
    assert rows("occasion_members") == 0


# The invitee's view


def test_an_invitee_sees_the_occasion_its_list_and_gifts(client, bea, shared):
    response = client.get(
        f"/api/occasions/{shared['occasion_id']}", headers=bea.headers
    )

    assert response.status_code == 200
    view = response.json()
    gift_id = view["gifts"][0]["id"]
    # Exactly these fields: no token, no members, no list id, no other
    # occasion (D8).
    assert view == {
        "id": shared["occasion_id"],
        "name": "Christmas 2026",
        "date": "2026-12-25",
        "list_title": "Birthday",
        "recipient_name": "Ada",
        "owner_names": ["Ada"],
        "role": "invitee",
        "gifts": [
            {
                "id": gift_id,
                "title": "Book",
                "description": "",
                "links": [],
                "price_amount": "12.50",
                "price_currency": "EUR",
            }
        ],
    }
    listed = client.get("/api/shared", headers=bea.headers).json()
    assert listed == [
        {key: value for key, value in view.items() if key not in ("role", "gifts")}
    ]


def test_the_owner_sees_the_occasion_with_its_link_and_list(client, ada, shared):
    view = client.get(
        f"/api/occasions/{shared['occasion_id']}", headers=ada.headers
    ).json()

    assert view["role"] == "owner"
    assert view["join_token"] == shared["token"]
    assert view["member_count"] == 1
    assert view["list"]["id"] == shared["list_id"]
    assert view["gifts"][0]["list_id"] == shared["list_id"]


def test_the_invitee_view_names_the_recipient_of_a_list_for_someone_else(
    client, ada, bea
):
    list_id = create_list(client, ada, FOR_LEO)
    occasion = create_occasion(client, ada, list_id)
    join(client, bea, create_link(client, ada, occasion["id"]))

    view = client.get(f"/api/occasions/{occasion['id']}", headers=bea.headers).json()

    assert (view["recipient_name"], view["owner_names"]) == ("Leo", ["Ada"])


def test_members_names_are_shown_to_owners_only(client, ada, bea, make_account, shared):
    cid = make_account("Cid")
    join(client, cid, shared["token"])

    to_owner = client.get(
        f"/api/occasions/{shared['occasion_id']}/members", headers=ada.headers
    )
    seen_by_bea = [
        client.get(f"/api/occasions/{shared['occasion_id']}", headers=bea.headers),
        client.get("/api/shared", headers=bea.headers),
        preview(client, bea, shared["token"]),
    ]

    assert to_owner.json() == [
        {"user_id": bea.id, "display_name": "Bea", "removed": False},
        {"user_id": cid.id, "display_name": "Cid", "removed": False},
    ]
    for response in seen_by_bea:
        assert response.status_code == 200
        assert "Cid" not in response.text
        assert cid.id not in response.text


def test_shared_with_me_is_sorted_by_date(client, ada, bea):
    list_id = create_list(client, ada)
    later = create_occasion(client, ada, list_id, CHRISTMAS)
    sooner = create_occasion(
        client, ada, list_id, {"name": "Party", "date": "2026-06-01"}
    )
    for occasion in (later, sooner):
        join(client, bea, create_link(client, ada, occasion["id"]))

    listed = client.get("/api/shared", headers=bea.headers).json()

    assert [found["id"] for found in listed] == [sooner["id"], later["id"]]


# Removing and leaving


def remove(client, owner, occasion_id, account):
    return client.delete(
        f"/api/occasions/{occasion_id}/members/{account.id}", headers=owner.headers
    )


def allow_again(client, owner, occasion_id, account):
    return client.delete(
        f"/api/occasions/{occasion_id}/removals/{account.id}", headers=owner.headers
    )


def can_read(client, account, occasion_id):
    response = client.get(f"/api/occasions/{occasion_id}", headers=account.headers)
    return response.status_code == 200


def test_a_removed_invitee_loses_access_and_is_listed_as_removed(
    client, ada, bea, rows, shared
):
    occasion = shared["occasion_id"]

    removed = remove(client, ada, occasion, bea)

    assert removed.status_code == 204
    assert not can_read(client, bea, occasion)
    assert client.get("/api/shared", headers=bea.headers).json() == []
    assert rows("occasion_removals", "user_id", bea.id) == 1
    members = client.get(f"/api/occasions/{occasion}/members", headers=ada.headers)
    assert members.json() == [
        {"user_id": bea.id, "display_name": "Bea", "removed": True}
    ]
    detail = client.get(f"/api/lists/{shared['list_id']}", headers=ada.headers).json()
    assert detail["occasions"][0]["member_count"] == 0
    # Removed again: they are no longer a member.
    assert remove(client, ada, occasion, bea).status_code == 404


def test_a_removed_invitee_cannot_come_back_through_any_link(
    client, ada, bea, rows, shared
):
    occasion = shared["occasion_id"]
    remove(client, ada, occasion, bea)

    old_token = shared["token"]
    new_token = create_link(client, ada, occasion)

    # Not with the link they knew, nor with a regenerated one: the answer is
    # the one for an unknown token.
    for token in (old_token, new_token):
        assert preview(client, bea, token).json() == {"detail": "Not found"}
        refused = join(client, bea, token)
        assert (refused.status_code, refused.json()) == (404, {"detail": "Not found"})
    assert rows("occasion_members") == 0
    assert not can_read(client, bea, occasion)


def test_allowed_again_they_rejoin_with_a_current_link_only(
    client, ada, bea, rows, shared
):
    occasion = shared["occasion_id"]
    remove(client, ada, occasion, bea)
    new_token = create_link(client, ada, occasion)

    allowed = allow_again(client, ada, occasion, bea)

    assert allowed.status_code == 204
    assert rows("occasion_removals") == 0
    # Allowing does not rejoin them (D8).
    assert rows("occasion_members") == 0
    assert not can_read(client, bea, occasion)
    members = client.get(f"/api/occasions/{occasion}/members", headers=ada.headers)
    assert members.json() == []
    # The link they knew was regenerated away; the current one works.
    assert join(client, bea, shared["token"]).status_code == 404
    assert preview(client, bea, new_token).json()["role"] == "none"
    assert join(client, bea, new_token).status_code == 200
    assert can_read(client, bea, occasion)


def test_allowing_someone_who_was_not_removed(client, ada, bea, shared):
    response = allow_again(client, ada, shared["occasion_id"], bea)

    assert response.status_code == 404


def test_a_removal_holds_for_its_occasion_only(client, ada, bea, shared):
    other = create_occasion(client, ada, shared["list_id"])
    other_token = create_link(client, ada, other["id"])
    remove(client, ada, shared["occasion_id"], bea)

    assert join(client, bea, other_token).status_code == 200
    assert can_read(client, bea, other["id"])


def test_removing_someone_who_is_not_a_member(client, ada, make_account, shared):
    cid = make_account("Cid")

    response = client.delete(
        f"/api/occasions/{shared['occasion_id']}/members/{cid.id}", headers=ada.headers
    )

    assert response.status_code == 404


def test_an_invitee_who_leaves_loses_access(client, bea, rows, shared):
    occasion = shared["occasion_id"]

    left = client.delete(f"/api/occasions/{occasion}/membership", headers=bea.headers)

    assert left.status_code == 204
    assert rows("occasion_members") == 0
    assert (
        client.get(f"/api/occasions/{occasion}", headers=bea.headers).status_code == 404
    )
    again = client.delete(f"/api/occasions/{occasion}/membership", headers=bea.headers)
    assert again.status_code == 404
    assert client.get("/api/shared", headers=bea.headers).json() == []
    # Leaving is not a removal: nothing keeps them out.
    assert rows("occasion_removals") == 0


def test_an_invitee_who_left_rejoins_with_a_current_link(client, bea, shared):
    occasion = shared["occasion_id"]
    client.delete(f"/api/occasions/{occasion}/membership", headers=bea.headers)

    rejoined = join(client, bea, shared["token"])

    assert rejoined.status_code == 200
    assert can_read(client, bea, occasion)
