"""The list, gift, occasion and sharing endpoints (lists plan D8).

Lists, gifts and occasions are their owners' business. Invitees reach an
occasion through the join endpoints, `GET /api/shared` and
`GET /api/occasions/{id}`, which answers each role with its own model. A
gift's image is attached, replaced and removed through the gift's own
endpoints (gift images plan D1, D11).
"""

import secrets
import uuid
from collections import defaultdict
from collections.abc import Iterable
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import ColumnElement, delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.db import DbSession
from app.lists.access import (
    INVITEE,
    OWNER,
    not_found,
    owned_gift,
    owned_list,
    owned_occasion,
    owns_list,
    visible_occasion,
)
from app.lists.models import (
    OTHER,
    SELF,
    Gift,
    List,
    ListOwner,
    Occasion,
    OccasionMember,
    OccasionRemoval,
)
from app.lists.schemas import (
    GiftCreate,
    GiftOut,
    GiftUpdate,
    InviteeOccasionView,
    Joined,
    JoinPreview,
    JoinRequest,
    ListCreate,
    ListDetail,
    ListOut,
    ListSummary,
    ListUpdate,
    MemberOut,
    OccasionCreate,
    OccasionOut,
    OccasionUpdate,
    OccasionView,
    OwnerOccasionView,
    SharedGiftOut,
    SharedOccasion,
)
from app.media.gift_images import (
    occasion_image_out,
    owner_image_out,
    set_gift_image,
)
from app.media.images import ImageRejected
from app.media.models import Image

router = APIRouter(prefix="/api", tags=["lists"])


@router.get("/lists")
def my_lists(user: CurrentUser, db: DbSession) -> list[ListSummary]:
    gift_count = (
        select(func.count(Gift.id)).where(Gift.list_id == List.id).scalar_subquery()
    )
    occasion_count = (
        select(func.count(Occasion.id))
        .where(Occasion.list_id == List.id)
        .scalar_subquery()
    )
    rows = db.execute(
        select(List, gift_count, occasion_count)
        .join(ListOwner, ListOwner.list_id == List.id)
        .where(ListOwner.user_id == user.id)
        .order_by(List.created_at, List.id)
    )
    return [
        ListSummary(
            **_list_out(found).model_dump(),
            gift_count=gifts,
            occasion_count=occasions,
        )
        for found, gifts, occasions in rows
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
    return ListDetail(
        **_list_out(found).model_dump(),
        gifts=[_gift_out(gift, image) for gift, image in _gifts(db, found.id)],
        occasions=_occasions_out(db, Occasion.list_id == found.id),
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
    # The foreign keys cascade to its owners, gifts, occasions, members and
    # removals.
    db.execute(delete(List).where(List.id == found.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/lists/{list_id}/gifts", status_code=status.HTTP_201_CREATED)
def add_gift(
    list_id: uuid.UUID,
    body: GiftCreate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
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
    _set_image(db, user, gift, body.image_id, request.app.state.clock())
    db.add(gift)
    db.flush()
    # Read back as stored: an amount of 149 is answered as "149.00".
    db.refresh(gift)
    return _gift_out(gift, _image_of(db, gift))


@router.patch("/gifts/{gift_id}")
def update_gift(
    gift_id: uuid.UUID,
    body: GiftUpdate,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> GiftOut:
    gift = owned_gift(db, user, gift_id)
    if "image_id" in body.model_fields_set:
        # Locked until the request commits: two changes of the image at the
        # same moment take turns, so each one detaches, and stamps, the image
        # the other attached.
        db.refresh(gift, with_for_update=True)
    for field in body.model_fields_set - {"image_id"}:
        setattr(gift, field, getattr(body, field))
    if "image_id" in body.model_fields_set:
        _set_image(db, user, gift, body.image_id, request.app.state.clock())
    # Either half of the price may be sent alone; the result must still be
    # both or neither.
    if (gift.price_amount is None) != (gift.price_currency is None):
        raise _invalid("price_currency", "a price has both an amount and a currency")
    db.flush()
    db.refresh(gift)
    return _gift_out(gift, _image_of(db, gift))


@router.delete("/gifts/{gift_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_gift(gift_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    gift = owned_gift(db, user, gift_id)
    db.execute(delete(Gift).where(Gift.id == gift.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/lists/{list_id}/occasions", status_code=status.HTTP_201_CREATED)
def create_occasion(
    list_id: uuid.UUID, body: OccasionCreate, user: CurrentUser, db: DbSession
) -> OccasionOut:
    found = owned_list(db, user, list_id)
    # No link yet: the owner creates one when sharing (D5).
    occasion = Occasion(list_id=found.id, name=body.name, date=body.date)
    db.add(occasion)
    db.flush()
    return _occasion_out(db, occasion)


@router.get("/occasions/{occasion_id}")
def get_occasion(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OccasionView:
    occasion, role = visible_occasion(db, user, occasion_id)
    found = db.get_one(List, occasion.list_id)
    gifts = _gifts(db, found.id)
    if role == OWNER:
        return OwnerOccasionView(
            **_occasion_out(db, occasion).model_dump(),
            role=OWNER,
            list=_list_out(found),
            gifts=[_gift_out(gift, image) for gift, image in gifts],
        )
    # The invitee's own model: no token, no members, no other occasion (D8).
    shared = _shared_occasion(occasion, found, _owner_names(db, [found.id]))
    return InviteeOccasionView(
        **shared.model_dump(),
        role=INVITEE,
        gifts=[_shared_gift_out(gift, image, occasion.id) for gift, image in gifts],
    )


@router.patch("/occasions/{occasion_id}")
def update_occasion(
    occasion_id: uuid.UUID, body: OccasionUpdate, user: CurrentUser, db: DbSession
) -> OccasionOut:
    occasion = owned_occasion(db, user, occasion_id)
    for field in body.model_fields_set:
        setattr(occasion, field, getattr(body, field))
    db.flush()
    return _occasion_out(db, occasion)


@router.delete("/occasions/{occasion_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_occasion(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    occasion = owned_occasion(db, user, occasion_id)
    # The foreign keys cascade to its members and removals.
    db.execute(delete(Occasion).where(Occasion.id == occasion.id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/occasions/{occasion_id}/link")
def create_link(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> OccasionOut:
    occasion = owned_occasion(db, user, occasion_id)
    # A new token every time, so regenerating makes the previous link stop
    # working; members who already joined keep their access (D5).
    occasion.join_token = secrets.token_urlsafe(16)
    db.flush()
    return _occasion_out(db, occasion)


@router.delete("/occasions/{occasion_id}/link", status_code=status.HTTP_204_NO_CONTENT)
def revoke_link(occasion_id: uuid.UUID, user: CurrentUser, db: DbSession) -> Response:
    occasion = owned_occasion(db, user, occasion_id)
    occasion.join_token = None
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/occasions/{occasion_id}/members")
def list_members(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> list[MemberOut]:
    occasion = owned_occasion(db, user, occasion_id)
    joined = db.execute(
        select(User.id, User.display_name)
        .join(OccasionMember, OccasionMember.user_id == User.id)
        .where(OccasionMember.occasion_id == occasion.id)
        .order_by(OccasionMember.joined_at, User.id)
    )
    removed = db.execute(
        select(User.id, User.display_name)
        .join(OccasionRemoval, OccasionRemoval.user_id == User.id)
        .where(OccasionRemoval.occasion_id == occasion.id)
        .order_by(OccasionRemoval.removed_at, User.id)
    )
    # Members first, in the order they joined; then the removed people, so
    # the owner can allow one again.
    return [
        MemberOut(user_id=member, display_name=name, removed=False)
        for member, name in joined
    ] + [
        MemberOut(user_id=member, display_name=name, removed=True)
        for member, name in removed
    ]


@router.delete(
    "/occasions/{occasion_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    occasion_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    occasion = owned_occasion(db, user, occasion_id)
    # Exclusive until this request commits: a join of the same occasion waits
    # (its share lock), then finds the removal and answers 404. Without it, a
    # join that checked for a removal just before this one committed would
    # make the removed person a member again.
    db.execute(select(Occasion.id).where(Occasion.id == occasion.id).with_for_update())
    # Locked so that an account deleted at the same moment either waits for
    # the removal or is not found here, never a 500 on a removal of no one.
    removed = db.get(User, user_id, with_for_update={"read": True, "key_share": True})
    # Owners are never invitees (D6), so there is no one to remove: the same
    # answer as an unknown user.
    if removed is None or owns_list(db, removed, occasion.list_id):
        raise not_found()
    # Whether or not they are still a member: someone who left a moment ago is
    # kept out all the same.
    db.execute(
        delete(OccasionMember).where(
            OccasionMember.occasion_id == occasion.id,
            OccasionMember.user_id == user_id,
        )
    )
    # Effective on its own: no link, current or old, lets them back until an
    # owner allows them again (D4). Removing twice leaves one row.
    db.execute(
        insert(OccasionRemoval)
        .values(occasion_id=occasion.id, user_id=user_id)
        .on_conflict_do_nothing()
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/occasions/{occasion_id}/removals/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def allow_again(
    occasion_id: uuid.UUID, user_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    occasion = owned_occasion(db, user, occasion_id)
    if db.get(User, user_id) is None:
        raise not_found()
    # Not removed, or allowed again at the same moment, is the same outcome:
    # nothing keeps them out. Allowing does not rejoin: they need a current
    # link.
    db.execute(
        delete(OccasionRemoval).where(
            OccasionRemoval.occasion_id == occasion.id,
            OccasionRemoval.user_id == user_id,
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/occasions/{occasion_id}/membership", status_code=status.HTTP_204_NO_CONTENT
)
def leave_occasion(
    occasion_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    occasion, role = visible_occasion(db, user, occasion_id)
    # Owners are not members: they have nothing to leave.
    if role != INVITEE:
        raise not_found()
    _delete_membership(db, occasion.id, user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/shared")
def shared_with_me(user: CurrentUser, db: DbSession) -> list[SharedOccasion]:
    rows = db.execute(
        select(Occasion, List)
        .join(OccasionMember, OccasionMember.occasion_id == Occasion.id)
        .join(List, List.id == Occasion.list_id)
        .where(OccasionMember.user_id == user.id)
        .order_by(Occasion.date, Occasion.name, Occasion.id)
    ).all()
    names = _owner_names(db, {found.id for _, found in rows})
    return [_shared_occasion(occasion, found, names) for occasion, found in rows]


@router.post("/join/preview")
def preview_join(body: JoinRequest, user: CurrentUser, db: DbSession) -> JoinPreview:
    occasion = _occasion_by_token(db, body.token)
    found = db.get_one(List, occasion.list_id)
    shared = _shared_occasion(occasion, found, _owner_names(db, [found.id]))
    # No occasion id unless the caller is already its member.
    common = shared.model_dump(exclude={"id"})
    if owns_list(db, user, found.id):
        # The client opens the list instead of offering to join (D6).
        return JoinPreview(**common, role="owner", list_id=found.id, occasion_id=None)
    if _removed(db, occasion.id, user.id):
        raise not_found()
    if db.get(OccasionMember, (occasion.id, user.id)) is not None:
        return JoinPreview(
            **common, role="member", list_id=None, occasion_id=occasion.id
        )
    return JoinPreview(**common, role="none", list_id=None, occasion_id=None)


@router.post("/join", response_model=Joined)
def join(body: JoinRequest, user: CurrentUser, db: DbSession) -> Joined | JSONResponse:
    # Locked until this request commits, so an occasion deleted, its link
    # revoked or regenerated, or this user removed, at the same moment either
    # waits for the join or turns it into a 404: never a 500 on a member of a
    # deleted occasion, nor a removed person who is a member again.
    occasion = _occasion_by_token(db, body.token, lock=True)
    if owns_list(db, user, occasion.list_id):
        # An owner, recipient or not, never becomes an invitee of their own
        # list (D6); the body names the list to open instead.
        return JSONResponse(
            status_code=status.HTTP_409_CONFLICT,
            content={"detail": "You own this list", "list_id": str(occasion.list_id)},
        )
    # Removed by an owner: the same answer as an unknown token, whatever the
    # link (D4).
    if _removed(db, occasion.id, user.id):
        raise not_found()
    # Joining twice is not an error and leaves one row.
    db.execute(
        insert(OccasionMember)
        .values(occasion_id=occasion.id, user_id=user.id)
        .on_conflict_do_nothing()
    )
    return Joined(occasion_id=occasion.id)


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


def _set_image(
    db: Session, user: User, gift: Gift, image_id: uuid.UUID | None, now: datetime
) -> None:
    try:
        set_gift_image(db, user, gift, image_id, now)
    except ImageRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from None


def _image_of(db: Session, gift: Gift) -> Image | None:
    return None if gift.image_id is None else db.get_one(Image, gift.image_id)


def _gift_out(gift: Gift, image: Image | None) -> GiftOut:
    return GiftOut(
        id=gift.id,
        list_id=gift.list_id,
        title=gift.title,
        description=gift.description,
        links=gift.links,
        price_amount=gift.price_amount,
        price_currency=gift.price_currency,
        image=None if image is None else owner_image_out(image),
    )


def _gifts(db: Session, list_id: uuid.UUID) -> list[tuple[Gift, Image | None]]:
    """The list's gifts, oldest first (D3), each with its image."""
    rows = db.execute(
        select(Gift, Image)
        .outerjoin(Image, Image.id == Gift.image_id)
        .where(Gift.list_id == list_id)
        .order_by(Gift.created_at, Gift.id)
    )
    return [(gift, image) for gift, image in rows]


def _shared_gift_out(
    gift: Gift, image: Image | None, occasion_id: uuid.UUID
) -> SharedGiftOut:
    return SharedGiftOut(
        id=gift.id,
        title=gift.title,
        description=gift.description,
        links=gift.links,
        price_amount=gift.price_amount,
        price_currency=gift.price_currency,
        image=None if image is None else occasion_image_out(image, occasion_id),
    )


def _occasions_out(db: Session, where: ColumnElement[bool]) -> list[OccasionOut]:
    """The occasions matching `where`, by date, with their member counts."""
    member_count = (
        select(func.count())
        .select_from(OccasionMember)
        .where(OccasionMember.occasion_id == Occasion.id)
        .scalar_subquery()
    )
    rows = db.execute(
        select(Occasion, member_count)
        .where(where)
        .order_by(Occasion.date, Occasion.created_at, Occasion.id)
    )
    return [
        OccasionOut(
            id=occasion.id,
            list_id=occasion.list_id,
            name=occasion.name,
            date=occasion.date,
            join_token=occasion.join_token,
            member_count=count,
        )
        for occasion, count in rows
    ]


def _occasion_out(db: Session, occasion: Occasion) -> OccasionOut:
    return _occasions_out(db, Occasion.id == occasion.id)[0]


def _owner_names(
    db: Session, list_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[str]]:
    """The display names of each list's owners, alphabetically."""
    names: dict[uuid.UUID, list[str]] = defaultdict(list)
    rows = db.execute(
        select(ListOwner.list_id, User.display_name)
        .join(User, User.id == ListOwner.user_id)
        .where(ListOwner.list_id.in_(list(list_ids)))
        .order_by(User.display_name, User.id)
    )
    for list_id, name in rows:
        names[list_id].append(name)
    return names


def _shared_occasion(
    occasion: Occasion, found: List, owner_names: dict[uuid.UUID, list[str]]
) -> SharedOccasion:
    names = owner_names[found.id]
    return SharedOccasion(
        id=occasion.id,
        name=occasion.name,
        date=occasion.date,
        list_title=found.title,
        # The owners of a "for me" list are its recipients (D8).
        recipient_name=(
            found.recipient_name if found.recipient_kind == OTHER else ", ".join(names)
        ),
        owner_names=names,
    )


def _occasion_by_token(db: Session, token: str, lock: bool = False) -> Occasion:
    """The occasion a link joins; 404 for an unknown or revoked token."""
    query = select(Occasion).where(Occasion.join_token == token)
    if lock:
        query = query.with_for_update(read=True)
    occasion = db.scalar(query)
    if occasion is None:
        raise not_found()
    return occasion


def _removed(db: Session, occasion_id: uuid.UUID, user_id: uuid.UUID) -> bool:
    return db.get(OccasionRemoval, (occasion_id, user_id)) is not None


def _delete_membership(db: Session, occasion_id: uuid.UUID, user_id: uuid.UUID) -> None:
    deleted = db.execute(
        delete(OccasionMember).where(
            OccasionMember.occasion_id == occasion_id,
            OccasionMember.user_id == user_id,
        )
    )
    # Not a member, or no longer one: removed, or left, at the same moment.
    if deleted.rowcount == 0:
        raise not_found()
