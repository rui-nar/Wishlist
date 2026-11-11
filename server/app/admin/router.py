"""The admin routes (admin panel plan D2–D9).

Every route depends on `AdminUser`, or `RecentAdminUser` for a change, before
anything else: anyone but the admin gets the answer of an unknown path, never
a 401, 403, 405 or 422. That is why a body is read by a dependency of the
admin's (`_grant`, `_deletion`) rather than declared: FastAPI parses a
declared body before any dependency runs, and would answer malformed JSON
with a 422. A refusal is returned, not raised, so it keeps its `code`.
"""

import uuid
from datetime import UTC, date, datetime, time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts.deletion import delete_account
from app.accounts.deps import AdminUser, RecentAdminUser
from app.accounts.models import User
from app.accounts.schemas import EMAIL_MAX_LENGTH
from app.admin import queries
from app.admin.models import AdminAction
from app.admin.schemas import (
    AccountDeletion,
    AdminRefusal,
    AdminUserDetail,
    AdminUsersPage,
    ManualGrant,
    PremiumGrant,
)
from app.billing.models import ACTIVE, ENDED, MANUAL, Entitlement
from app.billing.schemas import BillingRefusal
from app.db import DbSession
from app.lists.access import not_found

router = APIRouter(prefix="/api/admin", tags=["admin"])

USE_ACCOUNT_SCREEN = "use_account_screen"
EMAIL_MISMATCH = "email_mismatch"
NO_MANUAL_GRANT = "no_manual_grant"
PERIOD_END_OUT_OF_RANGE = "period_end_out_of_range"
INVALID_CURSOR = "invalid_cursor"

_REFUSALS: dict[str, tuple[int, str]] = {
    USE_ACCOUNT_SCREEN: (status.HTTP_409_CONFLICT, "Use the account screen"),
    EMAIL_MISMATCH: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The address does not match",
    ),
    NO_MANUAL_GRANT: (status.HTTP_409_CONFLICT, "No manual grant"),
    PERIOD_END_OUT_OF_RANGE: (
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "The end date is out of range",
    ),
    INVALID_CURSOR: (status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor"),
}

_REFUSAL = {"model": AdminRefusal}

# The furthest a manual grant may end, and its default (D8).
MAX_GRANT_YEARS = 10
DEFAULT_GRANT_YEARS = 1

# The audit's fixed words (D4).
GRANT_PREMIUM = "grant_premium"
END_PREMIUM = "end_premium"
DELETE_ACCOUNT = "delete_account"

# Longer than any cursor `queries.encode_cursor` makes.
CURSOR_MAX_LENGTH = 200


async def _parsed[T: BaseModel](request: Request, model: type[T]) -> T:
    """The JSON body as `model`, with the 422 a declared body would get. No
    body reads as `{}`."""
    body = await request.body()
    try:
        return model.model_validate_json(body or b"{}")
    except ValidationError as error:
        raise RequestValidationError(
            [{**found, "loc": ("body", *found["loc"])} for found in error.errors()]
        ) from None


async def _grant(request: Request, _: RecentAdminUser) -> PremiumGrant:
    return await _parsed(request, PremiumGrant)


async def _deletion(request: Request, _: RecentAdminUser) -> AccountDeletion:
    return await _parsed(request, AccountDeletion)


@router.get("/users", response_model=AdminUsersPage, responses={422: _REFUSAL})
def list_users(
    request: Request,
    _: AdminUser,
    db: DbSession,
    q: Annotated[str | None, Query(max_length=EMAIL_MAX_LENGTH)] = None,
    cursor: Annotated[str | None, Query(max_length=CURSOR_MAX_LENGTH)] = None,
) -> AdminUsersPage | JSONResponse:
    """The users, newest first, 50 a page, those whose address contains `q`
    when given (D5)."""
    after = None
    if cursor is not None:
        after = queries.decode_cursor(cursor)
        if after is None:
            return _refusal(INVALID_CURSOR)
    users, following = queries.users_page(db, (q or "").strip() or None, after)
    return AdminUsersPage(
        users=queries.user_rows(db, users, request.app.state.clock()),
        next_cursor=None if following is None else queries.encode_cursor(following),
    )


@router.get("/users/{user_id}")
def read_user(
    request: Request, user_id: uuid.UUID, _: AdminUser, db: DbSession
) -> AdminUserDetail:
    """One user, with the lists they own, as counts (D6)."""
    user = db.get(User, user_id)
    if user is None:
        raise not_found()
    return _detail(db, user, request.app.state.clock())


@router.post(
    "/users/{user_id}/premium",
    response_model=AdminUserDetail,
    responses={422: _REFUSAL},
)
def grant_premium(
    request: Request,
    user_id: uuid.UUID,
    admin: RecentAdminUser,
    body: Annotated[PremiumGrant, Depends(_grant)],
    db: DbSession,
) -> AdminUserDetail | JSONResponse:
    """Premium until the date chosen, one year ahead by default (D8). A grant
    still active is replaced: the new date is the one that holds."""
    now = request.app.state.clock()
    today = now.date()
    end = body.period_end or _years_after(today, DEFAULT_GRANT_YEARS)
    if not today < end <= _years_after(today, MAX_GRANT_YEARS):
        return _refusal(PERIOD_END_OUT_OF_RANGE)
    user = _lock_target(db, user_id)
    replaced = queries.active_manual_grant(db, user.id, lock=True)
    if replaced is not None:
        _end(replaced, now)
    granted = Entitlement(
        user_id=user.id,
        source=MANUAL,
        external_id=str(uuid.uuid4()),
        status=ACTIVE,
        # Noon UTC: the date chosen, in every time zone the panel is read in.
        period_end=datetime.combine(end, time(12), tzinfo=UTC),
        cancel_at_period_end=False,
        started_at=now,
        read_at=now,
    )
    db.add(granted)
    db.flush()
    _record(
        db,
        admin,
        GRANT_PREMIUM,
        user.id,
        entitlement_id=str(granted.id),
        period_end=end.isoformat(),
        replaced_id=None if replaced is None else str(replaced.id),
    )
    return _detail(db, user, now)


@router.delete(
    "/users/{user_id}/premium",
    response_model=AdminUserDetail,
    responses={409: _REFUSAL},
)
def end_premium(
    request: Request, user_id: uuid.UUID, admin: RecentAdminUser, db: DbSession
) -> AdminUserDetail | JSONResponse:
    """Ends the admin's grant now (D8). A Stripe subscription is left alone."""
    now = request.app.state.clock()
    user = _lock_target(db, user_id)
    grant = queries.active_manual_grant(db, user.id, lock=True)
    if grant is None:
        return _refusal(NO_MANUAL_GRANT)
    _end(grant, now)
    _record(db, admin, END_PREMIUM, user.id, entitlement_id=str(grant.id))
    return _detail(db, user, now)


@router.delete(
    "/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={
        409: {"model": BillingRefusal},
        422: _REFUSAL,
        502: {"model": BillingRefusal},
    },
)
def delete_user(
    request: Request,
    user_id: uuid.UUID,
    admin: RecentAdminUser,
    body: Annotated[AccountDeletion, Depends(_deletion)],
    db: DbSession,
) -> Response:
    """Deletes the account as `DELETE /api/me` does (D9), once the admin has
    typed its address. Not the admin's own: their request holds their row, and
    their account screen does it."""
    if user_id == admin.id:
        return _refusal(USE_ACCOUNT_SCREEN)
    user = db.get(User, user_id)
    if user is None:
        raise not_found()
    if body.email.strip().casefold() != user.email.strip().casefold():
        return _refusal(EMAIL_MISMATCH)
    refusal = delete_account(db, request.app.state, user_id)
    if refusal is not None:
        return refusal
    _record(db, admin, DELETE_ACCOUNT, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Last, so every route above is matched first. No methods means every method
# (Starlette's rule): a known path with another method gets this 404, not a
# 405 (D2, review R1-2). It has no operation, so the schema leaves it out. It
# also answers `/api/admin` itself and any path with a trailing slash, which
# Starlette would otherwise redirect. Named, as FastAPI names an operation from
# its methods.
@router.api_route("{rest:path}", methods=[], operation_id="admin_unknown_path")
def unknown(_: AdminUser) -> None:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not Found")


def _detail(db: Session, user: User, now: datetime) -> AdminUserDetail:
    [row] = queries.user_rows(db, [user], now)
    grant = queries.active_manual_grant(db, user.id)
    return AdminUserDetail(
        **row.model_dump(),
        lists=queries.lists_of(db, user.id),
        manual_grant=(
            None
            if grant is None or grant.period_end is None
            else ManualGrant(period_end=grant.period_end)
        ),
    )


def _lock_target(db: Session, user_id: uuid.UUID) -> User:
    """The user whose plan changes, locked `FOR NO KEY UPDATE`: two changes
    of their plan take turns, an account's deletion waits for this one, and
    their own requests (`FOR KEY SHARE`) go on."""
    user = db.scalar(
        select(User).where(User.id == user_id).with_for_update(key_share=True)
    )
    if user is None:
        raise not_found()
    return user


def _end(grant: Entitlement, now: datetime) -> None:
    grant.status = ENDED
    grant.read_at = now
    grant.updated_at = func.now()


def _record(
    db: Session,
    admin: User,
    action: str,
    target: uuid.UUID,
    **detail: str | None,
) -> None:
    """One audit row per change (D4): ids and dates only."""
    db.add(
        AdminAction(
            admin_user_id=admin.id,
            action=action,
            target_user_id=target,
            detail=detail,
        )
    )


def _years_after(day: date, years: int) -> date:
    try:
        return day.replace(year=day.year + years)
    except ValueError:  # 29 February
        return day.replace(year=day.year + years, day=28)


def _refusal(code: str) -> JSONResponse:
    status_code, detail = _REFUSALS[code]
    return JSONResponse(
        status_code=status_code, content={"detail": detail, "code": code}
    )
