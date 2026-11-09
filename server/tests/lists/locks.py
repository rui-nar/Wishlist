"""Helpers for the race tests: requests released together, and a request
known to be waiting on another transaction's lock."""

import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from sqlalchemy import text

TIMEOUT_SECONDS = 10


def together(*calls: Callable[[], Any]) -> list[Any]:
    """Runs the calls in threads released at the same moment by a barrier,
    and returns their results in order. Run many times over, the requests
    meet in every order the database allows."""
    start = threading.Barrier(len(calls), timeout=TIMEOUT_SECONDS)

    def run(call: Callable[[], Any]) -> Any:
        start.wait()
        return call()

    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        futures = [pool.submit(run, call) for call in calls]
        return [future.result(timeout=TIMEOUT_SECONDS) for future in futures]


def wait_until_blocked_on_a_lock(engine) -> None:
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
    raise AssertionError("the request never waited on the other transaction")
