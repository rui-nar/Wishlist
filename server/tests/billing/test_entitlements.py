"""Recording purchases and reading premium from them (premium plan D1, D2, D3, D13)."""

import logging
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.accounts.models import User
from app.billing.entitlements import (
    GRACE,
    Applied,
    EntitlementFacts,
    apply,
    is_premium,
    premium_condition,
    record_consent,
    summary,
    warn_if_lapsed,
)
from app.billing.models import Entitlement

NOW = datetime(2026, 11, 10, 12, tzinfo=UTC)
LATER = NOW + timedelta(seconds=1)
IN_A_MONTH = NOW + timedelta(days=30)
LOGGER = "app.billing.entitlements"


def facts(user_id, **overrides) -> EntitlementFacts:
    values = {
        "source": "stripe",
        "external_id": "sub_1",
        "user_id": user_id,
        "status": "active",
        "period_end": IN_A_MONTH,
        "cancel_at_period_end": False,
        "started_at": NOW - timedelta(days=30),
    }
    return EntitlementFacts(**(values | overrides))


@pytest.fixture
def user(make_account):
    return make_account().id


@pytest.fixture
def record(engine):
    def record(fact: EntitlementFacts, read_at: datetime = NOW) -> Applied:
        with Session(engine) as db, db.begin():
            return apply(db, fact, read_at)

    return record


@pytest.fixture
def rows(engine):
    def rows() -> list[Entitlement]:
        with Session(engine) as db:
            return list(db.scalars(select(Entitlement)))

    return rows


# Recording.


def test_apply_inserts_a_row(user, record, rows):
    assert record(facts(user)) is Applied.RECORDED

    row = rows()[0]
    assert len(rows()) == 1
    assert (row.user_id, row.source, row.external_id) == (user, "stripe", "sub_1")
    assert row.status == "active"
    assert row.period_end == IN_A_MONTH
    assert row.cancel_at_period_end is False
    assert row.started_at == NOW - timedelta(days=30)
    assert row.read_at == NOW
    assert row.terms_accepted_at is None
    assert row.terms_version is None


def test_apply_updates_the_row_of_that_purchase(user, record, rows):
    record(facts(user))
    first = rows()[0]

    renewal = IN_A_MONTH + timedelta(days=365)
    record(
        facts(user, status="past_due", period_end=renewal, cancel_at_period_end=True),
        LATER,
    )

    assert len(rows()) == 1
    row = rows()[0]
    assert row.id == first.id
    assert row.created_at == first.created_at
    assert row.status == "past_due"
    assert row.period_end == renewal
    assert row.cancel_at_period_end is True
    assert row.read_at == LATER


def test_apply_is_idempotent(user, record, rows):
    record(facts(user))
    first = rows()[0]

    record(facts(user))

    assert len(rows()) == 1
    row = rows()[0]
    assert (row.id, row.status, row.period_end, row.read_at) == (
        first.id,
        first.status,
        first.period_end,
        first.read_at,
    )


def test_an_older_read_changes_nothing(user, record, rows):
    record(facts(user, status="active"), LATER)
    before = rows()[0]

    assert record(facts(user, status="ended", period_end=NOW), NOW) is Applied.RECORDED

    row = rows()[0]
    assert (row.status, row.period_end, row.read_at, row.updated_at) == (
        "active",
        IN_A_MONTH,
        LATER,
        before.updated_at,
    )


def test_a_read_of_the_same_moment_applies(user, record, rows):
    record(facts(user, status="incomplete"), NOW)

    record(facts(user, status="active"), NOW)

    assert rows()[0].status == "active"


def test_a_purchase_is_its_source_and_id(user, record, rows):
    record(facts(user))
    record(facts(user, external_id="sub_2"))
    record(facts(user, source="apple"))

    assert len(rows()) == 3


def test_the_user_gone_is_reported_and_nothing_written(record, rows):
    assert record(facts(uuid.uuid4())) is Applied.USER_GONE
    assert rows() == []


def test_apply_locks_the_user_before_it_writes(engine, user):
    statements: list[str] = []

    def collect(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", collect)
    try:
        with Session(engine) as db, db.begin():
            apply(db, facts(user), NOW)
    finally:
        event.remove(engine, "before_cursor_execute", collect)

    assert "FOR KEY SHARE" in statements[0]
    assert "FROM users" in statements[0]
    assert "INSERT INTO entitlements" in statements[1]


@pytest.mark.parametrize(
    "values", [{"source": "paypal"}, {"status": "trialing"}], ids=["source", "status"]
)
def test_the_table_refuses_an_unknown_word(engine, user, values):
    with pytest.raises(IntegrityError), Session(engine) as db, db.begin():
        apply(db, facts(user, **values), NOW)


# Reading premium.


@pytest.mark.parametrize("status", ["active", "past_due"])
@pytest.mark.parametrize(
    "period_end",
    [
        IN_A_MONTH,
        NOW,
        NOW - timedelta(days=1),
        NOW - GRACE + timedelta(seconds=1),
    ],
    ids=["in period", "at its end", "in the grace", "last second of the grace"],
)
def test_premium_in_period_and_through_the_grace(
    engine, user, record, status, period_end
):
    record(facts(user, status=status, period_end=period_end))

    with Session(engine) as db:
        assert is_premium(db, user, NOW) is True


@pytest.mark.parametrize("status", ["active", "past_due"])
@pytest.mark.parametrize(
    "period_end",
    [NOW - GRACE, NOW - GRACE - timedelta(seconds=1), None],
    ids=["grace just over", "after the grace", "no period end"],
)
def test_not_premium_after_the_grace(engine, user, record, status, period_end):
    record(facts(user, status=status, period_end=period_end))

    with Session(engine) as db:
        assert is_premium(db, user, NOW) is False


@pytest.mark.parametrize("status", ["incomplete", "ended"])
def test_not_premium_for_a_status_that_grants_nothing(engine, user, record, status):
    record(facts(user, status=status))

    with Session(engine) as db:
        assert is_premium(db, user, NOW) is False


@pytest.mark.parametrize("source", ["stripe", "apple", "google"])
def test_premium_from_a_row_of_each_source(engine, user, record, source):
    record(facts(user, source=source, external_id="purchase"))

    with Session(engine) as db:
        assert is_premium(db, user, NOW) is True
        assert summary(db, user, NOW).source == source


def test_a_person_without_a_row_is_not_premium(engine, user):
    with Session(engine) as db:
        assert is_premium(db, user, NOW) is False


def test_one_row_in_force_is_enough(engine, user, record):
    record(facts(user, status="ended"))
    record(facts(user, external_id="sub_2"))

    with Session(engine) as db:
        assert is_premium(db, user, NOW) is True


def test_someone_elses_purchase_grants_nothing(engine, make_account, record):
    buyer, other = make_account().id, make_account().id
    record(facts(buyer))

    with Session(engine) as db:
        assert is_premium(db, other, NOW) is False


def test_the_condition_applies_to_a_column_of_the_enclosing_query(
    engine, make_account, record
):
    premium, free = make_account().id, make_account().id
    record(facts(premium))

    with Session(engine) as db:
        found = db.scalars(
            select(User.id).where(
                User.id.in_([premium, free]), premium_condition(User.id, NOW)
            )
        )
        assert list(found) == [premium]


# The summary.


def test_the_summary_of_a_free_person(engine, user):
    with Session(engine) as db:
        plan = summary(db, user, NOW)

    assert plan.plan == "free"
    assert (plan.source, plan.status, plan.renews_at, plan.ends_at) == (
        None,
        None,
        None,
        None,
    )


def test_the_summary_of_a_lapsed_row_is_free(engine, user, record):
    record(facts(user, period_end=NOW - GRACE))

    with Session(engine) as db:
        assert summary(db, user, NOW).plan == "free"


@pytest.mark.parametrize("status", ["active", "past_due"])
def test_the_summary_of_a_renewing_purchase(engine, user, record, status):
    record(facts(user, status=status))

    with Session(engine) as db:
        plan = summary(db, user, NOW)

    assert plan.plan == "premium"
    assert (plan.source, plan.status) == ("stripe", status)
    assert (plan.renews_at, plan.ends_at) == (IN_A_MONTH, None)


@pytest.mark.parametrize("status", ["active", "past_due"])
def test_the_summary_of_a_canceled_purchase(engine, user, record, status):
    record(facts(user, status=status, cancel_at_period_end=True))

    with Session(engine) as db:
        plan = summary(db, user, NOW)

    assert (plan.plan, plan.status) == ("premium", "canceling")
    assert (plan.renews_at, plan.ends_at) == (None, IN_A_MONTH)


def test_the_summary_shows_the_latest_period_end(engine, user, record):
    latest = IN_A_MONTH + timedelta(days=30)
    record(facts(user, external_id="sub_1", period_end=IN_A_MONTH))
    record(facts(user, source="apple", external_id="tx_1", period_end=latest))
    record(facts(user, source="google", external_id="tk_1", period_end=NOW))

    with Session(engine) as db:
        plan = summary(db, user, NOW)

    assert (plan.source, plan.renews_at) == ("apple", latest)


def test_the_summary_warns_of_a_lapse(engine, user, record, caplog):
    record(facts(user, period_end=NOW - GRACE))

    with caplog.at_level(logging.WARNING, logger=LOGGER), Session(engine) as db:
        summary(db, user, NOW)

    assert "entitlement past its grace" in caplog.text


# The lapse.


@pytest.mark.parametrize("status", ["active", "past_due"])
def test_a_lapsed_row_logs_one_warning_with_no_personal_data(
    engine, user, record, rows, caplog, status
):
    record(facts(user, status=status, period_end=NOW - GRACE))
    row = rows()[0]
    with Session(engine) as db:
        email = db.get_one(User, user).email

    with caplog.at_level(logging.DEBUG, logger=LOGGER), Session(engine) as db:
        warn_if_lapsed(db, user, NOW)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    line = caplog.records[0].getMessage()
    assert "entitlement past its grace" in line
    assert str(row.id) in line
    assert "stripe" in line
    assert email not in line
    assert "sub_1" not in line
    assert str(user) not in line


def test_each_lapsed_row_is_logged_even_beside_one_in_force(
    engine, user, record, caplog
):
    record(facts(user, period_end=NOW - GRACE))
    record(facts(user, external_id="sub_2"))

    with caplog.at_level(logging.WARNING, logger=LOGGER), Session(engine) as db:
        warn_if_lapsed(db, user, NOW)

    assert len(caplog.records) == 1


@pytest.mark.parametrize(
    "overrides",
    [
        {"period_end": IN_A_MONTH},
        {"period_end": NOW - GRACE + timedelta(seconds=1)},
        {"status": "ended", "period_end": NOW - GRACE},
        {"status": "incomplete", "period_end": NOW - GRACE},
    ],
    ids=["in period", "in the grace", "ended", "incomplete"],
)
def test_no_warning_for_a_row_not_lapsed(engine, user, record, caplog, overrides):
    record(facts(user, **overrides))

    with caplog.at_level(logging.WARNING, logger=LOGGER), Session(engine) as db:
        warn_if_lapsed(db, user, NOW)

    assert caplog.records == []


@pytest.mark.parametrize("status", ["active", "past_due"])
def test_a_granting_row_without_a_period_end_logs_its_own_warning(
    engine, user, record, rows, caplog, status
):
    """Review R3-1: not the lapse's wording, whose recovery does not apply."""
    record(facts(user, status=status, period_end=None))
    row = rows()[0]

    with caplog.at_level(logging.DEBUG, logger=LOGGER), Session(engine) as db:
        warn_if_lapsed(db, user, NOW)

    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert caplog.records[0].getMessage() == (
        f"entitlement granting status without a period end: id={row.id} source=stripe"
    )


def test_no_warning_for_another_persons_row(engine, make_account, record, caplog):
    lapsed, other = make_account().id, make_account().id
    record(facts(lapsed, period_end=NOW - GRACE))

    with caplog.at_level(logging.WARNING, logger=LOGGER), Session(engine) as db:
        warn_if_lapsed(db, other, NOW)

    assert caplog.records == []


# The consent.


def consent(engine, accepted_at=NOW, version="v1", external_id="sub_1") -> None:
    with Session(engine) as db, db.begin():
        record_consent(db, "stripe", external_id, accepted_at, version)


def test_the_consent_is_recorded(engine, user, record, rows):
    record(facts(user))

    consent(engine)

    assert (rows()[0].terms_accepted_at, rows()[0].terms_version) == (NOW, "v1")


def test_the_consent_is_recorded_whatever_the_guard_says(engine, user, record, rows):
    record(facts(user), LATER)

    # The older read loses; its consent does not.
    with Session(engine) as db, db.begin():
        apply(db, facts(user, status="ended"), NOW)
        record_consent(db, "stripe", "sub_1", NOW, "v1")

    row = rows()[0]
    assert (row.status, row.read_at) == ("active", LATER)
    assert (row.terms_accepted_at, row.terms_version) == (NOW, "v1")


def test_a_later_apply_keeps_the_consent(engine, user, record, rows):
    record(facts(user))
    consent(engine)

    record(facts(user, status="ended"), LATER)

    assert (rows()[0].status, rows()[0].terms_version) == ("ended", "v1")


def test_the_first_consent_stands(engine, user, record, rows):
    record(facts(user))
    consent(engine)

    consent(engine, accepted_at=LATER, version="v2")

    assert (rows()[0].terms_accepted_at, rows()[0].terms_version) == (NOW, "v1")


def test_the_consent_of_an_unknown_purchase_writes_nothing(engine, user, record, rows):
    record(facts(user))

    consent(engine, external_id="sub_other")

    assert rows()[0].terms_accepted_at is None
