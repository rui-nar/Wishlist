"""The account's email switch and language, and unsubscribing from an email
link (comments plan D17, D18)."""

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import update

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.db import DbSession
from app.lists.access import not_found
from app.notifications.unsubscribe import read_token

router = APIRouter(prefix="/api", tags=["notifications"])

Language = Literal["en", "fr"]


class PreferencesPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Either or both: an absent field stays as it is, and null is refused
    # (the columns have no null), since a default is not validated.
    email_notifications: bool = Field(default=None)
    language: Language = Field(default=None)


class PreferencesOut(BaseModel):
    email_notifications: bool
    language: Language


@router.get("/me/preferences")
def preferences(user: CurrentUser) -> PreferencesOut:
    return _preferences_out(user)


@router.patch("/me/preferences")
def update_preferences(body: PreferencesPatch, user: CurrentUser) -> PreferencesOut:
    for field in body.model_fields_set:
        setattr(user, field, getattr(body, field))
    return _preferences_out(user)


# No session: the link speaks for its own account. No body parameter, so any
# body is accepted and never read: this is the RFC 8058 one-click target, and
# a mail app posts a form to it. Never a GET: mail scanners open links.
@router.post("/unsubscribe/{token}", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(token: str, request: Request, db: DbSession) -> Response:
    user_id = read_token(request.app.state.settings.notification_secret, token)
    if user_id is None:
        raise not_found()
    # A single statement that matches no row for a deleted account: the same
    # answer, which says nothing about the account.
    db.execute(update(User).where(User.id == user_id).values(email_notifications=False))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _preferences_out(user: User) -> PreferencesOut:
    return PreferencesOut(
        email_notifications=user.email_notifications, language=user.language
    )
