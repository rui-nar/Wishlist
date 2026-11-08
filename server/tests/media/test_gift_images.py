"""Images on gifts: attaching, replacing and removing them, and who reads them
through which path (gift images plan D7, D9, D11)."""

import io
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from functools import partial

import pytest
from PIL import Image
from sqlalchemy import text

from app.accounts.sessions import utc_now

NOW = utc_now()


def png(size=(300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize(size).convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


@pytest.fixture
def bea(make_account):
    return make_account("Bea")


@pytest.fixture
def clock(client):
    """The app's clock, frozen at NOW unless a test moves it."""
    now = [NOW]
    client.app.state.clock = lambda: now[0]
    return now


@pytest.fixture
def upload(client, ada):
    def upload(account=None):
        response = client.post(
            "/api/images", content=png(), headers=(account or ada).headers
        )
        assert response.status_code == 201, response.text
        return response.json()

    return upload


@pytest.fixture
def list_id(client, ada):
    return client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=ada.headers,
    ).json()["id"]


@pytest.fixture
def add(client, ada, list_id, clock):
    def add(body, account=None):
        return client.post(
            f"/api/lists/{list_id}/gifts", json=body, headers=(account or ada).headers
        )

    return add


def patch(client, account, gift_id, body):
    return client.patch(f"/api/gifts/{gift_id}", json=body, headers=account.headers)


def not_found(response) -> bool:
    return response.status_code == 404 and response.json() == {"detail": "Not found"}


def owner_paths(image_id: str) -> dict[str, str]:
    return {
        "url": f"/api/images/{image_id}/full",
        "thumb_url": f"/api/images/{image_id}/thumb",
    }


def occasion_paths(occasion_id: str, image_id: str) -> dict[str, str]:
    base = f"/api/occasions/{occasion_id}/images/{image_id}"
    return {"url": f"{base}/full", "thumb_url": f"{base}/thumb"}


def image_row(engine, image_id):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT attached_at FROM images WHERE id = :id"), {"id": image_id}
        ).one_or_none()


def orphans(engine) -> dict[str, object]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                text("SELECT name, first_seen_at FROM media_orphans")
            ).all()
        )


def gift_count(engine) -> int:
    with engine.connect() as connection:
        return connection.scalar(text("SELECT count(*) FROM gifts"))


def test_adding_a_gift_with_an_image(client, ada, upload, add, engine):
    image = upload()

    response = add({"title": "Lamp", "image_id": image["id"]})

    assert response.status_code == 201, response.text
    gift = response.json()
    assert gift["image"] == {
        "id": image["id"],
        "width": 300,
        "height": 200,
    } | owner_paths(image["id"])
    # Attached now, by the app's clock (review R1-6).
    assert image_row(engine, image["id"]) == (NOW,)
    detail = client.get(f"/api/lists/{gift['list_id']}", headers=ada.headers).json()
    assert detail["gifts"] == [gift]
    for path in owner_paths(image["id"]).values():
        assert client.get(path, headers=ada.headers).status_code == 200


def test_editing_a_gift_without_image_id_keeps_its_image(client, ada, upload, add):
    image = upload()
    gift = add({"title": "Lamp", "image_id": image["id"]}).json()

    response = patch(client, ada, gift["id"], {"title": "Desk lamp"})

    assert response.status_code == 200
    assert response.json() == gift | {"title": "Desk lamp"}


def test_sending_the_current_image_again_changes_nothing(
    client, ada, upload, add, engine
):
    image = upload()
    gift = add({"title": "Lamp", "image_id": image["id"]}).json()

    response = patch(client, ada, gift["id"], {"image_id": image["id"]})

    assert response.status_code == 200
    assert response.json() == gift
    assert orphans(engine) == {}


def test_replacing_an_image_detaches_the_old_one(
    client, ada, upload, add, engine, clock
):
    old = upload()
    new = upload()
    gift = add({"title": "Lamp", "image_id": old["id"]}).json()
    # An older record for the stem, as a rollback to an older dump would
    # bring back (review R1-1): the replace stamps it again.
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO media_orphans VALUES (:name, :then)"),
            {"name": uuid.UUID(old["id"]).hex, "then": NOW - timedelta(days=60)},
        )
    clock[0] = NOW + timedelta(hours=1)

    response = patch(client, ada, gift["id"], {"image_id": new["id"]})

    assert response.status_code == 200, response.text
    assert response.json()["image"]["id"] == new["id"]
    assert orphans(engine) == {uuid.UUID(old["id"]).hex: NOW + timedelta(hours=1)}
    # Detached: no route reads it, its uploader's included (review R1-6).
    for path in owner_paths(old["id"]).values():
        assert not_found(client.get(path, headers=ada.headers))
    for path in owner_paths(new["id"]).values():
        assert client.get(path, headers=ada.headers).status_code == 200
    # And it can never be attached again.
    again = add({"title": "Other", "image_id": old["id"]})
    assert (again.status_code, again.json()) == (
        422,
        {"detail": "image_not_attachable"},
    )


def test_removing_an_image_with_null(client, ada, upload, add, engine):
    image = upload()
    gift = add({"title": "Lamp", "image_id": image["id"]}).json()

    response = patch(client, ada, gift["id"], {"image_id": None})

    assert response.status_code == 200
    assert response.json() == gift | {"image": None}
    assert orphans(engine) == {uuid.UUID(image["id"]).hex: NOW}
    assert not_found(client.get(owner_paths(image["id"])["url"], headers=ada.headers))


@pytest.fixture
def unattachable(client, ada, bea, upload, add, engine):
    """Image ids Ada may not attach, by why."""
    bea_list = client.post(
        "/api/lists",
        json={"title": "Bea's", "recipient_kind": "self"},
        headers=bea.headers,
    ).json()["id"]
    others = upload(account=bea)["id"]
    attached = upload()["id"]
    add({"title": "Lamp", "image_id": attached})
    detached = upload()["id"]
    gift = add({"title": "Vase", "image_id": detached}).json()
    patch(client, ada, gift["id"], {"image_id": None})
    on_beas_gift = upload(account=bea)["id"]
    client.post(
        f"/api/lists/{bea_list}/gifts",
        json={"title": "Book", "image_id": on_beas_gift},
        headers=bea.headers,
    )
    return {
        "another user's pending image": others,
        "an image attached to a gift": attached,
        "an image on another user's gift": on_beas_gift,
        "a detached image": detached,
        "a random id": str(uuid.uuid4()),
    }


@pytest.mark.parametrize(
    "case",
    [
        "another user's pending image",
        "an image attached to a gift",
        "an image on another user's gift",
        "a detached image",
        "a random id",
    ],
)
def test_attaching_anything_but_ones_own_pending_image_is_one_422(
    client, ada, add, unattachable, engine, case
):
    image_id = unattachable[case]
    gift = add({"title": "Scarf"}).json()
    gifts_before = gift_count(engine)

    created = add({"title": "Hat", "image_id": image_id})
    updated = patch(client, ada, gift["id"], {"title": "Wool", "image_id": image_id})

    for response in (created, updated):
        assert (response.status_code, response.json()) == (
            422,
            {"detail": "image_not_attachable"},
        )
    # Nothing was written: no gift, and the patch's title is not kept either.
    assert gift_count(engine) == gifts_before
    assert [
        found["title"]
        for found in client.get(
            f"/api/lists/{gift['list_id']}", headers=ada.headers
        ).json()["gifts"]
        if found["id"] == gift["id"]
    ] == ["Scarf"]


def test_a_pending_image_older_than_24_hours_has_expired(
    client, ada, upload, add, clock, engine
):
    image = upload()
    clock[0] = utc_now() + timedelta(hours=24, minutes=1)

    response = add({"title": "Lamp", "image_id": image["id"]})

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "image_expired"},
    )
    assert image_row(engine, image["id"]) == (None,)

    clock[0] = utc_now() + timedelta(hours=23, minutes=59)
    assert add({"title": "Lamp", "image_id": image["id"]}).status_code == 201


@pytest.fixture
def shared(client, ada, make_account, upload, add, list_id):
    """Ada's list with a gift with an image, and two occasions: Bea joined the
    first, Cid the second, Dan joined the first and was removed from it."""
    image = upload()
    gift = add({"title": "Lamp", "image_id": image["id"]}).json()
    people = {name: make_account(name) for name in ("Bea", "Cid", "Dan", "Eve")}
    occasions = []
    for name, invitees in (("Birthday", ("Bea", "Dan")), ("Christmas", ("Cid",))):
        occasion = client.post(
            f"/api/lists/{list_id}/occasions",
            json={"name": name, "date": "2026-12-25"},
            headers=ada.headers,
        ).json()["id"]
        token = client.post(
            f"/api/occasions/{occasion}/link", headers=ada.headers
        ).json()["join_token"]
        for invitee in invitees:
            client.post(
                "/api/join", json={"token": token}, headers=people[invitee].headers
            )
        occasions.append(occasion)
    client.delete(
        f"/api/occasions/{occasions[0]}/members/{people['Dan'].id}",
        headers=ada.headers,
    )
    return {
        "image": image,
        "gift": gift,
        "occasion": occasions[0],
        "other_occasion": occasions[1],
        **people,
    }


def test_invitees_read_the_image_through_their_occasion(client, ada, shared):
    image, occasion = shared["image"], shared["occasion"]
    paths = occasion_paths(occasion, image["id"])

    view = client.get(f"/api/occasions/{occasion}", headers=shared["Bea"].headers)

    assert (
        view.json()["gifts"][0]["image"]
        == {
            "id": image["id"],
            "width": 300,
            "height": 200,
        }
        | paths
    )
    for account in (shared["Bea"], ada):
        for path in paths.values():
            response = client.get(path, headers=account.headers)
            assert response.status_code == 200
            assert response.headers["content-type"] == "image/webp"
    # The owner's own view of the occasion keeps the owner's paths.
    owner_view = client.get(f"/api/occasions/{occasion}", headers=ada.headers)
    assert (
        owner_view.json()["gifts"][0]["image"]["url"] == owner_paths(image["id"])["url"]
    )


@pytest.mark.parametrize(
    "who",
    ["Cid", "Dan", "Eve"],
    ids=["invitee of another occasion", "removed invitee", "stranger"],
)
def test_nobody_else_reads_it_through_the_occasion(client, shared, who):
    account = shared[who]
    real = occasion_paths(shared["occasion"], shared["image"]["id"])["url"]
    random = occasion_paths(shared["occasion"], str(uuid.uuid4()))["url"]

    assert not_found(client.get(real, headers=account.headers))
    assert not_found(client.get(random, headers=account.headers))
    # Nor through the owners' path.
    owners = owner_paths(shared["image"]["id"])["url"]
    assert not_found(client.get(owners, headers=account.headers))


def test_an_invitee_of_another_occasion_reads_it_through_theirs(client, shared):
    paths = occasion_paths(shared["other_occasion"], shared["image"]["id"])

    response = client.get(paths["thumb_url"], headers=shared["Cid"].headers)

    assert response.status_code == 200


def test_an_occasion_does_not_serve_another_lists_image(
    client, ada, bea, shared, upload
):
    """Bea is an invitee of Ada's occasion and owns a list of her own with an
    image: neither path mixes the two."""
    bea_list = client.post(
        "/api/lists",
        json={"title": "Bea's", "recipient_kind": "self"},
        headers=bea.headers,
    ).json()["id"]
    beas_image = upload(account=bea)["id"]
    client.post(
        f"/api/lists/{bea_list}/gifts",
        json={"title": "Book", "image_id": beas_image},
        headers=bea.headers,
    )

    path = occasion_paths(shared["occasion"], beas_image)["url"]

    for account in (bea, ada):
        assert not_found(client.get(path, headers=account.headers))


def test_an_unknown_variant_through_the_occasion_is_404(client, shared):
    base = f"/api/occasions/{shared['occasion']}/images/{shared['image']['id']}"

    assert not_found(client.get(f"{base}/original", headers=shared["Bea"].headers))


def test_signed_out_the_occasion_route_is_401(client, shared):
    path = occasion_paths(shared["occasion"], shared["image"]["id"])["url"]

    assert client.get(path).status_code == 401


def every_path(shared) -> list[str]:
    image_id = shared["image"]["id"]
    return [
        *owner_paths(image_id).values(),
        *occasion_paths(shared["occasion"], image_id).values(),
    ]


@pytest.mark.parametrize(
    "deletion",
    ["gift", "list", "account"],
)
def test_deleting_the_gift_list_or_account_makes_both_routes_404(
    client, ada, shared, list_id, deletion
):
    path = {
        "gift": f"/api/gifts/{shared['gift']['id']}",
        "list": f"/api/lists/{list_id}",
        "account": "/api/me",
    }[deletion]

    assert client.delete(path, headers=ada.headers).status_code == 204

    readers = [shared["Bea"]] if deletion == "account" else [ada, shared["Bea"]]
    for account in readers:
        for image_path in every_path(shared):
            assert not_found(client.get(image_path, headers=account.headers))


TIMEOUT_SECONDS = 10


def together(*calls):
    """Runs the calls at the same moment, each in its thread; their results."""
    start = threading.Barrier(len(calls), timeout=TIMEOUT_SECONDS)

    def run(call):
        start.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=TIMEOUT_SECONDS) for future in futures]


def test_one_image_attached_twice_at_once_goes_to_one_gift(
    client, ada, upload, add, engine
):
    """The attach locks the image row: the second one finds it attached."""
    for _ in range(10):
        image_id = upload()["id"]
        gifts = [add({"title": title}).json()["id"] for title in ("A", "B")]

        responses = together(
            *(
                partial(patch, client, ada, gift, {"image_id": image_id})
                for gift in gifts
            )
        )

        assert sorted(response.status_code for response in responses) == [200, 422]
        with engine.connect() as connection:
            on_gifts = connection.scalar(
                text("SELECT count(*) FROM gifts WHERE image_id = :id"),
                {"id": image_id},
            )
        assert on_gifts == 1


def test_two_replacements_at_once_leave_no_detached_image_unstamped(
    client, ada, upload, add, engine
):
    """A change of a gift's image locks the gift row: whichever replacement
    goes second detaches, and stamps, the image the first attached (D9)."""
    gift = add({"title": "Lamp", "image_id": upload()["id"]}).json()["id"]
    for _ in range(10):
        image_ids = [upload()["id"] for _ in range(2)]

        responses = together(
            *(
                partial(patch, client, ada, gift, {"image_id": image_id})
                for image_id in image_ids
            )
        )

        assert [response.status_code for response in responses] == [200, 200]
        with engine.connect() as connection:
            unstamped = connection.scalar(
                text(
                    "SELECT count(*) FROM images"
                    " WHERE attached_at IS NOT NULL"
                    " AND id NOT IN"
                    "  (SELECT image_id FROM gifts WHERE image_id IS NOT NULL)"
                    " AND replace(id::text, '-', '') NOT IN"
                    "  (SELECT name FROM media_orphans)"
                )
            )
        assert unstamped == 0
