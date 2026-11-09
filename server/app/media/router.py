"""The image endpoints (gift images plan D6, D7, D8, D11).

An upload, or an image URL's download, becomes a pending image of its
uploader; reading an image goes through the same access rules as its gift,
and anything the caller may not see answers the API's usual 404, the same as
a random id. Owners read through `/api/images/...`, invitees through the
occasion they were invited to.
"""

import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser, UnlockedSession, lock_signed_in
from app.accounts.models import User, UserSession
from app.db import DbSession
from app.lists.access import not_found, owns_list, visible_occasion
from app.lists.models import Gift
from app.media.gift_images import owner_image_out
from app.media.images import (
    MAX_BYTES,
    MEDIA_TYPES,
    VARIANTS,
    ImageBusy,
    ImageRejected,
    ImageTooLarge,
    Processed,
    add_image,
    image_path,
    process,
)
from app.media.models import Image
from app.media.schemas import ImageFromUrl, ImageOut
from app.safe_fetch import FetchError

_log = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["media"])

# The path holds the image id, which changes with every new image, so a
# response never changes (D8). Private: authenticated content stays out of
# shared caches.
_CACHE_CONTROL = "private, max-age=31536000, immutable"

# Uploads in flight, from reading the body to the stored image (review R2-4):
# one decoding and one waiting for the decode lock, each holding up to
# MAX_BYTES of body, so concurrent uploads cannot pile bodies up in memory
# next to the decode. One more answers image_busy at once, unread.
MAX_UPLOADS_IN_FLIGHT = 2
UPLOAD_SLOTS = threading.BoundedSemaphore(MAX_UPLOADS_IN_FLIGHT)

# Image URLs in flight, from the fetch to the stored image (review round 2,
# envelope answer a): each holds up to MAX_BYTES of body until it is decoded,
# like an upload, and a fetch to a slow host holds its slot for up to the
# fetcher's 20 s. Kept at the upload cap, and under the fetcher's 4 DNS
# threads (review R3-2). One more answers image_busy at once, unfetched.
MAX_FETCHES_IN_FLIGHT = 2
FETCH_SLOTS = threading.BoundedSemaphore(MAX_FETCHES_IN_FLIGHT)


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(
    request: Request, session: UnlockedSession, db: DbSession
) -> ImageOut:
    """The request body is the image's bytes, whatever its Content-Type."""
    try:
        # Taken before the body is read, never waited for: the event loop
        # must not block.
        if not UPLOAD_SLOTS.acquire(blocking=False):
            raise ImageBusy()
        try:
            data = await _read_body(request)
            # Decoding is CPU-bound and may wait for the decode lock: off the
            # event loop.
            processed = await run_in_threadpool(process, data)
            image = await run_in_threadpool(_stored, request, db, session, processed)
        finally:
            UPLOAD_SLOTS.release()
    except ImageRejected as exc:
        raise _refused(exc) from None
    return owner_image_out(image)


@router.post("/images/from-url", status_code=status.HTTP_201_CREATED)
def image_from_url(
    body: ImageFromUrl, request: Request, session: UnlockedSession, db: DbSession
) -> ImageOut:
    """The image at `url`, downloaded once by the server (D6).

    A sync handler, so it runs in a worker thread: the fetcher blocks, and
    runs an event loop of its own, which cannot run on the app's.
    """
    try:
        if not FETCH_SLOTS.acquire(blocking=False):
            raise ImageBusy()
        try:
            data, _ = request.app.state.url_fetcher.fetch(
                body.url, MEDIA_TYPES, MAX_BYTES
            )
            # Whatever the server said the type was, the bytes go through the
            # pipeline exactly as an upload's.
            image = _stored(request, db, session, process(data))
        finally:
            FETCH_SLOTS.release()
    except FetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=exc.code
        ) from None
    except ImageRejected as exc:
        raise _refused(exc) from None
    return owner_image_out(image)


@router.get("/images/{image_id}/{variant}")
def get_image(
    image_id: uuid.UUID,
    variant: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """WebP bytes: a pending image for its uploader, an attached one for the
    owners of its gift's list (D7)."""
    if variant not in VARIANTS:
        raise not_found()
    image = db.get(Image, image_id)
    if image is None or not _readable_by_owner(db, user, image):
        raise not_found()
    return _image_response(request, image, variant)


@router.get("/occasions/{occasion_id}/images/{image_id}/{variant}")
def get_occasion_image(
    occasion_id: uuid.UUID,
    image_id: uuid.UUID,
    variant: str,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    """WebP bytes of an image on a gift shown in the occasion, for its owners
    and its invitees (D7).

    Through `visible_occasion`, as every invitee read: an invitee of another
    occasion of the list, someone removed from this one or a stranger gets
    the 404 of a random id.
    """
    if variant not in VARIANTS:
        raise not_found()
    occasion, _ = visible_occasion(db, user, occasion_id)
    # The occasion shows its list's gifts. A detached image is on no gift.
    image = db.scalar(
        select(Image)
        .join(Gift, Gift.image_id == Image.id)
        .where(Image.id == image_id, Gift.list_id == occasion.list_id)
    )
    if image is None:
        raise not_found()
    return _image_response(request, image, variant)


def _image_response(request: Request, image: Image, variant: str) -> Response:
    path = image_path(request.app.state.settings.media_dir, image.id, variant)
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        # A row without its file: lost or deleted by hand. Not the client's
        # business, but an operator's.
        _log.warning("image file missing: image=%s variant=%s", image.id, variant)
        raise not_found() from None
    return Response(
        content=content,
        media_type="image/webp",
        headers={
            "Cache-Control": _CACHE_CONTROL,
            "ETag": f'"{image.id.hex}.{variant}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


def _stored(
    request: Request, db: Session, session: UserSession, processed: Processed
) -> Image:
    """The pending image, once the slow work is done (reserving review R9-3).

    Both routes authenticate with `unlocked_session`, so an account deletion
    does not wait for a body or a fetch: the user is locked only here, before
    anything is written, and a user deleted (or a session signed out)
    meanwhile gets the answer of a signed-out token, with no file stored.
    Nothing else is locked after the user.
    """
    user = lock_signed_in(request, db, session)
    return add_image(db, request.app.state.settings.media_dir, user, processed)


async def _read_body(request: Request) -> bytes:
    """The body, refused beyond MAX_BYTES: before reading when Content-Length
    says so, else as soon as the stream passes it (D11)."""
    length = request.headers.get("content-length", "")
    if length.isdigit() and int(length) > MAX_BYTES:
        raise ImageTooLarge()
    body = bytearray()
    async for chunk in request.stream():
        body += chunk
        if len(body) > MAX_BYTES:
            raise ImageTooLarge()
    return bytes(body)


def _readable_by_owner(db: Session, user: User, image: Image) -> bool:
    if image.attached_at is None:
        # Pending: its uploader only.
        return image.uploaded_by == user.id
    # Attached: the owners of its gift's list. Detached (no gift any more):
    # nobody, its uploader included (review R1-6).
    list_id = db.scalar(select(Gift.list_id).where(Gift.image_id == image.id))
    return list_id is not None and owns_list(db, user, list_id)


def _refused(exc: ImageRejected) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.code)
