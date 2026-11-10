"""Hashing passwords (sign-in plan D11)."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

from app.accounts import passwords

TIMEOUT_SECONDS = 10
PASSWORD = "correct horse battery staple"


def test_a_password_verifies_against_its_hash():
    stored = passwords.hash(PASSWORD)

    assert passwords.verify(stored, PASSWORD) is True
    assert PASSWORD not in stored


def test_a_wrong_password_does_not_verify():
    assert passwords.verify(passwords.hash(PASSWORD), "another password") is False


def test_a_corrupted_hash_is_a_failure_not_an_error():
    assert passwords.verify("not-a-hash", PASSWORD) is False


def test_hashes_are_argon2id_at_owasps_minimum():
    assert passwords.hash(PASSWORD).startswith("$argon2id$v=19$m=19456,t=2,p=1$")


def test_two_hashes_of_one_password_differ():
    assert passwords.hash(PASSWORD) != passwords.hash(PASSWORD)


def test_todays_parameters_need_no_rehash():
    assert passwords.needs_rehash(passwords.hash(PASSWORD)) is False


def test_other_parameters_need_a_rehash():
    stored = passwords.hash(PASSWORD).replace("m=19456", "m=65536")

    assert passwords.needs_rehash(stored) is True


def test_the_length_limits_follow_nist():
    assert (passwords.MIN_LENGTH, passwords.MAX_LENGTH) == (10, 128)


class _HoldingHasher:
    """Stands in for argon2's hasher: each call waits until released."""

    def __init__(self) -> None:
        self.release = threading.Event()
        self.started = 0
        self._lock = threading.Lock()

    def _hold(self) -> None:
        with self._lock:
            self.started += 1
        assert self.release.wait(TIMEOUT_SECONDS)

    def hash(self, password: str) -> str:
        self._hold()
        return "hashed"

    def verify(self, stored_hash: str, password: str) -> bool:
        self._hold()
        return True


def _wait_for(condition) -> None:
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def test_at_most_four_hashes_run_at_once(monkeypatch):
    hasher = _HoldingHasher()
    monkeypatch.setattr(passwords, "_hasher", hasher)

    with ThreadPoolExecutor(max_workers=8) as pool:
        running = [
            pool.submit(passwords.hash if i % 2 else _verify, PASSWORD)
            for i in range(8)
        ]
        _wait_for(lambda: hasher.started >= 4)
        # Long enough for a fifth to start, were it let through.
        time.sleep(0.2)
        assert hasher.started == 4
        hasher.release.set()
        for future in running:
            future.result(timeout=TIMEOUT_SECONDS)

    assert hasher.started == 8


def _verify(password: str) -> bool:
    return passwords.verify("stored", password)


def test_the_dummy_verify_runs_a_real_verification(monkeypatch):
    # An address with no account costs the time of one that has one (D10).
    hasher = _HoldingHasher()
    hasher.release.set()
    monkeypatch.setattr(passwords, "_hasher", hasher)

    passwords.dummy_verify(PASSWORD)

    assert hasher.started == 1


def test_the_dummy_verify_accepts_any_password_without_raising():
    assert passwords.dummy_verify(PASSWORD) is None
