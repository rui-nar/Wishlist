"""Shared test setup.

The tests run against a real PostgreSQL (plan D12) named by `DATABASE_URL`,
the same variable the app reads, e.g.
`postgresql+psycopg://wishlist:wishlist@localhost:5432/wishlist_test`.
Point it at a test database, never at a database whose data matters:
`dev.ps1 -Test` and CI set it to theirs. The user needs the CREATEDB privilege
(the official Postgres image's user has it): the migration test runs on a
scratch database it creates and drops.
"""

import os
from collections.abc import Callable, Collection, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.settings import Settings

# Checked before anything imports app.main, whose module-level app would fail
# with a less helpful validation error.
if not os.environ.get("DATABASE_URL"):
    pytest.exit(
        "DATABASE_URL is not set: the tests need a PostgreSQL test database",
        returncode=4,
    )


@pytest.fixture
def database_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture
def make_client(database_url: str, tmp_path) -> Iterator[Callable[..., TestClient]]:
    """Builds a client for an app with test settings, overridable by keyword.

    MEDIA_DIR defaults to a directory under tmp_path, so no test writes into
    the repository.
    """
    from app.main import create_app

    clients: list[TestClient] = []

    def make(**overrides: Any) -> TestClient:
        values: dict[str, Any] = {
            "database_url": database_url,
            "media_dir": tmp_path / "media",
        } | overrides
        client = TestClient(create_app(Settings(**values)))
        client.__enter__()  # runs the lifespan, as uvicorn does
        clients.append(client)
        return client

    yield make
    for client in clients:
        client.__exit__(None, None, None)


class FakeFetcher:
    """Stands in for `app.state.url_fetcher`, a SafeFetcher: answers every
    fetch with `result`, or raises it when it is an exception, and records
    the calls. No endpoint test fetches from the network."""

    def __init__(self) -> None:
        self.result: tuple[bytes, str] | Exception = (b"", "image/png")
        self.calls: list[tuple[str, tuple[str, ...], int]] = []

    def fetch(
        self, url: str, accept: Collection[str], max_bytes: int
    ) -> tuple[bytes, str]:
        self.calls.append((url, tuple(accept), max_bytes))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def url_fetcher(client: TestClient) -> FakeFetcher:
    """The fake fetcher, put in the app of the package's `client` fixture."""
    fake = FakeFetcher()
    client.app.state.url_fetcher = fake
    return fake
