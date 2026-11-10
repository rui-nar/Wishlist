"""The limits on the email routes hold across processes (sign-in plan D12)."""

import hashlib
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.accounts import throttle
from app.accounts.throttle import Limit

TIMEOUT_SECONDS = 10
ONE_PER_HOUR = Limit("test_one", 1, timedelta(hours=1))
THREE_PER_HOUR = Limit("test_three", 3, timedelta(hours=1))


@pytest.fixture(autouse=True)
def empty_throttle(engine: Engine) -> Iterator[None]:
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE auth_throttle"))


@pytest.fixture
def factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(engine)


def test_a_limit_allows_its_attempts_then_refuses(factory, clock):
    answers = [
        throttle.allowed(factory, THREE_PER_HOUR, "1.2.3.4", clock()) for _ in range(5)
    ]

    assert answers == [True, True, True, False, False]


def test_a_new_window_starts_over(factory, clock):
    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is True
    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is False

    clock.advance(timedelta(hours=1))

    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is True
    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is False


def test_a_window_does_not_end_early(factory, clock):
    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is True

    clock.advance(timedelta(minutes=59, seconds=59))

    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is False


def test_each_value_and_each_kind_counts_alone(factory, clock):
    other_kind = Limit("test_other", 1, timedelta(hours=1))

    assert throttle.allowed(factory, ONE_PER_HOUR, "a", clock()) is True
    assert throttle.allowed(factory, ONE_PER_HOUR, "b", clock()) is True
    assert throttle.allowed(factory, other_kind, "a", clock()) is True


def test_the_limit_survives_a_rollback_of_the_callers_transaction(factory, clock):
    # A refused request rolls its own transaction back: the count must stay.
    with pytest.raises(RuntimeError), factory.begin() as caller:
        caller.execute(text("SELECT 1"))
        assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is True
        raise RuntimeError

    assert throttle.allowed(factory, ONE_PER_HOUR, "x", clock()) is False


def test_the_limit_holds_across_two_concurrent_callers(factory, clock):
    attempts = 30
    limit = Limit("test_race", attempts, timedelta(hours=1))
    start = threading.Barrier(2, timeout=TIMEOUT_SECONDS)

    def caller() -> list[bool]:
        start.wait()
        return [throttle.allowed(factory, limit, "x", clock()) for _ in range(attempts)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        answers = [pool.submit(caller) for _ in range(2)]
        allowed = sum(sum(a.result(timeout=TIMEOUT_SECONDS)) for a in answers)

    assert allowed == attempts


def test_a_caller_waits_for_the_other_and_counts_after_it(factory, engine, clock):
    # Deterministic: another caller's row is held uncommitted at the limit. The
    # upsert must wait for it and count on top of it.
    limit = Limit("test_held", 2, timedelta(hours=1))
    with engine.connect() as other:
        other.execute(
            text(
                "INSERT INTO auth_throttle (key_hash, window_started_at, count)"
                " VALUES (:key, :now, 2)"
            ),
            {"key": throttle._key(limit, "x"), "now": clock()},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            caller = pool.submit(throttle.allowed, factory, limit, "x", clock())
            _wait_until_blocked_on_a_lock(engine)
            other.commit()

            assert caller.result(timeout=TIMEOUT_SECONDS) is False


def test_neither_address_nor_ip_is_stored(factory, engine, clock):
    value = "ada@example.com|203.0.113.7"

    throttle.allowed(factory, throttle.SIGN_IN_PER_ADDRESS_AND_IP, value, clock())

    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT key_hash, CAST(a AS text) FROM auth_throttle a")
        ).all()
    expected = hashlib.sha256(f"sign_in_address_ip|{value}".encode()).hexdigest()
    assert [row[0] for row in rows] == [expected]
    assert "example.com" not in rows[0][1]
    assert "203.0.113.7" not in rows[0][1]


def test_the_limits_are_those_of_the_plan():
    quarter, hour = timedelta(minutes=15), timedelta(hours=1)

    assert throttle.SIGN_IN_PER_ADDRESS_AND_IP.attempts == 10
    assert throttle.SIGN_IN_PER_ADDRESS_AND_IP.window == quarter
    assert throttle.SIGN_IN_PER_IP.attempts == 100
    assert throttle.SIGN_IN_PER_IP.window == quarter
    assert throttle.START_PER_ADDRESS.attempts == 3
    assert throttle.START_PER_ADDRESS.window == hour
    assert throttle.START_PER_IP.attempts == 20
    assert throttle.START_PER_IP.window == hour
    assert throttle.COMPLETE_PER_IP.attempts == 20
    assert throttle.COMPLETE_PER_IP.window == quarter


def _wait_until_blocked_on_a_lock(engine: Engine) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            waiting = observer.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity"
                    " WHERE datname = current_database() AND wait_event_type = 'Lock'"
                )
            )
            observer.rollback()
            if waiting:
                return
            time.sleep(0.02)
    raise AssertionError("the caller never waited on the other's row")
