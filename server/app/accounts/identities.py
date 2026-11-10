"""Finding the account behind a sign-in, by provider (accounts plan D1).

An account is found by `(provider, subject)` only, never by its email: the
ways of signing in stay separate accounts (sign-in plan D1).
"""

from sqlalchemy import Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import User, UserIdentity

GOOGLE = "google"
APPLE = "apple"
EMAIL = "email"


class AddressRequired(Exception):
    """A first sign-in without an address: no account can be made from it."""


def user_for(
    db: Session,
    provider: str,
    subject: str,
    email: str | None,
    name: str,
    refresh_name: bool,
) -> User:
    """The account of this identity, created at its first sign-in.

    Email and, when `refresh_name` is set, name are refreshed from the sign-in,
    for display only. `email=None` keeps the stored address; on a first sign-in
    there is none to keep, so it raises `AddressRequired`.
    """
    # Locked as the update below would lock it: an account deleted at the
    # same moment either waits for this sign-in (and deletes its session
    # with it) or committed first and is not found, and the sign-in makes a
    # new account, as a moment later.
    user = db.scalar(
        _by_identity(provider, subject).with_for_update(key_share=True, of=User)
    )
    if user is None:
        if email is None:
            raise AddressRequired
        try:
            # A savepoint: if a concurrent first sign-in of the same identity
            # commits first, the unique (provider, subject) constraint refuses
            # this insert, and only the savepoint is rolled back.
            with db.begin_nested():
                user = User(email=email, display_name=name)
                db.add(user)
                db.flush()
                db.add(
                    UserIdentity(user_id=user.id, provider=provider, subject=subject)
                )
                db.flush()
            return user
        except IntegrityError:
            # Each statement sees what was committed before it started, so the
            # winner's rows are visible here.
            user = db.scalars(_by_identity(provider, subject)).one()
    if email is not None:
        user.email = email
    if refresh_name:
        user.display_name = name
    return user


def _by_identity(provider: str, subject: str) -> Select[tuple[User]]:
    return (
        select(User)
        .join(UserIdentity, UserIdentity.user_id == User.id)
        .where(UserIdentity.provider == provider, UserIdentity.subject == subject)
    )
