"""What the admin changes (admin panel plan D3, D4, D8, D9): manual Premium
granted and ended, an account deleted as `DELETE /api/me` deletes it. Each
change needs a recent sign-in and leaves one audit row of ids and dates.
"""

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.billing.entitlements import is_premium
from app.billing.stripe_gateway import GatewayUnavailable


def premium(client, admin, user_id, **body):
    return client.post(
        f"/api/admin/users/{user_id}/premium", json=body, headers=admin.headers
    )


def end_premium(client, admin, user_id):
    return client.delete(f"/api/admin/users/{user_id}/premium", headers=admin.headers)


def delete(client, admin, user_id, email):
    return client.request(
        "DELETE",
        f"/api/admin/users/{user_id}",
        json={"email": email},
        headers=admin.headers,
    )


def audit(engine):
    with engine.connect() as connection:
        return [
            (row.admin_user_id, row.action, row.target_user_id, row.detail)
            for row in connection.execute(
                text(
                    "SELECT admin_user_id, action, target_user_id, detail"
                    " FROM admin_actions ORDER BY created_at, action"
                )
            )
        ]


def entitlements(engine, user_id):
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT id, source, status, period_end FROM entitlements"
                " WHERE user_id = :user ORDER BY created_at, source"
            ),
            {"user": user_id},
        ).all()


def premium_at(engine, user_id, at):
    with Session(engine) as db:
        return is_premium(db, user_id, at)


def add_stripe(engine, user_id, period_end, customer=True):
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO entitlements (id, user_id, source, external_id, status,"
                " period_end, cancel_at_period_end, read_at)"
                " VALUES (:id, :user, 'stripe', 'sub_1', 'active', :end, false, :end)"
            ),
            {"id": uuid.uuid4(), "user": user_id, "end": period_end},
        )
        if customer:
            connection.execute(
                text(
                    "INSERT INTO billing_customers (user_id, source, customer_id)"
                    " VALUES (:user, 'stripe', 'cus_1')"
                ),
                {"user": user_id},
            )


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 12, tzinfo=UTC)


@pytest.fixture
def target(make_account):
    return make_account()


# Granting and ending manual Premium (D8).


def test_a_grant_is_one_year_by_default_and_grants_premium(
    client, admin, target, engine, now
):
    response = premium(client, admin, target.id)

    assert response.status_code == 200, response.text
    end = noon(date(2027, 11, 10))
    assert response.json()["plan"] == {
        "plan": "premium",
        "source": "manual",
        "until": "2027-11-10T12:00:00Z",
    }
    assert response.json()["manual_grant"] == {"period_end": "2027-11-10T12:00:00Z"}
    [(granted, source, status, period_end)] = entitlements(engine, target.id)
    assert (source, status, period_end) == ("manual", "active", end)
    assert premium_at(engine, target.id, now)
    assert audit(engine) == [
        (
            admin.id,
            "grant_premium",
            target.id,
            {
                "entitlement_id": str(granted),
                "period_end": "2027-11-10",
                "replaced_id": None,
            },
        )
    ]
    # The person's own plan screen says so.
    billing = client.get("/api/billing", headers=target.headers).json()
    assert (billing["plan"], billing["source"]) == ("premium", "manual")


@pytest.mark.parametrize("day", ["2026-11-11", "2036-11-10"])
def test_a_grant_ends_on_the_date_chosen_up_to_10_years_ahead(
    client, admin, target, engine, day
):
    response = premium(client, admin, target.id, period_end=day)

    assert response.status_code == 200, response.text
    [(_, _, _, period_end)] = entitlements(engine, target.id)
    assert period_end == noon(date.fromisoformat(day))


@pytest.mark.parametrize("day", ["2026-11-10", "2026-01-01", "2036-11-11"])
def test_a_date_not_ahead_or_beyond_10_years_is_refused(
    client, admin, target, engine, day
):
    response = premium(client, admin, target.id, period_end=day)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The end date is out of range",
        "code": "period_end_out_of_range",
    }
    assert entitlements(engine, target.id) == []
    assert audit(engine) == []


@pytest.mark.parametrize(
    "body", [b"{not json", b'{"period_end": "soon"}', b"[]"], ids=str
)
def test_a_malformed_body_gets_the_validation_answer(client, admin, target, body):
    response = client.post(
        f"/api/admin/users/{target.id}/premium",
        content=body,
        headers=admin.headers | {"Content-Type": "application/json"},
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"][0] == "body"


def test_a_second_grant_replaces_the_first(client, admin, target, engine):
    premium(client, admin, target.id, period_end="2027-01-01")
    response = premium(client, admin, target.id, period_end="2028-01-01")

    assert response.status_code == 200, response.text
    (first, *_), (second, *_) = rows = entitlements(engine, target.id)
    assert [(status, end) for _, _, status, end in rows] == [
        ("ended", noon(date(2027, 1, 1))),
        ("active", noon(date(2028, 1, 1))),
    ]
    assert audit(engine)[-1][3] == {
        "entitlement_id": str(second),
        "period_end": "2028-01-01",
        "replaced_id": str(first),
    }


def test_ending_a_grant_makes_the_plan_free(client, admin, target, engine, now):
    premium(client, admin, target.id)
    [(granted, *_)] = entitlements(engine, target.id)

    response = end_premium(client, admin, target.id)

    assert response.status_code == 200, response.text
    assert response.json()["plan"] == {"plan": "free", "source": None, "until": None}
    assert response.json()["manual_grant"] is None
    assert [status for _, _, status, _ in entitlements(engine, target.id)] == ["ended"]
    assert not premium_at(engine, target.id, now)
    assert audit(engine)[-1] == (
        admin.id,
        "end_premium",
        target.id,
        {"entitlement_id": str(granted)},
    )


def test_ending_with_no_grant_is_refused_and_records_nothing(
    client, admin, target, engine
):
    response = end_premium(client, admin, target.id)

    assert response.status_code == 409
    assert response.json()["code"] == "no_manual_grant"
    assert audit(engine) == []


def test_a_grant_coexists_with_a_stripe_subscription(
    client, admin, target, engine, now
):
    stripe_end = now + timedelta(days=30)
    add_stripe(engine, target.id, stripe_end)

    granted = premium(client, admin, target.id).json()
    # The longest lasting is shown, as `GET /api/billing` shows it.
    assert granted["plan"]["source"] == "manual"
    # The person can still reach Stripe's portal (review R1-3).
    billing = client.get("/api/billing", headers=target.headers).json()
    assert billing["source"] == "manual"

    ended = end_premium(client, admin, target.id).json()

    assert ended["plan"] == {
        "plan": "premium",
        "source": "stripe",
        "until": stripe_end.isoformat().replace("+00:00", "Z"),
    }
    assert [
        (source, status) for _, source, status, _ in entitlements(engine, target.id)
    ] == [("stripe", "active"), ("manual", "ended")]


@pytest.mark.parametrize(
    "call",
    [
        lambda client, admin, target: premium(client, admin, target.id),
        lambda client, admin, target: end_premium(client, admin, target.id),
        lambda client, admin, target: delete(client, admin, target.id, "x@y.z"),
    ],
    ids=["grant", "end", "delete"],
)
def test_an_unknown_user_is_not_found(client, admin, call):
    gone = type("Gone", (), {"id": uuid.uuid4()})()

    assert call(client, admin, gone).status_code == 404


@pytest.mark.parametrize(
    "call",
    [
        lambda client, admin, target: premium(client, admin, target.id),
        lambda client, admin, target: end_premium(client, admin, target.id),
        lambda client, admin, target: delete(
            client, admin, target.id, "anything@example.com"
        ),
    ],
    ids=["grant", "end", "delete"],
)
def test_an_admin_session_over_12_hours_old_must_sign_in_again_to_change(
    make_client, make_account, target, engine, now, call
):
    old = make_account(signed_in_at=now - timedelta(hours=13))
    client = make_client(admin_user_ids=str(old.id))
    client.app.state.clock = lambda: now

    assert client.get("/api/admin/users", headers=old.headers).status_code == 200
    response = call(client, old, target)

    assert response.status_code == 401
    assert response.json() == {"detail": "reauth_required"}
    assert entitlements(engine, target.id) == []
    assert audit(engine) == []


# Deleting an account (D9).


def user_exists(engine, user_id):
    with engine.connect() as connection:
        return bool(
            connection.scalar(
                text("SELECT count(*) FROM users WHERE id = :id"), {"id": user_id}
            )
        )


def test_the_typed_address_confirms_the_deletion_case_insensitively(
    client, admin, target, engine, set_email, caplog
):
    set_email(target.id, "Target.Person@Example.com")
    premium(client, admin, target.id)
    listed = client.post(
        "/api/lists",
        json={"title": "Mine", "recipient_kind": "self"},
        headers=target.headers,
    ).json()["id"]

    with caplog.at_level(logging.DEBUG):
        response = delete(client, admin, target.id, "  target.person@EXAMPLE.COM ")

    assert response.status_code == 204, response.text
    assert not user_exists(engine, target.id)
    with engine.connect() as connection:
        assert 0 == connection.scalar(
            text("SELECT count(*) FROM lists WHERE id = :id"), {"id": listed}
        )
    # The manual grant went with the account.
    assert entitlements(engine, target.id) == []
    assert audit(engine)[-1] == (admin.id, "delete_account", target.id, {})
    # Their tokens are refused from now on.
    assert client.get("/api/me", headers=target.headers).status_code == 401
    assert all(
        "example.com" not in record.getMessage().lower() for record in caplog.records
    )


@pytest.mark.parametrize("typed", ["someone@example.com", "", "Target.Person"])
def test_another_address_is_refused_and_nothing_changes(
    client, admin, target, engine, set_email, typed
):
    set_email(target.id, "Target.Person@Example.com")

    response = delete(client, admin, target.id, typed)

    assert response.status_code == 422
    assert response.json() == {
        "detail": "The address does not match",
        "code": "email_mismatch",
    }
    assert user_exists(engine, target.id)
    assert audit(engine) == []


def test_a_missing_address_gets_the_validation_answer(client, admin, target, engine):
    response = client.request(
        "DELETE", f"/api/admin/users/{target.id}", headers=admin.headers
    )

    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "email"]
    assert user_exists(engine, target.id)


def test_the_admin_cannot_delete_themselves_here(client, admin, engine, set_email):
    set_email(admin.id, "admin@example.com")

    response = delete(client, admin, admin.id, "admin@example.com")

    assert response.status_code == 409
    assert response.json()["code"] == "use_account_screen"
    assert user_exists(engine, admin.id)
    assert audit(engine) == []


@pytest.fixture
def billing_client(make_client, billing_on, admin, now):
    client = make_client(**billing_on, admin_user_ids=str(admin.id))
    client.app.state.clock = lambda: now
    return client


def test_the_deletion_stops_stripe_first(
    billing_client, admin, target, engine, set_email, now
):
    set_email(target.id, "target@example.com")
    add_stripe(engine, target.id, now + timedelta(days=30))
    fake = billing_client.app.state.stripe_gateway

    response = delete(billing_client, admin, target.id, "target@example.com")

    assert response.status_code == 204, response.text
    assert fake.called("cancel_all") == [("cus_1",)]
    assert fake.called("cancel") == [("sub_1",)]
    assert not user_exists(engine, target.id)


def test_stripe_unreachable_refuses_the_deletion_and_nothing_changes(
    billing_client, admin, target, engine, set_email, now
):
    set_email(target.id, "target@example.com")
    add_stripe(engine, target.id, now + timedelta(days=30))
    billing_client.app.state.stripe_gateway.failures["cancel_all"] = (
        GatewayUnavailable()
    )

    response = delete(billing_client, admin, target.id, "target@example.com")

    assert response.status_code == 502
    assert response.json()["code"] == "billing_unavailable"
    assert user_exists(engine, target.id)
    assert audit(engine) == []


def test_with_no_gateway_a_subscription_still_billing_refuses_the_deletion(
    client, admin, target, engine, set_email, now
):
    set_email(target.id, "target@example.com")
    add_stripe(engine, target.id, now + timedelta(days=30), customer=False)

    response = delete(client, admin, target.id, "target@example.com")

    assert response.status_code == 409
    assert response.json()["code"] == "billing_unavailable"
    assert user_exists(engine, target.id)


def test_a_manual_grant_alone_does_not_hold_the_deletion(
    client, admin, target, engine, set_email
):
    set_email(target.id, "target@example.com")
    premium(client, admin, target.id)

    response = delete(client, admin, target.id, "target@example.com")

    assert response.status_code == 204, response.text
