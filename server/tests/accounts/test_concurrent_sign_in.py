"""Two first sign-ins of one Google account at once end with one user."""

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
