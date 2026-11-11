"""An image from a URL, downloaded once by the server (gift images plan D6,
D11). The fetcher is a fake here; tests/test_safe_fetch.py tests the real one.
"""

import asyncio
import io
import uuid

import pytest
from PIL import Image
from sqlalchemy import text

from app.media import images, router
from app.safe_fetch import FetchFailed, FetchRefused, SafeFetcher

URL = "https://shop.example.com/lamp.png"


def png(size=(300, 200)) -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize(size).convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


def from_url(client, account, url=URL):
    return client.post(
        "/api/images/from-url", json={"url": url}, headers=account.headers
    )


def image_rows(engine):
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT id, uploaded_by, attached_at FROM images")
        ).all()


def test_an_image_url_becomes_a_pending_image(client, ada, engine, url_fetcher):
    url_fetcher.result = (png(), "image/png")

    response = from_url(client, ada)

    assert response.status_code == 201, response.text
    body = response.json()
    image_id = uuid.UUID(body["id"])
    assert body == {
        "id": str(image_id),
        "width": 300,
        "height": 200,
        "url": f"/api/images/{image_id}/full",
        "thumb_url": f"/api/images/{image_id}/thumb",
    }
    # Fetched once, for the image types only, capped as an upload is.
    assert url_fetcher.calls == [(URL, images.MEDIA_TYPES, images.MAX_BYTES)]
    assert image_rows(engine) == [(image_id, uuid.UUID(ada.id), None)]
    assert client.get(body["thumb_url"], headers=ada.headers).status_code == 200


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (FetchRefused("scheme"), "url_not_allowed"),
        (FetchFailed("timeout"), "url_fetch_failed"),
        ((b"<html></html>", "image/png"), "image_unsupported"),
    ],
    ids=["refused", "failed", "not an image"],
)
def test_each_failure_answers_its_code(client, ada, engine, url_fetcher, result, code):
    url_fetcher.result = result

    response = from_url(client, ada)

    assert (response.status_code, response.json()) == (422, {"detail": code})
    assert image_rows(engine) == []


def test_a_busy_decoder_answers_503(client, ada, engine, url_fetcher, monkeypatch):
    url_fetcher.result = (png(), "image/png")
    monkeypatch.setattr(images, "LOCK_WAIT_SECONDS", 0.2)
    assert images.DECODE_LOCK.acquire(timeout=5)
    try:
        response = from_url(client, ada)
    finally:
        images.DECODE_LOCK.release()

    assert (response.status_code, response.json()) == (503, {"detail": "image_busy"})
    assert image_rows(engine) == []


def test_fetches_beyond_the_in_flight_cap_are_busy_unfetched(
    client, ada, engine, url_fetcher
):
    """Review round 2, envelope answer (a): with every fetch slot taken, the
    route answers at once without fetching; once one is free, it works."""
    url_fetcher.result = (png(), "image/png")
    for _ in range(router.MAX_FETCHES_IN_FLIGHT):
        assert router.FETCH_SLOTS.acquire(blocking=False)
    try:
        response = from_url(client, ada)
    finally:
        for _ in range(router.MAX_FETCHES_IN_FLIGHT):
            router.FETCH_SLOTS.release()

    assert (response.status_code, response.json()) == (503, {"detail": "image_busy"})
    assert url_fetcher.calls == []
    assert image_rows(engine) == []

    assert from_url(client, ada).status_code == 201


def test_the_cap_stays_within_the_fetchers_dns_threads():
    # Review R3-2: more fetches in flight than DNS threads would let stalled
    # lookups starve healthy ones.
    assert 1 <= router.MAX_FETCHES_IN_FLIGHT <= 4


@pytest.mark.parametrize(
    "result",
    [
        (png(), "image/png"),
        FetchRefused("port"),
        FetchFailed("status:404"),
        (b"not an image", "image/png"),
        RuntimeError("unexpected"),
    ],
    ids=["created", "refused", "failed", "not an image", "unexpected error"],
)
def test_every_fetch_gives_its_slot_back(client, ada, url_fetcher, result):
    url_fetcher.result = result
    if isinstance(result, RuntimeError):
        # A 500, which the test client raises.
        with pytest.raises(RuntimeError):
            from_url(client, ada)
    else:
        from_url(client, ada)

    taken = [
        router.FETCH_SLOTS.acquire(blocking=False)
        for _ in range(router.MAX_FETCHES_IN_FLIGHT)
    ]
    for got in taken:
        if got:
            router.FETCH_SLOTS.release()
    assert all(taken)


def test_the_fetch_runs_outside_any_event_loop(client, ada, url_fetcher):
    """The real fetcher runs an event loop of its own (asyncio.run), which
    fails in a thread already running one: the route must call it from a
    worker thread."""
    loops = []

    def fetch(url, accept, max_bytes):
        try:
            loops.append(asyncio.get_running_loop())
        except RuntimeError:
            loops.append(None)
        return png(), "image/png"

    url_fetcher.fetch = fetch

    assert from_url(client, ada).status_code == 201
    assert loops == [None]


@pytest.mark.parametrize(
    "body",
    [{}, {"url": URL, "extra": 1}, {"url": 5}],
    ids=["no url", "unknown field", "not a string"],
)
def test_an_invalid_body_is_refused_unfetched(client, ada, url_fetcher, body):
    response = client.post("/api/images/from-url", json=body, headers=ada.headers)

    assert response.status_code == 422
    assert url_fetcher.calls == []


def test_signed_out_is_401_unfetched(client, url_fetcher):
    response = client.post("/api/images/from-url", json={"url": URL})

    assert response.status_code == 401
    assert url_fetcher.calls == []


def test_the_app_fetches_with_a_safe_fetcher_named_by_its_version(make_client):
    app = make_client(app_version="v1.2.3").app

    assert isinstance(app.state.url_fetcher, SafeFetcher)
    assert app.state.url_fetcher._user_agent == "ShushGift/v1.2.3"
