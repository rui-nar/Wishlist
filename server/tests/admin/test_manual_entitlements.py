"""The `manual` source of entitlements, as far as U1 goes (admin panel plan
D8): the schema accepts it, and an expired grant is not a lost event (review
R1-6)."""

import logging
import uuid
from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.entitlements import is_premium, warn_if_lapsed
from app.billing.models import ACTIVE, MANUAL, STRIPE, BillingCustomer, Entitlement


def add_user(db: Session) -> uuid.UUID:
    user = User(email=f"{uuid.uuid4().hex}@example.com", display_name="U")
    db.add(user)
    db.flush()
    return user.id


def add_entitlement(db, user_id, source, period_end, now):
    entitlement = Entitlement(
        user_id=user_id,
        source=source,
        external_id=str(uuid.uuid4()),
        status=ACTIVE,
        period_end=period_end,
        cancel_at_period_end=False,
        read_at=now,
    )
    db.add(entitlement)
    db.flush()
    return entitlement.id


def test_a_manual_grant_is_stored_and_grants_premium(engine, now):
    with Session(engine) as db, db.begin():
        user_id = add_user(db)
        add_entitlement(db, user_id, MANUAL, now + timedelta(days=365), now)

        assert is_premium(db, user_id, now)


def test_an_unknown_source_is_still_refused(engine, now):
    with pytest.raises(IntegrityError), Session(engine) as db, db.begin():
        user_id = add_user(db)
        add_entitlement(db, user_id, "gift", now + timedelta(days=1), now)


def test_a_billing_customer_may_be_manual(engine):
    with Session(engine) as db, db.begin():
        user_id = add_user(db)
        db.add(BillingCustomer(user_id=user_id, source=MANUAL, customer_id="x"))


def test_an_expired_manual_grant_logs_nothing_and_a_stripe_one_still_does(
    engine, now, caplog
):
    expired = now - timedelta(days=10)
    with Session(engine) as db, db.begin():
        user_id = add_user(db)
        manual = add_entitlement(db, user_id, MANUAL, expired, now)
        stripe = add_entitlement(db, user_id, STRIPE, expired, now)

        with caplog.at_level(logging.WARNING, logger="app.billing.entitlements"):
            warn_if_lapsed(db, user_id, now)

    messages = [record.getMessage() for record in caplog.records]
    assert messages == [f"entitlement past its grace: id={stripe} source=stripe"]
    assert all(str(manual) not in message for message in messages)
