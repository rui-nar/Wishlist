"""Images on gifts (gift images plan D1, D7, D9, D11).

A gift's image changes through the gift's create or update body: an id
attaches a pending image, null removes the current one. Neither touches a
file: an image no gift points at any more is detached, and its row and files
are left to the purge (D9).
"""

import uuid
from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.lists.models import Gift
from app.media.images import ATTACHABLE_FOR, ImageRejected
from app.media.models import Image, MediaOrphan
from app.media.schemas import ImageOut


class ImageNotAttachable(ImageRejected):
    """Not a pending image of the caller. One answer whatever the reason, so
    another user's image id cannot be probed (D11)."""

    code = "image_not_attachable"


class ImageExpired(ImageRejected):
    """The caller's pending image, past ATTACHABLE_FOR."""

    code = "image_expired"


def set_gift_image(
    db: Session, user: User, gift: Gift, image_id: uuid.UUID | None, now: datetime
) -> None:
    """Points the gift at `image_id`, or at no image for None.

    Attaching takes a pending image of `user`, younger than ATTACHABLE_FOR,
    and sets its `attached_at` (review R1-6); anything else raises an
    `ImageRejected`. The image the gift had is detached, its orphan record
    stamped `now` in the same transaction (review R1-1). The gift's current
    image given again changes nothing.
    """
    if image_id == gift.image_id:
        return
    if image_id is not None:
        _attachable(db, user, image_id, now).attached_at = now
    detached = gift.image_id
    gift.image_id = image_id
    if detached is not None:
        stamp_orphan(db, detached, now)


def _attachable(db: Session, user: User, image_id: uuid.UUID, now: datetime) -> Image:
    # Locked until the request commits: the same image attached twice at the
    # same moment finds it attached the second time.
    image = db.get(Image, image_id, with_for_update=True, populate_existing=True)
    if image is None or image.uploaded_by != user.id or image.attached_at is not None:
        raise ImageNotAttachable()
    if image.created_at <= now - ATTACHABLE_FOR:
        raise ImageExpired()
    return image


def stamp_orphan(db: Session, image_id: uuid.UUID, now: datetime) -> None:
    """Records the image's file stem as unreferenced since `now`, whatever an
    older record said (D9, review R1-1)."""
    statement = insert(MediaOrphan).values(name=image_id.hex, first_seen_at=now)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[MediaOrphan.name],
            set_={"first_seen_at": statement.excluded.first_seen_at},
        )
    )


def owner_image_out(image: Image) -> ImageOut:
    """The image as its uploader or its gift's owners read it."""
    return _image_out(image, f"/api/images/{image.id}")


def occasion_image_out(image: Image, occasion_id: uuid.UUID) -> ImageOut:
    """The image as an occasion's invitees read it: through the occasion (D7)."""
    return _image_out(image, f"/api/occasions/{occasion_id}/images/{image.id}")


def _image_out(image: Image, path: str) -> ImageOut:
    return ImageOut(
        id=image.id,
        width=image.width,
        height=image.height,
        url=f"{path}/full",
        thumb_url=f"{path}/thumb",
    )
