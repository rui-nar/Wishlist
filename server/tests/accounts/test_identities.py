"""`user_for`, the account of any way of signing in (sign-in plan D1).

Google's behaviour is covered through its route, in `test_sign_in.py` and
`test_concurrent_sign_in.py`.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.accounts import identities


def count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


@pytest.fixture
def factory(engine):
    return sessionmaker(engine)


def user_for(factory, provider, subject, email, name, refresh_name=False):
    with factory.begin() as db:
        user = identities.user_for(db, provider, subject, email, name, refresh_name)
        return user.id, user.email, user.display_name


def test_a_first_sign_in_creates_the_account(factory, engine):
    _, email, name = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")

    assert (email, name) == ("a@example.com", "Ada")
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1


def test_a_later_sign_in_finds_the_same_account(factory, engine):
    first = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")
    again = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")

    assert again[0] == first[0]
    assert count(engine, "users") == 1


def test_one_address_on_two_providers_makes_two_accounts(factory, engine):
    # D1: signing in another way never joins an account of the same address.
    google = user_for(factory, identities.GOOGLE, "s", "a@example.com", "Ada")
    apple = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")
    email = user_for(factory, identities.EMAIL, "a@example.com", "a@example.com", "Ada")

    assert len({google[0], apple[0], email[0]}) == 3
    assert count(engine, "users") == 3


def test_an_absent_address_keeps_the_stored_one(factory):
    first = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")

    again = user_for(factory, identities.APPLE, "s", None, "Ignored")

    assert again == first


def test_an_address_is_refreshed_when_present(factory):
    first = user_for(factory, identities.APPLE, "s", "a@example.com", "Ada")

    again = user_for(factory, identities.APPLE, "s", "new@example.com", "Ada")

    assert again[0] == first[0]
    assert again[1] == "new@example.com"


def test_a_name_is_refreshed_only_when_asked(factory):
    user_for(factory, identities.GOOGLE, "s", "a@example.com", "Ada")

    kept = user_for(factory, identities.GOOGLE, "s", "a@example.com", "Other")
    changed = user_for(
        factory, identities.GOOGLE, "s", "a@example.com", "Other", refresh_name=True
    )

    assert kept[2] == "Ada"
    assert changed[2] == "Other"


def test_a_first_sign_in_without_an_address_makes_no_account(factory, engine):
    with pytest.raises(identities.AddressRequired), factory.begin() as db:
        identities.user_for(db, identities.APPLE, "s", None, "Ada", False)

    assert count(engine, "users") == 0
    assert count(engine, "user_identities") == 0
