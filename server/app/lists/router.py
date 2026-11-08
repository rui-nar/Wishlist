"""The list and gift endpoints (lists plan D8). All of them are the owner's."""

import uuid

from fastapi import APIRouter, Response, status
from fastapi.exceptions import RequestValidationError
from sqlalchemy import delete, func, select

from app.accounts.deps import CurrentUser
from app.db import DbSession
from app.lists.access import owned_gift, owned_list
from app.lists.models import OTHER, SELF, Gift, List, ListOwner
from app.lists.schemas import (
    GiftCreate,
    GiftOut,
    GiftUpdate,
    ListCreate,
    ListDetail,
    ListOut,
    ListSummary,
    ListUpdate,
)

router = APIRouter(prefix="/api", tags=["lists"])


@router.get("/lists")
def my_lists(user: CurrentUser, db: DbSession) -> list[ListSummary]:
    gift_count = (
        select(func.count(Gift.id)).where(Gift.list_id == List.id).scalar_subquery()
    )
    rows = db.execute(
        select(List, gift_count)
        .join(ListOwner, ListOwner.list_id == List.id)
        .where(ListOwner.user_id == user.id)
        .order_by(List.created_at, List.id)
    )
    return [
        ListSummary(**_list_out(found).model_dump(), gift_count=count)
        for found, count in rows
    ]


@router.post("/lists", status_code=status.HTTP_201_CREATED)
def create_list(body: ListCreate, user: CurrentUser, db: DbSession) -> ListOut:
    created = List(
        title=body.title,
        recipient_kind=body.recipient_kind,
        recipient_name=body.recipient_name,
    )
    db.add(created)
    db.flush()
    db.add(ListOwner(list_id=created.id, user_id=user.id))
    db.flush()
    return _list_out(created)


@router.get("/lists/{list_id}")
def get_list(list_id: uuid.UUID, user: CurrentUser, db: DbSession) -> ListDetail:
    found = owned_list(db, user, list_id)
    gifts = db.scalars(
        select(Gift).where(Gift.list_id == found.id).order_by(Gift.created_at, Gift.id)
    )
    return ListDetail(
        **_list_out(found).model_dump(), gifts=[_gift_out(gift) for gift in gifts]
    )


@router.patch("/lists/{list_id}")
def update_list(
    list_id: uuid.UUID, body: ListUpdate, user: CurrentUser, db: DbSession
) -> ListOut:
    found = owned_list(db, user, list_id)
    if "title" in body.model_fields_set:
        found.title = body.title
    if "recipient_name" in body.model_fields_set:
        # The kind never changes (D2), so the name follows it: a "for me" list
        # gets none, a "for someone else" list keeps one.
        if found.recipient_kind == SELF and body.recipient_name is not None:
            raise _invalid("recipient_name", "a list for me has no recipient name")
        if found.recipient_kind == OTHER and body.recipient_name is None:
            raise _invalid(
                "recipient_name", "a list for someone else needs the recipient's name"
            )
        found.recipient_name = body.recipient_name
    db.flush()
    return _list_out(found)


@router.delete("/lists/{list_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_list(list_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    found = owned_list(db, user, list_id)
    # The foreign keys cascade to its owners and gifts.
    db.execute(delete(List).where(List.id == found.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/lists/{list_id}/gifts", status_code=status.HTTP_201_CREATED)
def add_gift(
    list_id: uuid.UUID, body: GiftCreate, user: CurrentUser, db: DbSession
) -> GiftOut:
    found = owned_list(db, user, list_id)
    gift = Gift(
        list_id=found.id,
        title=body.title,
        description=body.description,
        links=body.links,
        price_amount=body.price_amount,
        price_currency=body.price_currency,
    )
    db.add(gift)
    db.flush()
    # Read back as stored: an amount of 149 is answered as "149.00".
    db.refresh(gift)
    return _gift_out(gift)


@router.patch("/gifts/{gift_id}")
def update_gift(
    gift_id: uuid.UUID, body: GiftUpdate, user: CurrentUser, db: DbSession
) -> GiftOut:
    gift = owned_gift(db, user, gift_id)
    for field in body.model_fields_set:
        setattr(gift, field, getattr(body, field))
    # Either half of the price may be sent alone; the result must still be
    # both or neither.
    if (gift.price_amount is None) != (gift.price_currency is None):
        raise _invalid("price_currency", "a price has both an amount and a currency")
    db.flush()
    db.refresh(gift)
    return _gift_out(gift)


@router.delete("/gifts/{gift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gift(gift_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    gift = owned_gift(db, user, gift_id)
    db.execute(delete(Gift).where(Gift.id == gift.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _invalid(field: str, message: str) -> RequestValidationError:
    # A rule that needs the stored object, answered as a schema rule would be:
    # 422, through the app's validation handler.
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", field), "msg": message}]
    )


def _list_out(found: List) -> ListOut:
    return ListOut(
        id=found.id,
        title=found.title,
        recipient_kind=found.recipient_kind,
        recipient_name=found.recipient_name,
    )


def _gift_out(gift: Gift) -> GiftOut:
    return GiftOut(
        id=gift.id,
        list_id=gift.list_id,
        title=gift.title,
        description=gift.description,
        links=gift.links,
        price_amount=gift.price_amount,
        price_currency=gift.price_currency,
    )
