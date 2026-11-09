"""Requests at the same moment as their user's account deletion (reserving
plan D7, D10, envelope Concurrency; review R8-1, R6-2): each runs fully
before the deletion, which then releases what it did, or answers 401 as a
signed-out token does. Never a 500, never a deadlock, never a row left
naming the deleted user.

The deletion is held uncommitted in a transaction of the test, taking its
locks as `DELETE /api/me` takes them: the user `FOR UPDATE`, then their
occasions.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial

import pytest
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text

ROUNDS = 20
FUTURE = (date.today() + timedelta(days=60)).isoformat()
NOT_SIGNED_IN = (401, {"detail": "Not signed in"})


@pytest.fixture
def owner(make_account):
    return make_account("Olga")


@pytest.fixture
def occasion(client, owner):
    """An occasion of Olga's list, with a gift and a link: (its id, its
    token, the gift's id)."""
    list_id = client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=owner.headers,
    ).json()["id"]
    gift = client.post(
        f"/api/lists/{list_id}/gifts", json={"title": "Bike"}, headers=owner.headers
    ).json()["id"]
    occasion_id = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": FUTURE},
        headers=owner.headers,
    ).json()["id"]
    token = client.post(
        f"/api/occasions/{occasion_id}/link", headers=owner.headers
    ).json()["join_token"]
    return occasion_id, token, gift


def join(client, account, occasion):
    _, token, _ = occasion
    return client.post("/api/join", json={"token": token}, headers=account.headers)


def reserve(client, account, occasion):
    occasion_id, _, gift = occasion
    return client.post(
        f"/api/occasions/{occasion_id}/gifts/{gift}/reservation",
        headers=account.headers,
    )


def pledge(client, account, occasion):
    occasion_id, _, gift = occasion
    return client.put(
        f"/api/occasions/{occasion_id}/gifts/{gift}/pledge",
        json={"amount": None},
        headers=account.headers,
    )


def remove(client, owner, account, occasion):
    occasion_id, _, _ = occasion
    return client.delete(
        f"/api/occasions/{occasion_id}/members/{account.id}", headers=owner.headers
    )


def delete_account(client, account):
    return client.delete("/api/me", headers=account.headers)


def lock_the_user_to_delete(connection, user):
    connection.execute(
        text("SELECT id FROM users WHERE id = :user FOR UPDATE"), {"user": user}
    )


def lock_their_occasions_and_delete(connection, user):
    """The rest of the deletion, as `delete_me` runs it once the user is
    locked: their occasions `FOR UPDATE`, then the user deleted."""
    values = {"user": user}
    connection.execute(
        text(
            "SELECT occasion_id FROM occasion_members WHERE user_id = :user"
            " ORDER BY occasion_id FOR UPDATE"
        ),
        values,
    )
    connection.execute(text("DELETE FROM users WHERE id = :user"), values)


def assert_nothing_names(rows, user):
    assert rows("claim_participants", "user_id", user) == 0
    assert rows("occasion_members", "user_id", user) == 0
    assert rows("occasion_removals", "user_id", user) == 0
    assert rows("sessions", "user_id", user) == 0


@pytest.mark.parametrize("touched", [False, True], ids=["recent", "touch due"])
def test_a_request_whose_session_was_found_before_the_deletion_is_not_signed_in(
    client, make_account, engine, rows, touched
):
    # R8-1: the session is found while the deletion is still uncommitted; the
    # request then waits on the user, and finds them gone. With "touch due",
    # its use is older than the touch interval, so the request would also
    # write the deleted session.
    ana = make_account("Ana")
    if touched:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE sessions SET last_used_at = now() - interval '2 hours'"
                    " WHERE user_id = :user"
                ),
                {"user": ana.id},
            )
    with engine.connect() as deleting:
        lock_the_user_to_delete(deleting, ana.id)
        lock_their_occasions_and_delete(deleting, ana.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            asking = pool.submit(client.get, "/api/me", headers=ana.headers)
            wait_until_blocked_on_a_lock(engine)
            deleting.commit()
            response = asking.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == NOT_SIGNED_IN
    assert rows("users", "id", ana.id) == 0


WRITES = pytest.mark.parametrize(
    "write", [reserve, pledge, join], ids=["reserve", "pledge", "join"]
)


@WRITES
def test_a_write_during_the_deletion_waits_then_is_not_signed_in(
    client, make_account, occasion, engine, rows, write
):
    # R6-2: the join is to an occasion they were not in when the deletion
    # locked theirs; the reservation and pledge in one they were in.
    ana = make_account("Ana")
    if write is not join:
        assert join(client, ana, occasion).status_code == 200
    with engine.connect() as deleting:
        lock_the_user_to_delete(deleting, ana.id)
        lock_their_occasions_and_delete(deleting, ana.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            writing = pool.submit(write, client, ana, occasion)
            wait_until_blocked_on_a_lock(engine)
            deleting.commit()
            response = writing.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == NOT_SIGNED_IN
    assert rows("gift_claims") == 0
    assert_nothing_names(rows, ana.id)
    assert_claims_consistent(engine)


def test_the_deletion_waits_for_a_join_in_flight_then_removes_it(
    client, make_account, occasion, engine, rows
):
    # The join holds its locks as the endpoint takes them: the user
    # `FOR KEY SHARE` from its dependency, then the occasion; the deletion
    # waits on the user, then deletes the membership with them.
    ana = make_account("Ana")
    values = {"occasion": occasion[0], "user": ana.id}
    with engine.connect() as joining:
        joining.execute(
            text("SELECT id FROM users WHERE id = :user FOR KEY SHARE"), values
        )
        joining.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"), values
        )
        joining.execute(
            text(
                "INSERT INTO occasion_members (occasion_id, user_id)"
                " VALUES (:occasion, :user)"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(delete_account, client, ana)
            wait_until_blocked_on_a_lock(engine)
            joining.commit()
            deleted = deleting.result(timeout=TIMEOUT_SECONDS)

    assert deleted.status_code == 204, deleted.text
    assert_nothing_names(rows, ana.id)


@pytest.mark.parametrize("write", [pledge, join], ids=["pledge", "join"])
def test_a_write_racing_the_writers_account_deletion(
    client, make_account, occasion, engine, rows, write
):
    # The reservation's race is in test_concurrent_release.py.
    for _ in range(ROUNDS):
        ana = make_account("Ana")
        if write is not join:
            assert join(client, ana, occasion).status_code == 200
        written, deleted = together(
            partial(write, client, ana, occasion),
            partial(delete_account, client, ana),
        )

        assert deleted.status_code == 204, deleted.text
        # Written first and released, or not signed in once she is gone.
        assert written.status_code in (200, 401), written.text
        assert rows("gift_claims") == 0
        assert_nothing_names(rows, ana.id)
    assert_claims_consistent(engine)


def test_a_removal_during_the_deletion_waits_then_finds_no_one(
    client, make_account, owner, occasion, engine, rows
):
    # The deletion holds the user and goes on to lock the occasion while the
    # removal waits: the removal locks the user before the occasion, so it
    # holds nothing the deletion needs, and no deadlock.
    ana = make_account("Ana")
    assert join(client, ana, occasion).status_code == 200
    with engine.connect() as deleting:
        lock_the_user_to_delete(deleting, ana.id)
        with ThreadPoolExecutor(max_workers=1) as pool:
            removing = pool.submit(remove, client, owner, ana, occasion)
            wait_until_blocked_on_a_lock(engine)
            lock_their_occasions_and_delete(deleting, ana.id)
            deleting.commit()
            removed = removing.result(timeout=TIMEOUT_SECONDS)

    assert (removed.status_code, removed.json()) == (404, {"detail": "Not found"})
    assert_nothing_names(rows, ana.id)


def test_the_deletion_waits_for_a_removal_in_flight(
    client, make_account, owner, occasion, engine, rows
):
    # The removal holds its locks as the endpoint takes them: the removed
    # user `FOR KEY SHARE`, then the occasion `FOR UPDATE`.
    ana = make_account("Ana")
    assert join(client, ana, occasion).status_code == 200
    values = {"occasion": occasion[0], "user": ana.id}
    with engine.connect() as removing:
        removing.execute(
            text("SELECT id FROM users WHERE id = :user FOR KEY SHARE"), values
        )
        removing.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        removing.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            values,
        )
        removing.execute(
            text(
                "INSERT INTO occasion_removals (occasion_id, user_id)"
                " VALUES (:occasion, :user)"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(delete_account, client, ana)
            wait_until_blocked_on_a_lock(engine)
            removing.commit()
            deleted = deleting.result(timeout=TIMEOUT_SECONDS)

    assert deleted.status_code == 204, deleted.text
    assert_nothing_names(rows, ana.id)


def test_a_removal_racing_the_removed_persons_account_deletion(
    client, make_account, owner, occasion, engine, rows
):
    for _ in range(ROUNDS):
        ana = make_account("Ana")
        assert join(client, ana, occasion).status_code == 200
        assert reserve(client, ana, occasion).status_code == 200
        removed, deleted = together(
            partial(remove, client, owner, ana, occasion),
            partial(delete_account, client, ana),
        )

        assert deleted.status_code == 204, deleted.text
        # Removed first, or no one to remove once she is gone.
        assert removed.status_code in (204, 404), removed.text
        assert rows("gift_claims") == 0
        assert_nothing_names(rows, ana.id)
    assert_claims_consistent(engine)


def test_two_deletions_of_one_account_at_once(client, make_account, rows):
    # Each takes the user `FOR UPDATE` in its dependency, never upgrading a
    # share lock, so the second waits, then finds no one.
    for _ in range(ROUNDS):
        ana = make_account("Ana")
        responses = together(
            partial(delete_account, client, ana),
            partial(delete_account, client, ana),
        )

        assert sorted(response.status_code for response in responses) == [204, 401]
        assert rows("users", "id", ana.id) == 0
