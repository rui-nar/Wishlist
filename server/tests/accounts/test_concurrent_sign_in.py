"""Two first sign-ins of one Google account at once end with one user; a
sign-in at the same moment as its account's deletion ends as one of the
serial orders, never a 500 (reserving review R6-2)."""

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import text

TIMEOUT_SECONDS = 10


def count(engine, table: str) -> int:
    with engine.connect() as connection:
        return connection.scalar(text(f"SELECT count(*) FROM {table}"))


def test_two_simultaneous_first_sign_ins_make_one_user(client, google, engine):
    tokens = [google.issue("sub-1"), google.issue("sub-1")]
    # Both requests are held until both are past verification, so they look
    # the account up at the same moment.
    both_verifying = threading.Barrier(2, timeout=TIMEOUT_SECONDS)
    google.before_verify = lambda token: both_verifying.wait()

    def sign_in(token: str):
        return client.post("/api/auth/google", json={"id_token": token})

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(sign_in, tokens))

    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json()["user"]["id"] == responses[1].json()["user"]["id"]
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1
    assert count(engine, "sessions") == 2


def test_the_sign_in_that_loses_the_race_reuses_the_winners_user(
    client, google, engine
):
    # Deterministic: the winner's rows are inserted here and held uncommitted,
    # the sign-in finds no account, inserts its own and waits on the unique
    # (provider, subject) index; the winner commits; the sign-in must then
    # fall back to the winner's user.
    winner_id = uuid.uuid4()
    with engine.connect() as winner:
        winner.execute(
            text(
                "INSERT INTO users (id, email, display_name)"
                " VALUES (:id, 'w@example.com', 'Winner')"
            ),
            {"id": winner_id},
        )
        winner.execute(
            text(
                "INSERT INTO user_identities (id, user_id, provider, subject)"
                " VALUES (:id, :user_id, 'google', 'sub-1')"
            ),
            {"id": uuid.uuid4(), "user_id": winner_id},
        )

        with ThreadPoolExecutor(max_workers=1) as pool:
            loser = pool.submit(
                client.post,
                "/api/auth/google",
                json={"id_token": google.issue("sub-1", "l@example.com", "Loser")},
            )
            wait_until_blocked_on_a_lock(engine)
            winner.commit()
            response = loser.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 200
    assert response.json()["user"] == {
        "id": str(winner_id),
        "email": "l@example.com",
        "display_name": "Loser",
    }
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1


def test_a_sign_in_during_its_accounts_deletion_makes_a_new_account(
    client, google, engine, sign_in
):
    # Deterministic: the deletion is held uncommitted, locking the user as
    # `DELETE /api/me` does; the sign-in finds the account, waits on it, then
    # finds it gone and makes a new one, as a sign-in a moment later would.
    old_id = sign_in("sub-1")["user"]["id"]
    with engine.connect() as deleting:
        deleting.execute(
            text("SELECT id FROM users WHERE id = :id FOR UPDATE"), {"id": old_id}
        )
        deleting.execute(text("DELETE FROM users WHERE id = :id"), {"id": old_id})
        with ThreadPoolExecutor(max_workers=1) as pool:
            signing_in = pool.submit(
                client.post,
                "/api/auth/google",
                json={"id_token": google.issue("sub-1")},
            )
            wait_until_blocked_on_a_lock(engine)
            deleting.commit()
            response = signing_in.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 200, response.text
    signed_in = response.json()
    assert signed_in["user"]["id"] != old_id
    assert count(engine, "users") == 1
    assert count(engine, "user_identities") == 1
    me = client.get(
        "/api/me", headers={"Authorization": f"Bearer {signed_in['token']}"}
    )
    assert me.json() == signed_in["user"] | {"is_admin": False}


def test_a_sign_in_racing_its_accounts_deletion(client, google, engine, sign_in):
    # Released together, many times over: signed in first, and the account
    # then deleted with its new session, or deleted first and a new account
    # made.
    for _ in range(20):
        token = sign_in("sub-1")["token"]
        start = threading.Barrier(2, timeout=TIMEOUT_SECONDS)

        def delete_account(token=token, start=start):
            start.wait()
            return client.delete(
                "/api/me", headers={"Authorization": f"Bearer {token}"}
            )

        def sign_in_again(start=start):
            start.wait()
            return client.post(
                "/api/auth/google", json={"id_token": google.issue("sub-1")}
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            deleting = pool.submit(delete_account)
            signing_in = pool.submit(sign_in_again)
            deleted = deleting.result(timeout=TIMEOUT_SECONDS)
            signed_in = signing_in.result(timeout=TIMEOUT_SECONDS)

        assert deleted.status_code == 204, deleted.text
        assert signed_in.status_code == 200, signed_in.text
        new_token = signed_in.json()["token"]
        me = client.get("/api/me", headers={"Authorization": f"Bearer {new_token}"})
        if count(engine, "users") == 0:
            assert me.status_code == 401
        else:
            assert me.json() == signed_in.json()["user"] | {"is_admin": False}
            client.delete("/api/me", headers={"Authorization": f"Bearer {new_token}"})
        assert count(engine, "users") == 0
        assert count(engine, "sessions") == 0


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
    raise AssertionError("the sign-in never waited on the winner's insert")
