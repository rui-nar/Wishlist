"""Joining at the same moment as a removal, a leave or a deletion (lists plan
envelope, Concurrency): the membership row exists or not, a removal stays
effective, and no answer is a 500.
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


def test_a_removal_racing_a_join_always_keeps_them_out(
    client, ada, bea, occasion, rows
):
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
    # every order the database allows. Whichever goes first, the removal is
    # effective: the join either came before it (and is undone by it) or
    # after it (and is refused).
    for _ in range(20):
        client.delete(
            f"/api/occasions/{occasion_id}/removals/{bea.id}", headers=ada.headers
        )
        assert join(client, bea, token).status_code == 200
        start = threading.Barrier(2, timeout=TIMEOUT_SECONDS)
        with ThreadPoolExecutor(max_workers=2) as pool:
            removing = pool.submit(remove, start)
            joining = pool.submit(rejoin, start)
            removed = removing.result(timeout=TIMEOUT_SECONDS)
            joined = joining.result(timeout=TIMEOUT_SECONDS)

        assert removed.status_code == 204, removed.text
        assert joined.status_code in (200, 404), joined.text
        assert rows("occasion_members") == 0
        assert rows("occasion_removals") == 1


def test_a_join_waiting_on_a_removal_is_a_404(client, bea, occasion, engine, rows):
    # Deterministic: the owner's removal is made here, as the endpoint makes
    # it, and held uncommitted; the join waits on the occasion's lock; once
    # the removal commits, the join must see it and refuse.
    occasion_id, token = occasion
    join(client, bea, token)
    values = {"occasion": occasion_id, "user": bea.id}
    with engine.connect() as removal:
        removal.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        removal.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            values,
        )
        removal.execute(
            text(
                "INSERT INTO occasion_removals (occasion_id, user_id)"
                " VALUES (:occasion, :user)"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(join, client, bea, token)
            wait_until_blocked_on_a_lock(engine)
            removal.commit()
            response = joining.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 404
    assert rows("occasion_members") == 0


def test_a_join_waiting_on_a_leave_ends_as_a_member(
    client, bea, occasion, engine, rows
):
    # Deterministic: the invitee's leaving is made here and held uncommitted;
    # the join finds the row being deleted and waits; once the leave commits,
    # the join must make the membership again rather than fail.
    occasion_id, token = occasion
    join(client, bea, token)
    with engine.connect() as leaving:
        leaving.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            {"occasion": occasion_id, "user": bea.id},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            joining = pool.submit(join, client, bea, token)
            wait_until_blocked_on_a_lock(engine)
            leaving.commit()
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
