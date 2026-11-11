"""What the admin reads (admin panel plan D5–D7): the users, newest first and
paginated, searched by address; one user with the lists they own, as counts;
the space each one's photos take.

The surprise floor applies to the admin, a user like any other (Review
envelope): with the admin as a list's recipient, a giver's hidden gift with a
photo, a pending upload and a reservation change nothing the admin reads,
about the giver or about themselves (review R1-1).
"""

import base64
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from PIL import Image
from sqlalchemy import text

from app.admin.queries import PAGE_SIZE, encode_cursor

GIFT = {
    "title": "Headphones",
    "description": "Over-ear, black",
    "links": ["https://shop.example.com/h"],
    "price_amount": 149,
    "price_currency": "EUR",
}
LIST_KEYS = {"id", "title", "created_at", "gift_count", "owner_count"}


def b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode()


def png() -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize((64, 48)).save(buffer, "PNG")
    return buffer.getvalue()


def created(response, key="id"):
    assert response.status_code in (200, 201), response.text
    return response.json()[key]


def upload(client, account) -> str:
    return created(client.post("/api/images", content=png(), headers=account.headers))


def new_list(client, account, title="My birthday") -> str:
    body = {"title": title, "recipient_kind": "self"}
    return created(client.post("/api/lists", json=body, headers=account.headers))


def add_gift(client, account, list_id, image=None) -> str:
    body = GIFT | ({} if image is None else {"image_id": image})
    return created(
        client.post(f"/api/lists/{list_id}/gifts", json=body, headers=account.headers)
    )


def future(client) -> str:
    """A date 60 days ahead of the app's clock: the occasion is not passed."""
    return (client.app.state.clock() + timedelta(days=60)).date().isoformat()


def invite(client, owner, list_id, giver) -> str:
    """An occasion of the list, which `giver` joins; returns its id."""
    occasion = created(
        client.post(
            f"/api/lists/{list_id}/occasions",
            json={"name": "Birthday", "date": future(client)},
            headers=owner.headers,
        )
    )
    token = created(
        client.post(f"/api/occasions/{occasion}/link", headers=owner.headers),
        key="join_token",
    )
    joined = client.post("/api/join", json={"token": token}, headers=giver.headers)
    assert joined.status_code == 200, joined.text
    return occasion


def add_hidden(client, giver, occasion) -> str:
    body = GIFT | {"title": "Surprise", "image_id": upload(client, giver)}
    return created(
        client.post(
            f"/api/occasions/{occasion}/hidden-gifts", json=body, headers=giver.headers
        )
    )


def users(client, admin, **params):
    response = client.get("/api/admin/users", params=params, headers=admin.headers)
    assert response.status_code == 200, response.text
    return response.json()


def detail(client, admin, user_id):
    response = client.get(f"/api/admin/users/{user_id}", headers=admin.headers)
    assert response.status_code == 200, response.text
    return response.json()


def row_of(client, admin, user_id):
    [row] = [row for row in users(client, admin)["users"] if row["id"] == str(user_id)]
    return row


def image_bytes(engine, uploader) -> int:
    with engine.connect() as connection:
        return connection.scalar(
            text(
                "SELECT sum(bytes) FROM images JOIN gifts ON gifts.image_id = images.id"
                " WHERE uploaded_by = :user"
            ),
            {"user": uploader},
        )


# The users list (D5).


def test_a_page_is_50_newest_first_and_the_pages_cover_everyone_once(
    client, admin, make_account, engine, now
):
    for _ in range(2 * PAGE_SIZE + 10):
        make_account()
    # Pairs created in the same instant: the id decides between them.
    with engine.begin() as connection:
        ids = list(connection.scalars(text("SELECT id FROM users ORDER BY id")))
        for position, user_id in enumerate(ids):
            connection.execute(
                text("UPDATE users SET created_at = :at WHERE id = :id"),
                {"at": now - timedelta(seconds=position // 2), "id": user_id},
            )
        expected = [
            str(user_id)
            for user_id in connection.scalars(
                text("SELECT id FROM users ORDER BY created_at DESC, id DESC")
            )
        ]

    seen, sizes, cursor = [], [], None
    while True:
        page = users(client, admin, **({} if cursor is None else {"cursor": cursor}))
        sizes.append(len(page["users"]))
        seen += [row["id"] for row in page["users"]]
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert sizes == [PAGE_SIZE, PAGE_SIZE, len(expected) - 2 * PAGE_SIZE]
    assert seen == expected


def test_exactly_one_page_has_no_next_cursor(client, admin, make_account):
    for _ in range(PAGE_SIZE - 1):
        make_account()

    page = users(client, admin)

    assert len(page["users"]) == PAGE_SIZE
    assert page["next_cursor"] is None


@pytest.fixture
def named(make_account, set_email):
    accounts = {}
    for name, email in [
        ("alice", "Alice.Smith@Example.COM"),
        ("bob", "bob_jones@example.org"),
        ("carol", "carol@other.test"),
    ]:
        accounts[name] = make_account()
        set_email(accounts[name].id, email)
    return accounts


@pytest.mark.parametrize(
    ("q", "found"),
    [
        ("smith@ex", ["alice"]),
        ("ALICE.SMITH@EXAMPLE.COM", ["alice"]),
        ("  bob_  ", ["bob"]),
        # Neither is a wildcard.
        ("_", ["bob"]),
        ("%", []),
        ("other.test", ["carol"]),
        ("nobody", []),
    ],
)
def test_q_finds_the_address_containing_it_case_insensitively(
    client, admin, named, q, found
):
    page = users(client, admin, q=q)

    # Newest first: Carol was created last.
    assert [row["id"] for row in page["users"]] == [
        str(named[name].id) for name in ("carol", "bob", "alice") if name in found
    ]


def test_an_empty_q_finds_everyone(client, admin, named):
    assert len(users(client, admin, q="  ")["users"]) == 4


@pytest.mark.parametrize(
    "cursor",
    [
        "not-a-cursor",
        encode_cursor((datetime(2026, 1, 1, tzinfo=UTC), uuid.uuid4())) + "xx",
        b64("x|y"),
        b64(f"2026-01-01T00:00:00|{uuid.uuid4()}|more"),
        # A date with no time zone.
        b64(f"2026-01-01T00:00:00|{uuid.uuid4()}"),
        b64("2026-01-01T00:00:00+00:00|not-an-id"),
        "été",
    ],
)
def test_a_cursor_the_server_did_not_make_is_refused(client, admin, cursor):
    response = client.get(
        "/api/admin/users", params={"cursor": cursor}, headers=admin.headers
    )

    assert response.status_code == 422
    assert response.json()["code"] == "invalid_cursor"


def test_a_row_says_who_how_they_sign_in_their_plan_lists_and_photos(
    client, admin, make_account, engine, set_email, now
):
    target = make_account()
    set_email(target.id, "target@example.com")
    end = now + timedelta(days=30)
    with engine.begin() as connection:
        for provider in ("google", "email", "google"):
            connection.execute(
                text(
                    "INSERT INTO user_identities (id, user_id, provider, subject)"
                    " VALUES (:id, :user, :provider, :subject)"
                ),
                {
                    "id": uuid.uuid4(),
                    "user": target.id,
                    "provider": provider,
                    "subject": uuid.uuid4().hex,
                },
            )
        connection.execute(
            text(
                "INSERT INTO entitlements (id, user_id, source, external_id, status,"
                " period_end, cancel_at_period_end, read_at)"
                " VALUES (:id, :user, 'stripe', 'sub_1', 'active', :end, false, :now)"
            ),
            {"id": uuid.uuid4(), "user": target.id, "end": end, "now": now},
        )
    first = new_list(client, target)
    add_gift(client, target, first, upload(client, target))
    add_gift(client, target, new_list(client, target, "Second"), upload(client, target))
    # A list of the admin's they co-own counts too.
    shared = new_list(client, admin, "Shared")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": shared, "user": target.id},
        )

    row = row_of(client, admin, target.id)

    assert row == {
        "id": str(target.id),
        "email": "target@example.com",
        "display_name": "U",
        "created_at": row["created_at"],
        "sign_in": ["email", "google"],
        "plan": {
            "plan": "premium",
            "source": "stripe",
            "until": end.isoformat().replace("+00:00", "Z"),
        },
        "subscription": {
            "status": "active",
            "started_at": None,
            "period_end": end.isoformat().replace("+00:00", "Z"),
        },
        "apple_subscription": None,
        "manual_grant": None,
        "lists_owned": 3,
        "photos": {
            "count": 2,
            "bytes": image_bytes(engine, target.id),
            "measuring": False,
        },
    }
    assert row["photos"]["bytes"] > 0


def test_a_new_user_is_free_with_nothing(client, admin, make_account):
    target = make_account()

    row = row_of(client, admin, target.id)

    assert row["plan"] == {"plan": "free", "source": None, "until": None}
    assert row["subscription"] is None
    assert row["manual_grant"] is None
    assert row["sign_in"] == []
    assert row["lists_owned"] == 0
    assert row["photos"] == {"count": 0, "bytes": 0, "measuring": False}


# One user (D6).


def test_one_user_shows_their_lists_as_counts_only(client, admin, make_account, engine):
    target = make_account()
    giver = make_account()
    first = new_list(client, target, "Birthday")
    kept = add_gift(client, target, first)
    received = add_gift(client, target, first)
    response = client.post(f"/api/gifts/{received}/received", headers=target.headers)
    assert response.status_code == 204, response.text
    add_hidden(client, giver, invite(client, target, first, giver))
    second = new_list(client, target, "Christmas")
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": second, "user": giver.id},
        )

    found = detail(client, admin, target.id)

    assert [
        (item["id"], item["title"], item["gift_count"], item["owner_count"])
        for item in found["lists"]
    ] == [(first, "Birthday", 1, 1), (second, "Christmas", 0, 2)]
    assert all(set(item) == LIST_KEYS for item in found["lists"])
    assert kept not in str(found)
    assert found["manual_grant"] is None
    row = dict(found)
    del row["lists"]
    assert row == row_of(client, admin, target.id)


def test_an_unknown_user_is_not_found(client, admin):
    response = client.get(f"/api/admin/users/{uuid.uuid4()}", headers=admin.headers)

    assert response.status_code == 404


# Photo space (D7) and the surprise floor.


@pytest.fixture
def surprise(client, admin, make_account):
    """The admin's list for themselves, a gift with a photo on it, and a
    giver invited, with a list of their own with a photo."""
    giver = make_account()
    mine = new_list(client, admin)
    gift = add_gift(client, admin, mine, upload(client, admin))
    occasion = invite(client, admin, mine, giver)
    add_gift(client, giver, new_list(client, giver, "Mine"), upload(client, giver))
    return giver, gift, occasion


def admin_reads(client, admin, giver):
    return [
        client.get(url, headers=admin.headers).content
        for url in (
            "/api/admin/users",
            f"/api/admin/users/{admin.id}",
            f"/api/admin/users/{giver.id}",
        )
    ]


def test_a_givers_hidden_gift_photo_and_pending_upload_change_nothing_the_admin_reads(
    client, admin, surprise
):
    giver, gift, occasion = surprise
    without = admin_reads(client, admin, giver)

    upload(client, giver)
    hidden = add_hidden(client, giver, occasion)
    reserved = client.post(
        f"/api/occasions/{occasion}/gifts/{gift}/reservation", headers=giver.headers
    )
    assert reserved.status_code == 200, reserved.text
    # The activity is there: the giver sees their hidden gift.
    seen = client.get(f"/api/occasions/{occasion}/hidden-gifts", headers=giver.headers)
    assert [found["id"] for found in seen.json()] == [hidden]

    assert admin_reads(client, admin, giver) == without
    assert row_of(client, admin, giver.id)["photos"]["count"] == 1
    assert row_of(client, admin, admin.id)["photos"]["count"] == 1
    assert [
        item["gift_count"] for item in detail(client, admin, admin.id)["lists"]
    ] == [1]


def test_a_revealed_hidden_gifts_photo_counts_for_its_uploader(
    client, admin, surprise, engine, now
):
    giver, _, occasion = surprise
    hidden = add_hidden(client, giver, occasion)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind, bought_at)"
                " VALUES (:gift, :occasion, 'reservation', :now)"
            ),
            {"gift": hidden, "occasion": occasion, "now": now},
        )
        connection.execute(
            text(
                "INSERT INTO claim_participants (gift_id, user_id)"
                " VALUES (:gift, :user)"
            ),
            {"gift": hidden, "user": giver.id},
        )
        connection.execute(
            text("UPDATE occasions SET date = '2001-01-01' WHERE id = :occasion"),
            {"occasion": occasion},
        )

    photos = row_of(client, admin, giver.id)["photos"]

    assert photos["count"] == 2
    assert photos["bytes"] == image_bytes(engine, giver.id)


def test_a_received_gifts_photo_still_counts(client, admin, surprise):
    _, gift, _ = surprise
    response = client.post(f"/api/gifts/{gift}/received", headers=admin.headers)
    assert response.status_code == 204, response.text

    assert row_of(client, admin, admin.id)["photos"]["count"] == 1


def test_a_photo_not_yet_measured_says_measuring(client, admin, surprise, engine):
    giver, _, _ = surprise
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE images SET bytes = NULL WHERE uploaded_by = :user"),
            {"user": admin.id},
        )

    assert row_of(client, admin, admin.id)["photos"] == {
        "count": 1,
        "bytes": 0,
        "measuring": True,
    }
    assert row_of(client, admin, giver.id)["photos"]["measuring"] is False


def test_a_photo_whose_uploader_is_gone_counts_for_no_one(
    client, admin, make_account, engine
):
    co_owner = make_account()
    mine = new_list(client, admin)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": mine, "user": co_owner.id},
        )
    add_gift(client, co_owner, mine, upload(client, co_owner))
    assert client.delete("/api/me", headers=co_owner.headers).status_code == 204

    assert row_of(client, admin, admin.id)["photos"]["count"] == 0
    assert detail(client, admin, admin.id)["lists"][0]["gift_count"] == 1
