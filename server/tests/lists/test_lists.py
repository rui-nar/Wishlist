import pytest

FOR_ME = {"title": "Birthday", "recipient_kind": "self"}
FOR_LEO = {
    "title": "Leo's birthday",
    "recipient_kind": "other",
    "recipient_name": "Leo",
}


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


def create(client, account, body):
    response = client.post("/api/lists", json=body, headers=account.headers)
    assert response.status_code == 201, response.text
    return response.json()


def test_creating_a_list_for_me(client, ada):
    created = create(client, ada, FOR_ME)

    assert created == {
        "id": created["id"],
        "title": "Birthday",
        "recipient_kind": "self",
        "recipient_name": None,
    }
    detail = client.get(f"/api/lists/{created['id']}", headers=ada.headers)
    assert detail.status_code == 200
    assert detail.json() == created | {"gifts": [], "occasions": []}


def test_creating_a_list_for_someone_else(client, ada):
    created = create(client, ada, FOR_LEO)

    assert created["recipient_kind"] == "other"
    assert created["recipient_name"] == "Leo"


def test_my_lists_are_mine_only_oldest_first_with_their_gift_counts(
    client, ada, make_account
):
    first = create(client, ada, FOR_ME)
    second = create(client, ada, FOR_LEO)
    create(client, make_account("Bea"), FOR_ME)
    for title in ("Book", "Scarf"):
        client.post(
            f"/api/lists/{second['id']}/gifts",
            json={"title": title},
            headers=ada.headers,
        )

    response = client.get("/api/lists", headers=ada.headers)

    assert response.status_code == 200
    assert response.json() == [
        first | {"gift_count": 0, "occasion_count": 0},
        second | {"gift_count": 2, "occasion_count": 0},
    ]


def test_titles_and_names_are_trimmed(client, ada):
    created = create(
        client,
        ada,
        {"title": "  Birthday ", "recipient_kind": "other", "recipient_name": " Leo "},
    )

    assert (created["title"], created["recipient_name"]) == ("Birthday", "Leo")


def test_a_title_and_a_name_of_100_characters_are_accepted(client, ada):
    created = create(
        client,
        ada,
        {"title": "t" * 100, "recipient_kind": "other", "recipient_name": "n" * 100},
    )

    assert len(created["title"]) == len(created["recipient_name"]) == 100


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"recipient_kind": "self"}, id="no title"),
        pytest.param(FOR_ME | {"title": ""}, id="empty title"),
        pytest.param(FOR_ME | {"title": "   "}, id="blank title"),
        pytest.param(FOR_ME | {"title": "t" * 101}, id="title of 101"),
        pytest.param({"title": "Birthday"}, id="no kind"),
        pytest.param(FOR_ME | {"recipient_kind": "both"}, id="unknown kind"),
        pytest.param(
            {"title": "x", "recipient_kind": "other"}, id="other without name"
        ),
        pytest.param(FOR_LEO | {"recipient_name": None}, id="other with null name"),
        pytest.param(FOR_LEO | {"recipient_name": " "}, id="other with blank name"),
        pytest.param(FOR_LEO | {"recipient_name": "n" * 101}, id="name of 101"),
        pytest.param(FOR_ME | {"recipient_name": "Ada"}, id="self with a name"),
        pytest.param(FOR_ME | {"owner_id": "x"}, id="unknown field"),
    ],
)
def test_invalid_lists_are_refused(client, ada, rows, body):
    response = client.post("/api/lists", json=body, headers=ada.headers)

    assert response.status_code == 422
    assert rows("lists") == 0


def test_renaming_a_list_and_its_recipient(client, ada):
    created = create(client, ada, FOR_LEO)

    response = client.patch(
        f"/api/lists/{created['id']}",
        json={"title": "Leo turns 7", "recipient_name": "Léo"},
        headers=ada.headers,
    )

    assert response.status_code == 200
    expected = created | {"title": "Leo turns 7", "recipient_name": "Léo"}
    assert response.json() == expected
    detail = client.get(f"/api/lists/{created['id']}", headers=ada.headers).json()
    assert detail == expected | {"gifts": [], "occasions": []}


def test_a_field_left_out_of_a_patch_is_unchanged(client, ada):
    created = create(client, ada, FOR_LEO)

    response = client.patch(
        f"/api/lists/{created['id']}", json={"title": "New"}, headers=ada.headers
    )

    assert response.json() == created | {"title": "New"}


@pytest.mark.parametrize(
    ("original", "patch"),
    [
        pytest.param(FOR_ME, {"recipient_kind": "other"}, id="self to other"),
        pytest.param(
            FOR_ME,
            {"recipient_kind": "other", "recipient_name": "Leo"},
            id="self to other with a name",
        ),
        pytest.param(FOR_LEO, {"recipient_kind": "self"}, id="other to self"),
        pytest.param(FOR_ME, {"recipient_name": "Ada"}, id="a name on a list for me"),
        pytest.param(FOR_LEO, {"recipient_name": None}, id="removing the name"),
        pytest.param(FOR_LEO, {"recipient_name": "n" * 101}, id="name of 101"),
        pytest.param(FOR_LEO, {"title": None}, id="null title"),
        pytest.param(FOR_LEO, {"title": "t" * 101}, id="title of 101"),
        pytest.param(FOR_LEO, {"title": " "}, id="blank title"),
    ],
)
def test_invalid_changes_are_refused_and_change_nothing(client, ada, original, patch):
    created = create(client, ada, original)

    response = client.patch(
        f"/api/lists/{created['id']}", json=patch, headers=ada.headers
    )

    assert response.status_code == 422
    detail = client.get(f"/api/lists/{created['id']}", headers=ada.headers).json()
    assert detail == created | {"gifts": [], "occasions": []}


def test_deleting_a_list_deletes_its_gifts(client, ada, rows):
    kept = create(client, ada, FOR_ME)
    deleted = create(client, ada, FOR_LEO)
    for found in (kept, deleted):
        client.post(
            f"/api/lists/{found['id']}/gifts",
            json={"title": "Book"},
            headers=ada.headers,
        )

    response = client.delete(f"/api/lists/{deleted['id']}", headers=ada.headers)

    assert response.status_code == 204
    assert (
        client.get(f"/api/lists/{deleted['id']}", headers=ada.headers).status_code
        == 404
    )
    assert rows("gifts", "list_id", deleted["id"]) == 0
    assert rows("list_owners", "list_id", deleted["id"]) == 0
    assert rows("gifts", "list_id", kept["id"]) == 1
    assert [
        found["id"] for found in client.get("/api/lists", headers=ada.headers).json()
    ] == [kept["id"]]


def test_an_id_that_is_not_a_uuid_is_refused(client, ada):
    assert client.get("/api/lists/42", headers=ada.headers).status_code == 422
