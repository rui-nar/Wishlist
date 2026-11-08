"""The image endpoints (gift images plan D7, D8, D11).

An upload becomes a pending image of its uploader; reading an image goes
through the same access rules as its gift, and anything the caller may not
see answers the API's usual 404, the same as a random id.
"""

import logging
import threading
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.db import DbSession
from app.lists.access import not_found, owns_list
from app.lists.models import Gift
from app.media.images import (
    MAX_BYTES,
    VARIANTS,
    ImageBusy,
    ImageRejected,
    ImageTooLarge,
    image_path,
    ingest,
)
from app.media.models import Image
from app.media.schemas import ImageOut

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


@router.post("/images", status_code=status.HTTP_201_CREATED)
async def upload_image(request: Request, user: CurrentUser, db: DbSession) -> ImageOut:
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
            image = await run_in_threadpool(
                ingest, db, request.app.state.settings.media_dir, user, data
            )
        finally:
            UPLOAD_SLOTS.release()
    except ImageRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from None
    return _image_out(image)


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


def _image_out(image: Image) -> ImageOut:
    return ImageOut(
        id=image.id,
        width=image.width,
        height=image.height,
        url=f"/api/images/{image.id}/full",
        thumb_url=f"/api/images/{image.id}/thumb",
    )
