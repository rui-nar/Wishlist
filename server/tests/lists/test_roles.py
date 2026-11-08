"""The surprise rule, role by role (lists plan D10).

One scenario: a "for me" list and a "for someone else" list, each with its
owner, a gift and two occasions shared by link, an invitee who joined the
first occasion and another who joined the second; someone who joined the
first occasion of both lists and was removed from them; and a stranger who has
nothing to do with either. Every endpoint is called by every actor on every
list, and checked for:

- access: what each relation to the list and its first occasion gets
  (`expected`);
- content: no response carries a `join_token` key or an id or token the
  caller may not see (`Scenario.hidden_from`);
- probing: whatever a refused caller gets for a real id, they get for a random
  one;
- no effect: a refused call leaves both lists as their owners see them.

The routes that name no object of a list (my lists, creating a list, shared
with me, the join endpoints) have their own tests by role, below.

Later plans extend the scenario rather than writing their own: a plan that
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
ME_INVITEE = "invitee of the first occasion of the list for me"
ME_INVITEE_ELSEWHERE = "invitee of the second occasion of the list for me"
OTHER_INVITEE = "invitee of the first occasion of the list for someone else"
OTHER_INVITEE_ELSEWHERE = "invitee of the second occasion of the list for someone else"
REMOVED_INVITEE = "removed from the first occasion of both lists"
STRANGER = "stranger"
ACTORS = [
    ME_OWNER,
    OTHER_OWNER,
    ME_INVITEE,
    ME_INVITEE_ELSEWHERE,
    OTHER_INVITEE,
    OTHER_INVITEE_ELSEWHERE,
    REMOVED_INVITEE,
    STRANGER,
    SIGNED_OUT,
]

FOR_ME = "for me"
FOR_SOMEONE = "for someone else"
LISTS = {
    FOR_ME: (ME_OWNER, {"title": "My birthday", "recipient_kind": "self"}),
    FOR_SOMEONE: (
        OTHER_OWNER,
        {"title": "Leo's birthday", "recipient_kind": "other", "recipient_name": "Leo"},
    ),
}
# Each list's two occasions, by the name of their id, and who joined each.
FIRST = "occasion_id"
SECOND = "other_occasion_id"
INVITEES = {
    FOR_ME: {FIRST: ME_INVITEE, SECOND: ME_INVITEE_ELSEWHERE},
    FOR_SOMEONE: {FIRST: OTHER_INVITEE, SECOND: OTHER_INVITEE_ELSEWHERE},
}

# An actor's relation to a list, and to its first occasion (the one the
# occasion endpoints are called on), decides what they get.
OWNER = "owner"
INVITEE = "invitee of the occasion"
INVITEE_ELSEWHERE = "invitee of another occasion of the list"
REMOVED = "removed from the occasion"
UNRELATED = "unrelated"


@dataclass
class Scenario:
    accounts: dict[str, Any]
    # Per list: the ids of what it holds, by name ("list_id", "gift_id",
    # "occasion_id", "other_occasion_id", "user_id", the invitee of the first
    # occasion, and "removed_id", the person removed from it).
    lists: dict[str, dict[str, str]]
    # Per list: each occasion's join token, by the name of its id.
    tokens: dict[str, dict[str, str]]

    def headers(self, actor: str) -> dict[str, str]:
        return {} if actor == SIGNED_OUT else self.accounts[actor].headers

    def relation(self, actor: str, list_key: str) -> str:
        if actor == SIGNED_OUT:
            return SIGNED_OUT
        if LISTS[list_key][0] == actor:
            return OWNER
        if INVITEES[list_key][FIRST] == actor:
            return INVITEE
        if INVITEES[list_key][SECOND] == actor:
            return INVITEE_ELSEWHERE
        if actor == REMOVED_INVITEE:
            return REMOVED
        return UNRELATED

    def hidden_from(self, actor: str) -> set[str]:
        """Every id and token of the scenario that the actor may not see.

        An owner sees everything of their list, the ids of its invitees and
        of the people removed from it included. An invitee sees their
        occasion and the list's gifts; not the list's id, its other occasion
        or any token. A removed person sees nothing of the list. Nobody sees
        another user's id unless they own a list that user joined.
        """
        everything = {account.id for account in self.accounts.values()}
        visible = set()
        if actor != SIGNED_OUT:
            visible.add(self.accounts[actor].id)
        for list_key, ids in self.lists.items():
            everything |= set(ids.values()) | set(self.tokens[list_key].values())
            relation = self.relation(actor, list_key)
            if relation == OWNER:
                visible |= set(ids.values()) | set(self.tokens[list_key].values())
                visible |= {
                    self.accounts[invitee].id for invitee in INVITEES[list_key].values()
                }
            elif relation == INVITEE:
                visible |= {ids[FIRST], ids["gift_id"]}
            elif relation == INVITEE_ELSEWHERE:
                visible |= {ids[SECOND], ids["gift_id"]}
        return everything - visible

    def joined(self, actor: str) -> set[str]:
        """The occasions the actor is an invitee of."""
        return {
            self.lists[list_key][occasion]
            for list_key, invitees in INVITEES.items()
            for occasion, invitee in invitees.items()
            if invitee == actor
        }


@pytest.fixture
def scenario(client, make_account) -> Scenario:
    accounts = {actor: make_account(actor) for actor in ACTORS if actor != SIGNED_OUT}
    lists = {}
    tokens = {}
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
        ids = {"list_id": list_id, "gift_id": gift["id"]}
        tokens[list_key] = {}
        for occasion, name in ((FIRST, "Birthday 2026"), (SECOND, "Christmas 2026")):
            created = client.post(
                f"/api/lists/{list_id}/occasions",
                json={"name": name, "date": "2026-12-25"},
                headers=headers,
            ).json()
            token = client.post(
                f"/api/occasions/{created['id']}/link", headers=headers
            ).json()["join_token"]
            invitee = accounts[INVITEES[list_key][occasion]]
            joined = client.post(
                "/api/join", json={"token": token}, headers=invitee.headers
            )
            assert joined.status_code == 200, joined.text
            ids[occasion] = created["id"]
            tokens[list_key][occasion] = token
        ids["user_id"] = accounts[INVITEES[list_key][FIRST]].id
        removed = accounts[REMOVED_INVITEE]
        client.post(
            "/api/join",
            json={"token": tokens[list_key][FIRST]},
            headers=removed.headers,
        )
        removal = client.delete(
            f"/api/occasions/{ids[FIRST]}/members/{removed.id}", headers=headers
        )
        assert removal.status_code == 204, removal.text
        ids["removed_id"] = removed.id
        lists[list_key] = ids
    return Scenario(accounts=accounts, lists=lists, tokens=tokens)


@dataclass(frozen=True)
class Endpoint:
    method: str
    # Formatted with the ids of the list it is called on.
    path: str
    body: dict[str, Any] | None
    # The status for an owner, and for the invitee of the occasion in the
    # path; everyone else is refused (`expected`).
    success: int
    invitee: int = 404
    # The route as the API declares it, when `path` names its parameters
    # differently (two routes name a different user `{user_id}`).
    route: str | None = None

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
    Endpoint(
        "POST",
        "/api/lists/{list_id}/occasions",
        {"name": "Easter", "date": "2027-03-28"},
        201,
    ),
    Endpoint("GET", "/api/occasions/{occasion_id}", None, 200, invitee=200),
    Endpoint("PATCH", "/api/occasions/{occasion_id}", {"name": "Renamed"}, 200),
    Endpoint("DELETE", "/api/occasions/{occasion_id}", None, 204),
    Endpoint("POST", "/api/occasions/{occasion_id}/link", None, 200),
    Endpoint("DELETE", "/api/occasions/{occasion_id}/link", None, 204),
    Endpoint("GET", "/api/occasions/{occasion_id}/members", None, 200),
    Endpoint("DELETE", "/api/occasions/{occasion_id}/members/{user_id}", None, 204),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/removals/{removed_id}",
        None,
        204,
        route="/api/occasions/{occasion_id}/removals/{user_id}",
    ),
    # Only an invitee has a membership to leave.
    Endpoint("DELETE", "/api/occasions/{occasion_id}/membership", None, 404, 204),
]

# The API paths whose routes must all appear in this module.
GUARDED_PREFIXES = (
    "/api/lists",
    "/api/gifts",
    "/api/occasions",
    "/api/join",
    "/api/shared",
)

# Routes under those prefixes that name no object of a list, so they cannot
# take the scenario's ids; each is covered by its own test below.
COVERED_ELSEWHERE = {
    ("GET", "/api/lists"),  # test_my_lists_by_role
    ("POST", "/api/lists"),  # test_creating_a_list_by_role
    ("GET", "/api/shared"),  # test_shared_with_me_by_role
    ("POST", "/api/join/preview"),  # test_join_preview_by_role
    ("POST", "/api/join"),  # test_join_by_role
}


def expected(endpoint: Endpoint, relation: str) -> int:
    return {
        OWNER: endpoint.success,
        INVITEE: endpoint.invitee,
        INVITEE_ELSEWHERE: 404,
        REMOVED: 404,
        UNRELATED: 404,
        SIGNED_OUT: 401,
    }[relation]


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


def assert_reveals_nothing(body: Any, hidden: set[str], owner: bool = False) -> None:
    """No hidden id or token in the body, and no `join_token` key unless the
    caller is the owner of the list the body is about."""
    for key, value in walk(body):
        assert owner or key != "join_token"
        assert key not in hidden
        assert not (isinstance(value, str) and value in hidden), value


def owners_view(client, scenario: Scenario) -> dict[str, Any]:
    """Both lists as their owners see them: their gifts, their occasions with
    links and member counts, and who joined or was removed from the first."""
    view = {}
    for list_key, ids in scenario.lists.items():
        headers = scenario.headers(LISTS[list_key][0])
        view[list_key] = client.get(
            f"/api/lists/{ids['list_id']}", headers=headers
        ).json()
        view[list_key, FIRST] = client.get(
            f"/api/occasions/{ids[FIRST]}/members", headers=headers
        ).json()
    return view


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=str)
def test_endpoint_by_role(client, scenario, endpoint, list_key, actor):
    relation = scenario.relation(actor, list_key)
    status = expected(endpoint, relation)
    before = owners_view(client, scenario)

    response = call(client, scenario, actor, endpoint, scenario.lists[list_key])

    assert response.status_code == status, response.text
    if response.content:
        assert_reveals_nothing(
            response.json(), scenario.hidden_from(actor), owner=relation == OWNER
        )
    if status < 400:
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


@pytest.mark.parametrize("actor", ACTORS)
def test_shared_with_me_by_role(client, scenario, actor):
    response = client.get("/api/shared", headers=scenario.headers(actor))

    if actor == SIGNED_OUT:
        assert response.status_code == 401
        return
    assert response.status_code == 200
    # Owners are never invitees of their own lists, strangers of anything.
    assert {found["id"] for found in response.json()} == scenario.joined(actor)
    assert_reveals_nothing(response.json(), scenario.hidden_from(actor))


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
def test_join_preview_by_role(client, scenario, list_key, actor):
    relation = scenario.relation(actor, list_key)
    ids = scenario.lists[list_key]
    before = owners_view(client, scenario)

    response = client.post(
        "/api/join/preview",
        json={"token": scenario.tokens[list_key][FIRST]},
        headers=scenario.headers(actor),
    )

    assert owners_view(client, scenario) == before
    if relation == SIGNED_OUT:
        assert response.status_code == 401
        return
    if relation == REMOVED:
        # Removed: the link is as good as unknown to them (D4).
        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}
        return
    assert response.status_code == 200
    preview = response.json()
    # Only the ids the caller may already see: the list to an owner, the
    # occasion to its member, none to anyone else (D6).
    assert (preview["role"], preview["list_id"], preview["occasion_id"]) == {
        OWNER: ("owner", ids["list_id"], None),
        INVITEE: ("member", None, ids[FIRST]),
        INVITEE_ELSEWHERE: ("none", None, None),
        UNRELATED: ("none", None, None),
    }[relation]
    assert_reveals_nothing(preview, scenario.hidden_from(actor))


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
def test_join_by_role(client, scenario, rows, list_key, actor):
    relation = scenario.relation(actor, list_key)
    ids = scenario.lists[list_key]

    response = client.post(
        "/api/join",
        json={"token": scenario.tokens[list_key][FIRST]},
        headers=scenario.headers(actor),
    )

    if relation == SIGNED_OUT:
        assert response.status_code == 401
        return
    members = rows("occasion_members", "occasion_id", ids[FIRST])
    if relation == REMOVED:
        assert response.status_code == 404
        assert response.json() == {"detail": "Not found"}
        assert members == 1
        return
    if relation == OWNER:
        # An owner, for a "for me" list the recipient, never becomes an
        # invitee of their own list: the client opens the list instead (D6).
        assert response.status_code == 409
        assert response.json() == {
            "detail": "You own this list",
            "list_id": ids["list_id"],
        }
        assert members == 1
        return
    assert response.status_code == 200
    assert response.json() == {"occasion_id": ids[FIRST]}
    # The invitee who had joined stays one member; anyone else is a new one.
    assert members == (1 if relation == INVITEE else 2)
    # Joined: the occasion is now theirs to see, and nothing else is.
    assert_reveals_nothing(response.json(), scenario.hidden_from(actor) - {ids[FIRST]})


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
    in_matrix = {
        (endpoint.method, endpoint.route or endpoint.path) for endpoint in ENDPOINTS
    }

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
