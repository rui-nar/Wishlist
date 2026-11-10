"""Uploading an image and reading it back (gift images plan D7, D8, D11)."""

import io
import logging
import struct
import uuid
import zlib
from datetime import UTC, datetime

import pytest
from PIL import Image
from sqlalchemy import text

from app.media import images, router

PNG_HEADER_ONLY = b"\x89PNG\r\n\x1a\n"


def encoded(image: Image.Image, format: str, **params) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format, **params)
    return buffer.getvalue()


def picture(size=(2000, 1000)) -> Image.Image:
    return Image.linear_gradient("L").resize(size).convert("RGB")


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


@pytest.fixture
def bob(make_account):
    return make_account("Bob")


@pytest.fixture
def upload(client, ada):
    def upload(data=None, account=None):
        response = client.post(
            "/api/images",
            content=encoded(picture(), "PNG") if data is None else data,
            headers=(account or ada).headers,
        )
        assert response.status_code == 201, response.text
        return response.json()

    return upload


def image_rows(engine):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id, uploaded_by, width, height, attached_at FROM images")
        ).all()


@pytest.mark.parametrize(
    ("format", "mode"),
    [("JPEG", "RGB"), ("PNG", "RGBA"), ("WEBP", "RGB"), ("GIF", "P")],
)
def test_an_upload_is_a_pending_image_of_its_uploader(
    client, ada, engine, media_dir, format, mode
):
    data = encoded(picture().convert(mode), format)

    response = client.post(
        "/api/images",
        content=data,
        headers=ada.headers | {"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 201, response.text
    body = response.json()
    image_id = uuid.UUID(body["id"])
    assert body == {
        "id": str(image_id),
        "width": 1600,
        "height": 800,
        "url": f"/api/images/{image_id}/full",
        "thumb_url": f"/api/images/{image_id}/thumb",
    }
    assert image_rows(engine) == [(image_id, uuid.UUID(ada.id), 1600, 800, None)]
    # Two WebP files named by the id, and nothing else.
    gifts = media_dir / "gifts"
    assert sorted(path.name for path in gifts.iterdir()) == [
        f"{image_id.hex}.thumb.webp",
        f"{image_id.hex}.webp",
    ]
    for name, size in (
        (f"{image_id.hex}.webp", (1600, 800)),
        (f"{image_id.hex}.thumb.webp", (256, 256)),
    ):
        with Image.open(gifts / name) as stored:
            assert (stored.format, stored.size) == ("WEBP", size)


def test_an_upload_records_the_size_of_its_two_files(upload, engine, media_dir):
    """Admin panel plan D7: the panel reads sizes from the database only."""
    image_id = uuid.UUID(upload()["id"])

    with engine.connect() as connection:
        recorded = connection.scalar(
            text("SELECT bytes FROM images WHERE id = :id"), {"id": image_id}
        )
    on_disk = sum(
        images.image_path(media_dir, image_id, variant).stat().st_size
        for variant in images.VARIANTS
    )
    assert recorded == on_disk > 0


def test_the_uploader_reads_a_pending_image(client, ada, upload, media_dir):
    image = upload()

    for variant, url in (("full", image["url"]), ("thumb", image["thumb_url"])):
        response = client.get(url, headers=ada.headers)

        assert response.status_code == 200
        suffix = images.VARIANTS[variant]
        stored = media_dir / "gifts" / f"{uuid.UUID(image['id']).hex}{suffix}"
        assert response.content == stored.read_bytes()
        assert response.headers["content-type"] == "image/webp"
        assert (
            response.headers["cache-control"] == "private, max-age=31536000, immutable"
        )
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["etag"] == f'"{uuid.UUID(image["id"]).hex}.{variant}"'


def not_found(response):
    return response.status_code == 404 and response.json() == {"detail": "Not found"}


def test_another_user_gets_the_same_404_as_a_random_id(client, bob, upload):
    image = upload()

    assert not_found(client.get(image["url"], headers=bob.headers))
    assert not_found(client.get(image["thumb_url"], headers=bob.headers))
    assert not_found(
        client.get(f"/api/images/{uuid.uuid4()}/full", headers=bob.headers)
    )


def test_an_unknown_variant_is_404(client, ada, upload):
    image = upload()

    assert not_found(
        client.get(f"/api/images/{image['id']}/original", headers=ada.headers)
    )


def test_a_detached_image_is_404_for_its_uploader_too(client, ada, upload, engine):
    image = upload()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE images SET attached_at = :now WHERE id = :id"),
            {"now": datetime.now(UTC), "id": image["id"]},
        )

    assert not_found(client.get(image["url"], headers=ada.headers))
    assert not_found(client.get(image["thumb_url"], headers=ada.headers))


@pytest.fixture
def attach(client, engine):
    """Puts an image on a new gift of a new list owned by `owner`, directly in
    the database: attaching through the gift endpoints is a later unit's."""

    def attach(image, owner):
        list_id = client.post(
            "/api/lists",
            json={"title": "Birthday", "recipient_kind": "self"},
            headers=owner.headers,
        ).json()["id"]
        gift_id = client.post(
            f"/api/lists/{list_id}/gifts", json={"title": "Gift"}, headers=owner.headers
        ).json()["id"]
        with engine.begin() as connection:
            connection.execute(
                text("UPDATE images SET attached_at = now() WHERE id = :id"),
                {"id": image["id"]},
            )
            connection.execute(
                text("UPDATE gifts SET image_id = :image WHERE id = :gift"),
                {"image": image["id"], "gift": gift_id},
            )

    return attach


def test_an_attached_image_is_read_by_the_owners_of_its_list(
    client, ada, bob, upload, attach
):
    image = upload(account=bob)
    attach(image, owner=ada)

    assert client.get(image["url"], headers=ada.headers).status_code == 200
    assert client.get(image["thumb_url"], headers=ada.headers).status_code == 200
    # Its uploader, no owner of the list, sees nothing of it any more.
    assert not_found(client.get(image["url"], headers=bob.headers))


def test_a_row_without_its_file_is_404_and_logged(
    client, ada, upload, media_dir, caplog
):
    image = upload()
    (media_dir / "gifts" / f"{uuid.UUID(image['id']).hex}.webp").unlink()

    with caplog.at_level(logging.WARNING, logger="app.media.router"):
        response = client.get(image["url"], headers=ada.headers)

    assert not_found(response)
    assert [record.getMessage() for record in caplog.records] == [
        f"image file missing: image={image['id']} variant=full"
    ]


def test_signed_out_is_401(client, ada, upload):
    image = upload()

    assert client.post("/api/images", content=b"x").status_code == 401
    assert client.get(image["url"]).status_code == 401


def test_a_body_over_10mb_is_413_with_its_content_length(client, ada, engine):
    response = client.post(
        "/api/images",
        content=PNG_HEADER_ONLY
        + b"\x00" * (images.MAX_BYTES + 1 - len(PNG_HEADER_ONLY)),
        headers=ada.headers,
    )

    assert response.status_code == 413
    assert response.json() == {"detail": "image_too_large"}
    assert image_rows(engine) == []


def test_a_body_over_10mb_is_413_without_a_content_length(client, ada, engine):
    sent = []

    def chunks():
        for _ in range(11):
            chunk = b"\x00" * (1024 * 1024)
            sent.append(len(chunk))
            yield chunk

    response = client.post("/api/images", content=chunks(), headers=ada.headers)

    assert response.status_code == 413
    assert response.json() == {"detail": "image_too_large"}
    assert image_rows(engine) == []


def test_a_body_of_exactly_10mb_is_read(client, ada):
    # Not an image, so refused as unsupported: but read, not too large.
    response = client.post(
        "/api/images", content=b"\x00" * images.MAX_BYTES, headers=ada.headers
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "image_unsupported"}


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"just some text", "image_unsupported"),
        (b'<svg xmlns="http://www.w3.org/2000/svg"/>', "image_unsupported"),
    ],
)
def test_a_refused_image_answers_its_code(client, ada, engine, media_dir, data, code):
    response = client.post("/api/images", content=data, headers=ada.headers)

    assert response.status_code == 422
    assert response.json() == {"detail": code}
    assert image_rows(engine) == []
    assert not (media_dir / "gifts").exists() or not any(
        (media_dir / "gifts").iterdir()
    )


def test_too_many_pixels_answers_its_code(client, ada):
    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload))
            + kind
            + payload
            + struct.pack(">I", zlib.crc32(kind + payload))
        )

    data = (
        PNG_HEADER_ONLY
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 20000, 20000, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", b"junk")
        + chunk(b"IEND", b"")
    )

    response = client.post("/api/images", content=data, headers=ada.headers)

    assert response.status_code == 422
    assert response.json() == {"detail": "image_too_many_pixels"}


def test_a_busy_decoder_answers_503_after_the_wait(client, ada, engine, monkeypatch):
    monkeypatch.setattr(images, "LOCK_WAIT_SECONDS", 0.2)
    # Held by this thread: the request's worker thread waits, then gives up.
    assert images.DECODE_LOCK.acquire(timeout=5)
    try:
        response = client.post(
            "/api/images", content=encoded(picture(), "PNG"), headers=ada.headers
        )
    finally:
        images.DECODE_LOCK.release()

    assert response.status_code == 503
    assert response.json() == {"detail": "image_busy"}
    assert image_rows(engine) == []


def test_uploads_beyond_the_in_flight_cap_are_busy_unread(
    client, ada, engine, monkeypatch
):
    """Review R2-4: with every upload slot taken, an upload answers at once,
    its body unread; once a slot is free, uploads work again."""
    reads = []
    read_body = router._read_body

    async def spy(request):
        reads.append(request)
        return await read_body(request)

    monkeypatch.setattr(router, "_read_body", spy)
    data = encoded(picture(), "PNG")
    for _ in range(router.MAX_UPLOADS_IN_FLIGHT):
        assert router.UPLOAD_SLOTS.acquire(blocking=False)
    try:
        response = client.post("/api/images", content=data, headers=ada.headers)
    finally:
        for _ in range(router.MAX_UPLOADS_IN_FLIGHT):
            router.UPLOAD_SLOTS.release()

    assert response.status_code == 503
    assert response.json() == {"detail": "image_busy"}
    assert reads == []
    assert image_rows(engine) == []

    response = client.post("/api/images", content=data, headers=ada.headers)

    assert response.status_code == 201
    assert len(reads) == 1


@pytest.mark.parametrize(
    "data",
    [b"not an image", bytes(images.MAX_BYTES + 1)],
    ids=["refused", "too-large"],
)
def test_every_upload_gives_its_slot_back(client, ada, data):
    response = client.post("/api/images", content=data, headers=ada.headers)
    assert response.status_code in (413, 422)

    taken = [
        router.UPLOAD_SLOTS.acquire(blocking=False)
        for _ in range(router.MAX_UPLOADS_IN_FLIGHT)
    ]
    for got in taken:
        if got:
            router.UPLOAD_SLOTS.release()
    assert all(taken)
