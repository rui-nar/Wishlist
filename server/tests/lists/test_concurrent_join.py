"""Joining at the same moment as a removal or a deletion (lists plan envelope,
Concurrency): the membership row exists or not, and no answer is a 500.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text

TIMEOUT_SECONDS = 10


@pytest.fixture
def ada(make_account):
    return make_account("Ada")


@pytest.fixture
def bea(make_account):
    return make_account("Bea")


@pytest.fixture
def occasion(client, ada):
    """An occasion of Ada's list with a link: (its id, its token)."""
    list_id = client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=ada.headers,
    ).json()["id"]
    occasion_id = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": "2026-12-25"},
        headers=ada.headers,
    ).json()["id"]
    token = client.post(
        f"/api/occasions/{occasion_id}/link", headers=ada.headers
    ).json()["join_token"]
    return occasion_id, token


def join(client, account, token):
    return client.post("/api/join", json={"token": token}, headers=account.headers)


def test_joining_while_being_removed_never_fails(client, ada, bea, occasion, rows):
    occasion_id, token = occasion

    def remove(start: threading.Barrier):
        start.wait()
        return client.delete(
            f"/api/occasions/{occasion_id}/members/{bea.id}", headers=ada.headers
        )

    def rejoin(start: threading.Barrier):
        start.wait()
        return join(client, bea, token)

    # Both requests are released together, many times over, so they meet in
    # every order the database allows.
    for _ in range(20):
        assert join(client, bea, token).status_code == 200
        start = threading.Barrier(2, timeout=TIMEOUT_SECONDS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            removing = pool.submit(remove, start)
            joining = pool.submit(rejoin, start)
            removed = removing.result(timeout=TIMEOUT_SECONDS)
            joined = joining.result(timeout=TIMEOUT_SECONDS)

        assert removed.status_code in (204, 404), removed.text
        assert joined.status_code == 200, joined.text
        assert rows("occasion_members") in (0, 1)


def test_a_join_waiting_on_a_removal_ends_as_a_member(
    client, bea, occasion, engine, rows
):
    # Deterministic: the removal is made here and held uncommitted; the join
    # finds the row being deleted and waits; once the removal commits, the
    # join must make the membership again rather than fail.
    occasion_id, token = occasion
    join(client, bea, token)
    with engine.connect() as removal:
        removal.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            {"occasion": occasion_id, "user": bea.id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(join, client, bea, token)
            wait_until_blocked_on_a_lock(engine)
            removal.commit()
            response = joining.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 200
    assert rows("occasion_members") == 1


def test_a_join_waiting_on_the_occasions_deletion_is_a_404(
    client, bea, occasion, engine, rows
):
    occasion_id, token = occasion
    with engine.connect() as deletion:
        deletion.execute(
            text("DELETE FROM occasions WHERE id = :occasion"),
            {"occasion": occasion_id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(join, client, bea, token)
            wait_until_blocked_on_a_lock(engine)
            deletion.commit()
            response = joining.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 404
    assert rows("occasion_members") == 0


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
    raise AssertionError("the join never waited on the other transaction")
