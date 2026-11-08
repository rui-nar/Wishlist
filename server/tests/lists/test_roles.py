"""The surprise rule, role by role (lists plan D10).

One scenario: a "for me" list and a "for someone else" list, each with its
owner and a gift, and a stranger who owns neither. Every endpoint is called by
every actor on every list, and checked for:

- access: what each relation to the list gets (`expected`);
- content: no response carries a `join_token` key or an id the caller may not
  see (`Scenario.hidden_from`);
- probing: whatever a non-owner gets for a real id, they get for a random one;
- no effect: a refused call leaves both lists as their owners see them.

Later plans extend the scenario rather than writing their own: U2 adds an
occasion and an invitee per list (new actors, new relations in `relation`, the
occasion ids in `Scenario.lists`) and its endpoints to `ENDPOINTS`; a plan that
adds invitee activity adds it to the scenario and asserts that the recipient
sees none of it. A new route under `GUARDED_PREFIXES` without a row in
`ENDPOINTS` or `COVERED_ELSEWHERE` fails `test_every_route_is_in_the_matrix`.
"""

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

SIGNED_OUT = "signed out"
# The actors, each a user except SIGNED_OUT.
ME_OWNER = "owner of the list for me"
OTHER_OWNER = "owner of the list for someone else"
STRANGER = "stranger"
ACTORS = [ME_OWNER, OTHER_OWNER, STRANGER, SIGNED_OUT]

FOR_ME = "for me"
FOR_SOMEONE = "for someone else"
LISTS = {
    FOR_ME: (ME_OWNER, {"title": "My birthday", "recipient_kind": "self"}),
    FOR_SOMEONE: (
        OTHER_OWNER,
        {"title": "Leo's birthday", "recipient_kind": "other", "recipient_name": "Leo"},
    ),
}

# An actor's relation to a list decides what they get.
OWNER = "owner"
NOT_OWNER = "not an owner"


@dataclass
class Scenario:
    accounts: dict[str, Any]
    # Per list: the ids of what it holds, by name ("list_id", "gift_id").
    lists: dict[str, dict[str, str]]

    def headers(self, actor: str) -> dict[str, str]:
        return {} if actor == SIGNED_OUT else self.accounts[actor].headers

    def relation(self, actor: str, list_key: str) -> str:
        if actor == SIGNED_OUT:
            return SIGNED_OUT
        return OWNER if LISTS[list_key][0] == actor else NOT_OWNER

    def hidden_from(self, actor: str) -> set[str]:
        """Every id of every list the actor does not own."""
        return {
            value
            for list_key, ids in self.lists.items()
            if self.relation(actor, list_key) != OWNER
            for value in ids.values()
        }


@pytest.fixture
def scenario(client, make_account) -> Scenario:
    accounts = {actor: make_account(actor) for actor in ACTORS if actor != SIGNED_OUT}
    lists = {}
    for list_key, (owner, body) in LISTS.items():
        headers = accounts[owner].headers
        list_id = client.post("/api/lists", json=body, headers=headers).json()["id"]
        gift = client.post(
            f"/api/lists/{list_id}/gifts",
            json={
                "title": "Headphones",
                "links": ["https://shop.example.com/h"],
                "price_amount": 149,
                "price_currency": "EUR",
            },
            headers=headers,
        ).json()
        lists[list_key] = {"list_id": list_id, "gift_id": gift["id"]}
    return Scenario(accounts=accounts, lists=lists)


@dataclass(frozen=True)
class Endpoint:
    method: str
    # Formatted with the ids of the list it is called on.
    path: str
    body: dict[str, Any] | None
    # The status for an owner; everyone else is refused (`expected`).
    success: int

    def __str__(self) -> str:
        return f"{self.method} {self.path}"


# Every endpoint that names an object of a list.
ENDPOINTS = [
    Endpoint("GET", "/api/lists/{list_id}", None, 200),
    Endpoint("PATCH", "/api/lists/{list_id}", {"title": "Renamed"}, 200),
    Endpoint("DELETE", "/api/lists/{list_id}", None, 204),
    Endpoint("POST", "/api/lists/{list_id}/gifts", {"title": "Scarf"}, 201),
    Endpoint("PATCH", "/api/gifts/{gift_id}", {"title": "Renamed"}, 200),
    Endpoint("DELETE", "/api/gifts/{gift_id}", None, 204),
]

# The API paths whose routes must all appear in this module. U2 adds
# /api/occasions, /api/join and /api/shared.
GUARDED_PREFIXES = ("/api/lists", "/api/gifts")

# Routes under those prefixes that name no object of a list, so they cannot
# take the scenario's ids; each is covered by its own test below.
COVERED_ELSEWHERE = {
    ("GET", "/api/lists"),  # test_my_lists_by_role
    ("POST", "/api/lists"),  # test_creating_a_list_by_role
}


def expected(endpoint: Endpoint, relation: str) -> int:
    return {OWNER: endpoint.success, NOT_OWNER: 404, SIGNED_OUT: 401}[relation]


def call(client, scenario: Scenario, actor: str, endpoint: Endpoint, ids):
    return client.request(
        endpoint.method,
        endpoint.path.format(**ids),
        json=endpoint.body,
        headers=scenario.headers(actor),
    )


def walk(value: Any) -> Iterator[tuple[str | None, Any]]:
    """Every (key, value) pair of a JSON document, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from walk(item)


def assert_reveals_nothing(body: Any, hidden: set[str]) -> None:
    for key, value in walk(body):
        assert key != "join_token"
        assert key not in hidden
        assert not (isinstance(value, str) and value in hidden), value


def owners_view(client, scenario: Scenario) -> dict[str, Any]:
    """Both lists as their owners see them."""
    return {
        list_key: client.get(
            f"/api/lists/{ids['list_id']}", headers=scenario.headers(LISTS[list_key][0])
        ).json()
        for list_key, ids in scenario.lists.items()
    }


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=str)
def test_endpoint_by_role(client, scenario, endpoint, list_key, actor):
    relation = scenario.relation(actor, list_key)
    before = owners_view(client, scenario)

    response = call(client, scenario, actor, endpoint, scenario.lists[list_key])

    assert response.status_code == expected(endpoint, relation), response.text
    if response.content:
        assert_reveals_nothing(response.json(), scenario.hidden_from(actor))
    if relation == OWNER:
        return
    # Refused: nothing changed, and the answer is the one for ids that exist
    # nowhere, so a real id cannot be told from a random one.
    assert owners_view(client, scenario) == before
    random_ids = {name: str(uuid.uuid4()) for name in scenario.lists[list_key]}
    probe = call(client, scenario, actor, endpoint, random_ids)
    assert (probe.status_code, probe.json()) == (response.status_code, response.json())


@pytest.mark.parametrize("actor", ACTORS)
def test_my_lists_by_role(client, scenario, actor):
    response = client.get("/api/lists", headers=scenario.headers(actor))

    if actor == SIGNED_OUT:
        assert response.status_code == 401
        return
    assert response.status_code == 200
    owned = {
        ids["list_id"]
        for list_key, ids in scenario.lists.items()
        if scenario.relation(actor, list_key) == OWNER
    }
    assert {found["id"] for found in response.json()} == owned
    assert_reveals_nothing(response.json(), scenario.hidden_from(actor))


@pytest.mark.parametrize("actor", ACTORS)
def test_creating_a_list_by_role(client, scenario, actor):
    before = owners_view(client, scenario)

    response = client.post(
        "/api/lists",
        json={"title": "New", "recipient_kind": "self"},
        headers=scenario.headers(actor),
    )

    assert response.status_code == (401 if actor == SIGNED_OUT else 201)
    assert_reveals_nothing(response.json(), scenario.hidden_from(actor))
    assert owners_view(client, scenario) == before


def test_every_route_is_in_the_matrix(client):
    """No route under GUARDED_PREFIXES escapes this module, and no row names a
    route that no longer exists (guard for review R4-2).

    The routes are read from the OpenAPI document: FastAPI keeps included
    routers nested in `app.routes` behind private classes. An API route is
    never registered with `include_in_schema=False`, which would hide it here.
    """
    paths = client.app.openapi()["paths"]
    routes = {
        (method.upper(), path)
        for path, operations in paths.items()
        if path.startswith(GUARDED_PREFIXES)
        for method in operations
    }
    in_matrix = {(endpoint.method, endpoint.path) for endpoint in ENDPOINTS}

    # One assertion, so a failure shows every gap at once.
    assert {
        "routes in neither ENDPOINTS nor COVERED_ELSEWHERE": (
            routes - in_matrix - COVERED_ELSEWHERE
        ),
        "ENDPOINTS rows that match no route": in_matrix - routes,
        "COVERED_ELSEWHERE rows that match no route": COVERED_ELSEWHERE - routes,
    } == {
        "routes in neither ENDPOINTS nor COVERED_ELSEWHERE": set(),
        "ENDPOINTS rows that match no route": set(),
        "COVERED_ELSEWHERE rows that match no route": set(),
    }
