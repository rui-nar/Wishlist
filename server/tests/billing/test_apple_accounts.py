"""`DELETE /api/me` past an Apple subscription (Apple IAP plan D9): Apple
gives the server no way to cancel it and the deletion may not be refused, so
it goes ahead with a line logged, ids only, when Apple may still charge. The
admin's deletion: tests/admin/test_admin_apple_subscriptions.py."""

import logging
from datetime import timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.accounts.models import User
from app.billing.models import Entitlement

ORIGINAL = "2000000001"


def add(engine, user_id, **fields):
    now = sessions.utc_now()
    values = {
        "user_id": user_id,
        "source": "apple",
        "external_id": ORIGINAL,
        "status": "active",
        "period_end": now + timedelta(days=100),
        "cancel_at_period_end": False,
        "started_at": now - timedelta(days=100),
        "read_at": now,
    } | fields
    with Session(engine) as db, db.begin():
        db.add(Entitlement(**values))


@pytest.fixture
def client(make_client):
    return make_client()


def deleted(engine, user_id):
    with Session(engine) as db:
        return not db.scalar(
            select(func.count()).select_from(User).where(User.id == user_id)
        )


@pytest.mark.parametrize("status", ["active", "past_due", "ended"])
def test_a_deletion_past_a_renewing_apple_subscription_is_logged(
    client, make_account, engine, caplog, status
):
    target = make_account()
    add(engine, target.id, status=status)

    with caplog.at_level(logging.WARNING, logger="app.accounts.deletion"):
        response = client.delete("/api/me", headers=target.headers)

    assert response.status_code == 204, response.text
    assert deleted(engine, target.id)
    assert [record.getMessage() for record in caplog.records] == [
        f"billing: account {target.id} deleted with Apple subscription"
        f" {ORIGINAL} still renewing"
    ]


def test_no_line_for_one_set_to_stop(client, make_account, engine, caplog):
    target = make_account()
    add(engine, target.id, cancel_at_period_end=True)

    with caplog.at_level(logging.WARNING, logger="app.accounts.deletion"):
        assert client.delete("/api/me", headers=target.headers).status_code == 204

    assert deleted(engine, target.id)
    assert caplog.records == []
