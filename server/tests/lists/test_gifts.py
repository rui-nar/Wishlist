import pytest

LONGEST_LINK = "https://shop.example.com/" + "a" * (2048 - 25)

FULL = {
    "title": "Headphones",
    "description": "Over-ear, black.\nNot the white ones.",
    "links": ["https://shop.example.com/headphones", "http://other.example.org/h?id=7"],
    "price_amount": 149,
    "price_currency": "EUR",
}


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


@pytest.fixture
def list_id(client, ada):
    response = client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=ada.headers,
    )
    return response.json()["id"]


@pytest.fixture
def add(client, ada, list_id):
    def add(body):
        response = client.post(
            f"/api/lists/{list_id}/gifts", json=body, headers=ada.headers
        )
        assert response.status_code == 201, response.text
        return response.json()

    return add


def gifts_of(client, account, list_id):
    response = client.get(f"/api/lists/{list_id}", headers=account.headers)
    assert response.status_code == 200
    return response.json()["gifts"]


def test_adding_a_gift_with_every_field(client, ada, list_id, add):
    gift = add(FULL)

    assert gift == {
        "id": gift["id"],
        "list_id": list_id,
        "title": "Headphones",
        "description": "Over-ear, black.\nNot the white ones.",
        "links": FULL["links"],
        # As stored, numeric(12,2), and as a string: never a binary float.
        "price_amount": "149.00",
        "price_currency": "EUR",
    }
    assert gifts_of(client, ada, list_id) == [gift]


def test_adding_a_gift_with_a_title_only(add, list_id):
    gift = add({"title": "A surprise"})

    assert gift == {
        "id": gift["id"],
        "list_id": list_id,
        "title": "A surprise",
        "description": "",
        "links": [],
        "price_amount": None,
        "price_currency": None,
    }


def test_gifts_are_listed_oldest_first(client, ada, list_id, add):
    titles = ["First", "Second", "Third"]
    for title in titles:
        add({"title": title})

    assert [gift["title"] for gift in gifts_of(client, ada, list_id)] == titles


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"title": "t" * 200}, id="title of 200"),
        pytest.param(
            {"title": "x", "description": "d" * 2000}, id="description of 2000"
        ),
        pytest.param(
            {"title": "x", "links": [f"https://e.com/{n}" for n in range(10)]},
            id="10 links",
        ),
        pytest.param({"title": "x", "links": [LONGEST_LINK]}, id="link of 2048"),
        pytest.param({"title": "x", "links": ["HTTPS://E.COM/A"]}, id="capital scheme"),
        pytest.param(
            {"title": "x", "price_amount": "9999999999.99", "price_currency": "USD"},
            id="largest price",
        ),
        pytest.param(
            {"title": "x", "price_amount": 0, "price_currency": "JPY"}, id="free"
        ),
        pytest.param(
            {"title": "x", "price_amount": 19.99, "price_currency": "EUR"},
            id="price as a number",
        ),
    ],
)
def test_gifts_at_the_limits_are_accepted(add, body):
    gift = add(body)

    assert gift["title"] == body["title"]
    assert gift["links"] == body.get("links", [])


INVALID = [
    pytest.param({"title": ""}, id="empty title"),
    pytest.param({"title": "  "}, id="blank title"),
    pytest.param({"title": "t" * 201}, id="title of 201"),
    pytest.param({"title": None}, id="null title"),
    pytest.param({"title": "x", "description": "d" * 2001}, id="description of 2001"),
    pytest.param(
        {"title": "x", "links": [f"https://e.com/{n}" for n in range(11)]},
        id="11 links",
    ),
    pytest.param({"title": "x", "links": ["javascript:alert(1)"]}, id="javascript"),
    pytest.param({"title": "x", "links": ["/shop/item"]}, id="relative"),
    pytest.param({"title": "x", "links": ["www.shop.com/item"]}, id="no scheme"),
    pytest.param({"title": "x", "links": ["ftp://shop.com/item"]}, id="ftp"),
    pytest.param({"title": "x", "links": ["https://"]}, id="no host"),
    pytest.param({"title": "x", "links": ["https://e.com/a b"]}, id="space"),
    pytest.param({"title": "x", "links": ["https://e.com/\n"]}, id="newline"),
    pytest.param({"title": "x", "links": [""]}, id="empty link"),
    pytest.param({"title": "x", "links": [LONGEST_LINK + "a"]}, id="link of 2049"),
    pytest.param({"title": "x", "price_currency": "EUR"}, id="currency alone"),
    pytest.param({"title": "x", "price_amount": 10}, id="amount alone"),
    pytest.param(
        {"title": "x", "price_amount": 10, "price_currency": "ABC"},
        id="unknown currency",
    ),
    pytest.param(
        {"title": "x", "price_amount": 10, "price_currency": "eur"},
        id="lowercase currency",
    ),
    pytest.param(
        {"title": "x", "price_amount": -1, "price_currency": "EUR"}, id="negative"
    ),
    pytest.param(
        {"title": "x", "price_amount": 10000000000, "price_currency": "EUR"},
        id="11 integer digits",
    ),
    pytest.param(
        {"title": "x", "price_amount": 19.999, "price_currency": "EUR"},
        id="3 decimals",
    ),
    pytest.param(
        {"title": "x", "price_amount": "19.999", "price_currency": "EUR"},
        id="3 decimals as a string",
    ),
    pytest.param(
        {"title": "x", "price_amount": "NaN", "price_currency": "EUR"}, id="NaN"
    ),
    pytest.param(
        {"title": "x", "price_amount": "Infinity", "price_currency": "EUR"},
        id="infinity",
    ),
    pytest.param({"title": "x", "image": "a.png"}, id="unknown field"),
]


@pytest.mark.parametrize("body", INVALID)
def test_invalid_gifts_are_refused(client, ada, list_id, rows, body):
    response = client.post(
        f"/api/lists/{list_id}/gifts", json=body, headers=ada.headers
    )

    assert response.status_code == 422
    assert rows("gifts") == 0


def test_editing_every_field_of_a_gift(client, ada, list_id, add):
    gift = add({"title": "Book"})
    changes = {
        "title": "Headphones",
        "description": "Black",
        "links": ["https://shop.example.com/h"],
        "price_amount": "19.90",
        "price_currency": "GBP",
    }

    response = client.patch(
        f"/api/gifts/{gift['id']}", json=changes, headers=ada.headers
    )

    assert response.status_code == 200
    assert response.json() == gift | changes
    assert gifts_of(client, ada, list_id) == [gift | changes]


def test_a_field_left_out_of_a_patch_is_unchanged(client, ada, add):
    gift = add(FULL)

    response = client.patch(
        f"/api/gifts/{gift['id']}", json={"price_amount": 99.5}, headers=ada.headers
    )

    assert response.json() == gift | {"price_amount": "99.50"}


def test_removing_a_price_takes_both_halves(client, ada, add):
    gift = add(FULL)

    response = client.patch(
        f"/api/gifts/{gift['id']}",
        json={"price_amount": None, "price_currency": None},
        headers=ada.headers,
    )

    assert response.status_code == 200
    assert response.json() == gift | {"price_amount": None, "price_currency": None}


@pytest.mark.parametrize(
    ("original", "patch"),
    [
        pytest.param(FULL, {"price_amount": None}, id="amount removed alone"),
        pytest.param(FULL, {"price_currency": None}, id="currency removed alone"),
        pytest.param({"title": "x"}, {"price_currency": "EUR"}, id="currency alone"),
        pytest.param({"title": "x"}, {"price_amount": 5}, id="amount alone"),
        pytest.param(FULL, {"price_amount": 19.999}, id="3 decimals"),
        pytest.param(FULL, {"price_amount": -1}, id="negative"),
        pytest.param(FULL, {"price_currency": "ABC"}, id="unknown currency"),
        pytest.param(FULL, {"title": None}, id="null title"),
        pytest.param(FULL, {"description": None}, id="null description"),
        pytest.param(FULL, {"links": None}, id="null links"),
        pytest.param(FULL, {"links": ["javascript:alert(1)"]}, id="javascript"),
        pytest.param(FULL, {"list_id": "x"}, id="moving to another list"),
    ],
)
def test_invalid_gift_changes_are_refused_and_change_nothing(
    client, ada, list_id, add, original, patch
):
    gift = add(original)

    response = client.patch(f"/api/gifts/{gift['id']}", json=patch, headers=ada.headers)

    assert response.status_code == 422
    assert gifts_of(client, ada, list_id) == [gift]


def test_removing_a_gift(client, ada, list_id, add, rows):
    removed = add({"title": "Book"})
    kept = add({"title": "Scarf"})

    response = client.delete(f"/api/gifts/{removed['id']}", headers=ada.headers)

    assert response.status_code == 204
    assert gifts_of(client, ada, list_id) == [kept]
    assert rows("gifts") == 1
