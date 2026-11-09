"""An image's upload or download at the same moment as its uploader's account
deletion or sign-out (reserving review R9-3): the deletion does not wait for
the body, the fetch or the decode; the image then answers 401 as a
signed-out token does, and nothing is stored.
"""

import io
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from PIL import Image
from sqlalchemy import text

from app.media import router

TIMEOUT_SECONDS = 10
NOT_SIGNED_IN = (401, {"detail": "Not signed in"})


def png() -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize((300, 200)).convert("RGB").save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


class Held:
    """Holds a request in its slow work until released."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.released = threading.Event()

    def wrap(self, work):
        def held(*args, **kwargs):
            self.started.set()
            # Longer than the test waits for the other request: a request
            # that waits on this one fails the test, then this goes on.
            self.released.wait(timeout=2 * TIMEOUT_SECONDS)
            return work(*args, **kwargs)

        return held


@pytest.fixture
def held_upload(client, ada, monkeypatch):
    """An upload held in its decode."""
    held = Held()
    monkeypatch.setattr(router, "process", held.wrap(router.process))

    def upload():
        return client.post("/api/images", content=png(), headers=ada.headers)

    return held, upload


@pytest.fixture
def held_download(client, ada, url_fetcher, monkeypatch):
    """An image URL's download held in its fetch."""
    held = Held()
    url_fetcher.result = (png(), "image/png")
    monkeypatch.setattr(url_fetcher, "fetch", held.wrap(url_fetcher.fetch))

    def download():
        return client.post(
            "/api/images/from-url",
            json={"url": "https://shop.example.com/lamp.png"},
            headers=ada.headers,
        )

    return held, download


@pytest.fixture(params=["upload", "from URL"])
def held_image(request):
    return request.getfixturevalue(
        "held_upload" if request.param == "upload" else "held_download"
    )


def stored(engine, media_dir):
    with engine.connect() as connection:
        rows = connection.scalar(text("SELECT count(*) FROM images"))
    files = (
        list((media_dir / "gifts").glob("*")) if (media_dir / "gifts").exists() else []
    )
    return rows, files


def run_during(held, image_request, other_request):
    """Starts the image request, runs the other one while it is held, then
    lets it go on: (the image's response, the other's)."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        imaging = pool.submit(image_request)
        try:
            assert held.started.wait(timeout=TIMEOUT_SECONDS)
            other = pool.submit(other_request).result(timeout=TIMEOUT_SECONDS)
        finally:
            held.released.set()
        return imaging.result(timeout=TIMEOUT_SECONDS), other


def test_the_image_is_stored_once_released(held_image, engine, media_dir):
    # The hold itself changes nothing.
    held, image_request = held_image
    held.released.set()

    response = image_request()

    assert response.status_code == 201, response.text
    rows, files = stored(engine, media_dir)
    assert rows == 1
    assert len(files) == 2


def test_an_account_deletion_does_not_wait_for_an_image(
    client, ada, held_image, engine, media_dir
):
    held, image_request = held_image

    response, deleted = run_during(
        held, image_request, lambda: client.delete("/api/me", headers=ada.headers)
    )

    assert deleted.status_code == 204, deleted.text
    assert (response.status_code, response.json()) == NOT_SIGNED_IN
    assert stored(engine, media_dir) == (0, [])
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM users")) == 0


def test_a_sign_out_during_an_image_leaves_nothing_stored(
    client, ada, held_image, engine, media_dir
):
    held, image_request = held_image

    response, signed_out = run_during(
        held,
        image_request,
        lambda: client.post("/api/auth/sign-out", headers=ada.headers),
    )

    assert signed_out.status_code == 204, signed_out.text
    assert (response.status_code, response.json()) == NOT_SIGNED_IN
    assert stored(engine, media_dir) == (0, [])
