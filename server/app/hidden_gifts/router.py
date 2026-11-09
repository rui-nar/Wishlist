"""The hidden-gift endpoints: what an occasion's givers add for its list
(hidden gifts plan D7, D8).

Every route resolves its occasion through `giving_occasion`, so a recipient
gets the random-id 404 for every route and every state of the gifts (reserving
plan D4). Writes follow one lock order (D10): the user `FOR KEY SHARE` (taken
by `current_session`), the occasion `FOR SHARE`, the gift `FOR UPDATE`, which
every claim write's `FOR KEY SHARE` of the gift excludes, then its claim is
read: an edit never lands on a gift bought before it committed.

A refusal is returned, not raised, so it keeps the `code` its body needs; it
has written nothing. A 403 goes only to a giver who can see the gift, so it
reveals nothing a 404 would hide.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, and_, delete, exists, select
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.db import DbSession
from app.hidden_gifts.schemas import (
    NOT_AUTHOR,
    HiddenGiftOut,
    HiddenGiftRefusal,
    RefusalCode,
)
from app.lists.access import giving_occasion, not_found
from app.lists.models import Gift, Occasion
from app.lists.schemas import GiftCreate, GiftUpdate
from app.lists.visibility import in_occasion
from app.media.gift_images import occasion_image_out, set_gift_image
from app.media.images import ImageRejected
from app.media.models import Image
from app.reserving.models import GiftClaim
from app.reserving.release import drop_gift_activity
from app.reserving.rules import has_passed
from app.reserving.schemas import BOUGHT, PASSED

router = APIRouter(prefix="/api", tags=["hidden gifts"])

_REFUSALS: dict[RefusalCode, tuple[int, str]] = {
    NOT_AUTHOR: (
        status.HTTP_403_FORBIDDEN,
        "Only the person who added this gift can change it",
    ),
    BOUGHT: (status.HTTP_409_CONFLICT, "This gift is bought, which is final"),
    PASSED: (status.HTTP_409_CONFLICT, "This occasion has passed"),
}
_PASSED_RESPONSE = {status.HTTP_409_CONFLICT: {"model": HiddenGiftRefusal}}
_REFUSAL_RESPONSES = {
    status.HTTP_403_FORBIDDEN: {"model": HiddenGiftRefusal},
    status.HTTP_409_CONFLICT: {"model": HiddenGiftRefusal},
}


@router.get("/occasions/{occasion_id}/hidden-gifts")
def hidden_gifts(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[HiddenGiftOut]:
    # No lock: an owner's change to the occasion never waits on this read.
    occasion = giving_occasion(db, user, occasion_id, lock=False)
    rows = db.execute(
        select(Gift, Image, User.display_name)
        .outerjoin(Image, Image.id == Gift.image_id)
        .outerjoin(User, User.id == Gift.hidden_by)
        .where(_of_occasion(occasion))
        .order_by(Gift.created_at, Gift.id)
    )
    return [
        _out(gift, image, author, occasion, gift.hidden_by == user.id)
        for gift, image, author in rows
    ]


@router.post(
    "/occasions/{occasion_id}/hidden-gifts",
    status_code=status.HTTP_201_CREATED,
    response_model=HiddenGiftOut,
    responses=_PASSED_RESPONSE,
)
def add_hidden_gift(
    occasion_id: uuid.UUID,
    body: GiftCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> HiddenGiftOut | JSONResponse:
    occasion = giving_occasion(db, user, occasion_id)
    now = request.app.state.clock()
    if has_passed(occasion.date, now):
        return _refusal(PASSED)
    gift = Gift(
        for_list_id=occasion.list_id,
        hidden_occasion_id=occasion.id,
        hidden_by=user.id,
        title=body.title,
        description=body.description,
        links=body.links,
        price_amount=body.price_amount,
        price_currency=body.price_currency,
    )
    _set_image(db, user, gift, body.image_id, now)
    db.add(gift)
    db.flush()
    # Read back as stored: an amount of 149 is answered as "149.00".
    db.refresh(gift)
    return _authored_out(db, gift, user, occasion)


@router.patch(
    "/occasions/{occasion_id}/hidden-gifts/{gift_id}",
    response_model=HiddenGiftOut,
    responses=_REFUSAL_RESPONSES,
)
def update_hidden_gift(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    body: GiftUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> HiddenGiftOut | JSONResponse:
    occasion = giving_occasion(db, user, occasion_id)
    now = request.app.state.clock()
    gift = _locked_gift(db, occasion, gift_id)
    refused = _refused(db, gift, occasion, user, now)
    if refused is not None:
        return refused
    for field in body.model_fields_set - {"image_id"}:
        setattr(gift, field, getattr(body, field))
    if "image_id" in body.model_fields_set:
        _set_image(db, user, gift, body.image_id, now)
    # Either half of the price may be sent alone; the result must still be
    # both or neither.
    if (gift.price_amount is None) != (gift.price_currency is None):
        raise RequestValidationError(
            [
                {
                    "type": "value_error",
                    "loc": ("body", "price_currency"),
                    "msg": "a price has both an amount and a currency",
                }
            ]
        )
    db.flush()
    db.refresh(gift)
    return _authored_out(db, gift, user, occasion)


@router.delete(
    "/occasions/{occasion_id}/hidden-gifts/{gift_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_REFUSAL_RESPONSES,
)
def delete_hidden_gift(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    occasion = giving_occasion(db, user, occasion_id)
    gift = _locked_gift(db, occasion, gift_id)
    refused = _refused(db, gift, occasion, user, request.app.state.clock())
    if refused is not None:
        return refused
    # Its activity dropped explicitly, then the row (D15).
    drop_gift_activity(db, [gift.id])
    db.execute(delete(Gift).where(Gift.id == gift.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _of_occasion(occasion: Occasion) -> ColumnElement[bool]:
    """The occasion's hidden gifts, as its givers see them (D4)."""
    return and_(Gift.hidden_occasion_id == occasion.id, in_occasion(occasion))


def _locked_gift(db: Session, occasion: Occasion, gift_id: uuid.UUID) -> Gift:
    """The occasion's hidden gift, locked `FOR UPDATE` (D10); otherwise 404.
    A hidden gift of another occasion is one its givers cannot see."""
    gift = db.scalar(
        select(Gift)
        .where(Gift.id == gift_id, _of_occasion(occasion))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if gift is None:
        raise not_found()
    return gift


def _refused(
    db: Session, gift: Gift, occasion: Occasion, user: User, now: datetime
) -> JSONResponse | None:
    """Why the user may not change the locked gift, if they may not (D8)."""
    if gift.hidden_by != user.id:
        return _refusal(NOT_AUTHOR)
    if has_passed(occasion.date, now):
        return _refusal(PASSED)
    bought = db.scalar(
        select(
            exists().where(
                GiftClaim.gift_id == gift.id, GiftClaim.bought_at.is_not(None)
            )
        )
    )
    return _refusal(BOUGHT) if bought else None


def _refusal(code: RefusalCode) -> JSONResponse:
    status_code, detail = _REFUSALS[code]
    return JSONResponse(
        status_code=status_code, content={"detail": detail, "code": code}
    )


def _set_image(
    db: Session, user: User, gift: Gift, image_id: uuid.UUID | None, now: datetime
) -> None:
    try:
        set_gift_image(db, user, gift, image_id, now)
    except ImageRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from None


def _authored_out(
    db: Session, gift: Gift, user: User, occasion: Occasion
) -> HiddenGiftOut:
    """The gift as its author sees it after adding or editing it."""
    image = None if gift.image_id is None else db.get_one(Image, gift.image_id)
    return _out(gift, image, user.display_name, occasion, mine=True)


def _out(
    gift: Gift,
    image: Image | None,
    author: str | None,
    occasion: Occasion,
    mine: bool,
) -> HiddenGiftOut:
    return HiddenGiftOut(
        id=gift.id,
        title=gift.title,
        description=gift.description,
        links=gift.links,
        price_amount=gift.price_amount,
        price_currency=gift.price_currency,
        image=None if image is None else occasion_image_out(image, occasion.id),
        author=author,
        mine=mine,
    )
