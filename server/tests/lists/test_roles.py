"""The surprise rule, role by role (lists plan D10).

One scenario: a "for me" list and a "for someone else" list, each with its
owner, a gift with an image, a second gift the invitee of the first occasion
reserved and bought there, a third that is a group gift of the second
occasion, and two occasions dated in the future and shared by link, an
invitee who joined the first occasion and another who joined the second; a
hidden gift of the first occasion, with an image, added by its invitee;
a comment by the first occasion's invitee on the first gift, and their
follow of the second; someone who joined the first occasion of both lists
and was removed from them; and a stranger who has nothing to do with either.
Every endpoint is called by every actor on every list, and checked for:

- access: what each relation to the list and its first occasion gets
  (`expected`); the owner of the "for me" list, its recipient, gets 404 from
  every activity route (reserving plan D4);
- content: no JSON response carries a `join_token` key or an id or token the
  caller may not see (`Scenario.hidden_from`), whole or inside a string (an
  image id travels inside its paths); none to the recipient carries an
  activity key (`ACTIVITY_KEYS`);
- probing: whatever a refused caller gets for a real id, they get for a random
  one;
- no effect: a refused call leaves both lists as their owners see them, and
  each occasion's activity as its invitee sees it.

The routes that name no object of a list (my lists, creating a list, shared
with me, the join endpoints, uploading an image or giving its URL) have their
own tests by role, below.

`test_the_limit_by_role` runs the same scenario at the free plan's limits
(premium plan U9): an owner's growth is refused, identically on both lists,
and no giver route is limited.

Later plans extend the scenario rather than writing their own: a plan that
adds invitee activity adds it to the scenario and asserts that the recipient
sees none of it. A new route under `GUARDED_PREFIXES` without a row in
`ENDPOINTS` or `COVERED_ELSEWHERE` fails `test_every_route_is_in_the_matrix`.
"""

import base64
import io
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from PIL import Image

# Relative to today: a fixed date would turn the occasions into passed ones,
# where every activity write is refused (reserving plan D8).
OCCASION_DATE = (date.today() + timedelta(days=60)).isoformat()

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
# Who pledges on each list's group gift, in its second occasion, and how
# much: on the "for me" list its only giver there, the owner being the
# recipient; on the "for someone else" list its owner too (review R1-2).
PLEDGES = {
    FOR_ME: [(ME_INVITEE_ELSEWHERE, "40.00")],
    FOR_SOMEONE: [(OTHER_OWNER, "25.00"), (OTHER_INVITEE_ELSEWHERE, None)],
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
    # "image_id", the gift's image, "claimed_gift_id", the gift bought in the
    # first occasion, "group_gift_id", the group gift of the second occasion,
    # "hidden_gift_id" and "hidden_image_id", the first occasion's hidden gift
    # and its image, "comment_id", the invitee's comment on the first gift in
    # the first occasion, "occasion_id", "other_occasion_id", "user_id", the
    # invitee of the first occasion, and "removed_id", the person removed from
    # it).
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
        occasion and the list's gifts with their images, and their activity
        through that occasion, which names no user by id; not the list's id,
        its other occasion or any token. A removed person sees nothing of the
        list. Nobody sees another user's id unless they own a list that user
        joined. The hidden gift and its image are seen by the givers of its
        occasion only: its invitee and the owner of a list for someone else,
        never the owner of a list for them (hidden gifts plan D7). The
        comment's id, the same, is seen by the givers of its occasion only.
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
                if list_key == FOR_ME:
                    visible -= {
                        ids["hidden_gift_id"],
                        ids["hidden_image_id"],
                        ids["comment_id"],
                    }
            elif relation in (INVITEE, INVITEE_ELSEWHERE):
                occasion = FIRST if relation == INVITEE else SECOND
                visible |= {
                    ids[occasion],
                    ids["gift_id"],
                    ids["image_id"],
                    ids["claimed_gift_id"],
                    ids["group_gift_id"],
                }
                if relation == INVITEE:
                    visible |= {
                        ids["hidden_gift_id"],
                        ids["hidden_image_id"],
                        ids["comment_id"],
                    }
        return everything - visible

    def joined(self, actor: str) -> set[str]:
        """The occasions the actor is an invitee of."""
        return {
            self.lists[list_key][occasion]
            for list_key, invitees in INVITEES.items()
            for occasion, invitee in invitees.items()
            if invitee == actor
        }


def png() -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize((64, 48)).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def scenario(client, make_account) -> Scenario:
    accounts = {actor: make_account(actor) for actor in ACTORS if actor != SIGNED_OUT}
    lists = {}
    tokens = {}
    for list_key, (owner, body) in LISTS.items():
        headers = accounts[owner].headers
        list_id = client.post("/api/lists", json=body, headers=headers).json()["id"]
        image = client.post("/api/images", content=png(), headers=headers).json()
        gift = client.post(
            f"/api/lists/{list_id}/gifts",
            json={
                "title": "Headphones",
                "links": ["https://shop.example.com/h"],
                "price_amount": 149,
                "price_currency": "EUR",
                "image_id": image["id"],
            },
            headers=headers,
        ).json()
        assert gift["image"]["id"] == image["id"]
        claimed = client.post(
            f"/api/lists/{list_id}/gifts", json={"title": "Scarf"}, headers=headers
        ).json()
        group = client.post(
            f"/api/lists/{list_id}/gifts",
            json={"title": "Bike", "price_amount": 480, "price_currency": "EUR"},
            headers=headers,
        ).json()
        ids = {
            "list_id": list_id,
            "gift_id": gift["id"],
            "image_id": image["id"],
            "claimed_gift_id": claimed["id"],
            "group_gift_id": group["id"],
        }
        tokens[list_key] = {}
        for occasion, name in ((FIRST, "Birthday 2026"), (SECOND, "Christmas 2026")):
            created = client.post(
                f"/api/lists/{list_id}/occasions",
                json={"name": name, "date": OCCASION_DATE},
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
        # Activity: the first occasion's invitee reserves the second gift
        # there, then buys it (reserving plan D6).
        giver = accounts[INVITEES[list_key][FIRST]].headers
        for action in ("reservation", "bought"):
            done = client.post(
                f"/api/occasions/{ids[FIRST]}/gifts/{claimed['id']}/{action}",
                headers=giver,
            )
            assert done.status_code == 200, done.text
        # And a group gift in the second occasion (reserving plan D6, D9).
        for pledger, amount in PLEDGES[list_key]:
            pledged = client.put(
                f"/api/occasions/{ids[SECOND]}/gifts/{group['id']}/pledge",
                json={"amount": amount},
                headers=accounts[pledger].headers,
            )
            assert pledged.status_code == 200, pledged.text
        # A hidden gift of the first occasion, with an image, added by its
        # invitee; on the list for someone else, its owner reserves it
        # (hidden gifts plan D7).
        hidden_image = client.post("/api/images", content=png(), headers=giver).json()
        hidden = client.post(
            f"/api/occasions/{ids[FIRST]}/hidden-gifts",
            json={"title": "Drone", "image_id": hidden_image["id"]},
            headers=giver,
        )
        assert hidden.status_code == 201, hidden.text
        ids["hidden_gift_id"] = hidden.json()["id"]
        ids["hidden_image_id"] = hidden_image["id"]
        if list_key == FOR_SOMEONE:
            reserved = client.post(
                f"/api/occasions/{ids[FIRST]}/gifts/{ids['hidden_gift_id']}/reservation",
                headers=headers,
            )
            assert reserved.status_code == 200, reserved.text
        # A comment on the first gift and a follow of the second, in the
        # first occasion (comments plan D5).
        gift_path = f"/api/occasions/{ids[FIRST]}/gifts"
        commented = client.post(
            f"{gift_path}/{gift['id']}/comments",
            json={"body": "I'll take the blue one"},
            headers=giver,
        )
        assert commented.status_code == 201, commented.text
        ids["comment_id"] = commented.json()["id"]
        followed = client.put(f"{gift_path}/{claimed['id']}/follow", headers=giver)
        assert followed.status_code == 204, followed.text
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
    # The status for the owner of the "for me" list, its recipient, when it
    # is not `success`: 404 on every activity route (reserving plan D4).
    recipient: int | None = None
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
    # Received and put back, on any gift its owners see; keep, only on a
    # revealed one: the scenario's gift is on the list (hidden gifts plan D5,
    # D6).
    Endpoint("POST", "/api/gifts/{gift_id}/received", None, 204),
    Endpoint("DELETE", "/api/gifts/{gift_id}/received", None, 204),
    Endpoint("POST", "/api/gifts/{gift_id}/keep", None, 409),
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
    # The gift's image: owners through their path, invitees through their
    # occasion's (gift images plan D7).
    Endpoint(
        "GET",
        "/api/images/{image_id}/full",
        None,
        200,
        route="/api/images/{image_id}/{variant}",
    ),
    Endpoint(
        "GET",
        "/api/occasions/{occasion_id}/images/{image_id}/thumb",
        None,
        200,
        invitee=200,
        route="/api/occasions/{occasion_id}/images/{image_id}/{variant}",
    ),
    # Invitee activity: its givers, the invitees of the occasion and the
    # owners of a list for someone else, see and act; its recipient gets what
    # a stranger gets (reserving plan D4, D6).
    Endpoint(
        "GET", "/api/occasions/{occasion_id}/claims", None, 200, 200, recipient=404
    ),
    Endpoint(
        "POST",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation",
        None,
        200,
        200,
        recipient=404,
    ),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation",
        None,
        204,
        204,
        recipient=404,
    ),
    Endpoint(
        "POST",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/bought",
        None,
        200,
        200,
        recipient=404,
    ),
    Endpoint(
        "PUT",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge",
        {"amount": "20.00"},
        200,
        200,
        recipient=404,
    ),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge",
        None,
        204,
        204,
        recipient=404,
    ),
    # The hidden gifts of the occasion, its invitee the author of the
    # scenario's: its givers read and add, only the author changes it; the
    # recipient gets what a stranger gets (hidden gifts plan D7, D8).
    Endpoint(
        "GET",
        "/api/occasions/{occasion_id}/hidden-gifts",
        None,
        200,
        200,
        recipient=404,
    ),
    Endpoint(
        "POST",
        "/api/occasions/{occasion_id}/hidden-gifts",
        {"title": "Lamp"},
        201,
        201,
        recipient=404,
    ),
    Endpoint(
        "PATCH",
        "/api/occasions/{occasion_id}/hidden-gifts/{hidden_gift_id}",
        {"title": "Renamed"},
        403,
        200,
        recipient=404,
        route="/api/occasions/{occasion_id}/hidden-gifts/{gift_id}",
    ),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/hidden-gifts/{hidden_gift_id}",
        None,
        403,
        204,
        recipient=404,
        route="/api/occasions/{occasion_id}/hidden-gifts/{gift_id}",
    ),
    # Its image: only through the occasion, for its givers.
    Endpoint(
        "GET",
        "/api/images/{hidden_image_id}/full",
        None,
        404,
        route="/api/images/{image_id}/{variant}",
    ),
    Endpoint(
        "GET",
        "/api/occasions/{occasion_id}/images/{hidden_image_id}/thumb",
        None,
        200,
        200,
        recipient=404,
        route="/api/occasions/{occasion_id}/images/{image_id}/{variant}",
    ),
    # The thread of a gift in the occasion: its givers read, post and follow,
    # only the author changes a comment; the recipient gets what a stranger
    # gets, and so does the giver who is not its author (comments plan D5).
    Endpoint(
        "GET",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/comments",
        None,
        200,
        200,
        recipient=404,
    ),
    Endpoint(
        "POST",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/comments",
        {"body": "Hello"},
        201,
        201,
        recipient=404,
    ),
    Endpoint(
        "PATCH",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/comments/{comment_id}",
        {"body": "Edited"},
        404,
        200,
        recipient=404,
    ),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/comments/{comment_id}",
        None,
        404,
        204,
        recipient=404,
    ),
    Endpoint(
        "PUT",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/follow",
        None,
        204,
        204,
        recipient=404,
    ),
    Endpoint(
        "DELETE",
        "/api/occasions/{occasion_id}/gifts/{gift_id}/follow",
        None,
        204,
        204,
        recipient=404,
    ),
    # The hidden gift's id on the owner routes: the random id's 404 for every
    # owner, the givers among them reaching it as givers (hidden gifts plan
    # D4).
    Endpoint(
        "PATCH",
        "/api/gifts/{hidden_gift_id}",
        {"title": "Renamed"},
        404,
        route="/api/gifts/{gift_id}",
    ),
    Endpoint(
        "DELETE", "/api/gifts/{hidden_gift_id}", None, 404, route="/api/gifts/{gift_id}"
    ),
    Endpoint(
        "POST",
        "/api/gifts/{hidden_gift_id}/received",
        None,
        404,
        route="/api/gifts/{gift_id}/received",
    ),
    Endpoint(
        "DELETE",
        "/api/gifts/{hidden_gift_id}/received",
        None,
        404,
        route="/api/gifts/{gift_id}/received",
    ),
    Endpoint(
        "POST",
        "/api/gifts/{hidden_gift_id}/keep",
        None,
        404,
        route="/api/gifts/{gift_id}/keep",
    ),
]

# What only a giver may read (reserving plan D6): never a key of a response
# to the recipient.
ACTIVITY_KEYS = {
    "claims",
    "participants",
    "pledge_amount",
    "state",
    "bought",
    "expired",
    "passed",
    "author",
    "mine",
    "comments",
    "following",
    "author_name",
    "edited",
}

# The API paths whose routes must all appear in this module.
GUARDED_PREFIXES = (
    "/api/lists",
    "/api/gifts",
    "/api/occasions",
    "/api/join",
    "/api/shared",
    "/api/images",
    "/api/billing",
    "/api/admin",
)

# Routes under those prefixes that name no object of a list, so they cannot
# take the scenario's ids; each is covered by its own test below.
COVERED_ELSEWHERE = {
    ("GET", "/api/lists"),  # test_my_lists_by_role
    ("POST", "/api/lists"),  # test_creating_a_list_by_role
    ("GET", "/api/shared"),  # test_shared_with_me_by_role
    ("POST", "/api/join/preview"),  # test_join_preview_by_role
    ("POST", "/api/join"),  # test_join_by_role
    ("POST", "/api/images"),  # test_uploading_an_image_by_role
    ("POST", "/api/images/from-url"),  # test_image_from_url_by_role
    ("GET", "/api/billing"),  # test_billing_status_by_role
    ("POST", "/api/billing/checkout"),  # test_billing_sessions_by_role
    ("POST", "/api/billing/portal"),  # test_billing_sessions_by_role
    ("POST", "/api/billing/webhook"),  # test_stripe_webhook_by_role
    ("POST", "/api/billing/apple/transactions"),  # test_apple_transactions_by_role
    ("POST", "/api/billing/apple/notifications"),  # test_apple_notifications_by_role
    ("POST", "/api/billing/google/purchases"),  # test_google_purchases_by_role
    ("POST", "/api/billing/google/notifications"),  # test_google_notifications_by_role
    # The admin routes: every role but the admin gets 404, in
    # tests/admin/test_admin_routes.py (admin panel plan Conventions).
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/users/{user_id}"),
    ("POST", "/api/admin/users/{user_id}/premium"),
    ("DELETE", "/api/admin/users/{user_id}/premium"),
    ("DELETE", "/api/admin/users/{user_id}"),
}


def expected(endpoint: Endpoint, relation: str, list_key: str) -> int:
    if relation == OWNER and list_key == FOR_ME and endpoint.recipient is not None:
        return endpoint.recipient
    return {
        OWNER: endpoint.success,
        INVITEE: endpoint.invitee,
        INVITEE_ELSEWHERE: 404,
        REMOVED: 404,
        UNRELATED: 404,
        SIGNED_OUT: 401,
    }[relation]


def enforce(client, billing_on, **limits):
    """The free plan's limits enforced on this app (premium plan Conventions)."""
    state = client.app.state
    state.settings = state.settings.model_copy(update=billing_on | limits)


def plan_limit(resource: str, limit: int) -> dict[str, Any]:
    """The body of a refusal at the free plan's limit (premium plan D4)."""
    return {
        "detail": "The free plan's limit is reached",
        "code": "plan_limit",
        "resource": resource,
        "limit": limit,
    }


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


def assert_reveals_nothing(
    body: Any, hidden: set[str], owner: bool = False, recipient: bool = False
) -> None:
    """No hidden id or token in the body, whole or inside a string value (an
    image id travels inside `url` and `thumb_url`, review R1-7), no
    `join_token` key unless the caller is the owner of the list the body is
    about, and no activity key for the recipient (the owner of the "for me"
    list)."""
    for key, value in walk(body):
        assert owner or key != "join_token"
        assert not (recipient and key in ACTIVITY_KEYS), key
        assert key not in hidden
        if isinstance(value, str):
            assert not any(h in value for h in hidden), value


def test_a_hidden_id_inside_a_string_is_caught():
    """Guard for review R1-7: the scan sees ids inside paths, not only whole."""
    hidden = str(uuid.uuid4())

    with pytest.raises(AssertionError):
        assert_reveals_nothing(
            {"gifts": [{"image": {"url": f"/api/images/{hidden}/full"}}]}, {hidden}
        )
    assert_reveals_nothing({"url": f"/api/images/{uuid.uuid4()}/full"}, {hidden})


def test_an_activity_key_is_caught_for_the_recipient_only():
    body = {"gifts": [{"state": "reserved", "participants": []}]}

    with pytest.raises(AssertionError):
        assert_reveals_nothing(body, set(), recipient=True)
    assert_reveals_nothing(body, set())


def owners_view(client, scenario: Scenario) -> dict[str, Any]:
    """Both lists as their owners see them: their gifts, their occasions with
    links and member counts, and who joined or was removed from the first;
    each occasion's activity, as its invitee sees it, with its hidden gifts;
    and the first gift's thread in the first occasion, as that invitee sees
    it."""
    view = {}
    for list_key, ids in scenario.lists.items():
        headers = scenario.headers(LISTS[list_key][0])
        view[list_key] = client.get(
            f"/api/lists/{ids['list_id']}", headers=headers
        ).json()
        view[list_key, FIRST] = client.get(
            f"/api/occasions/{ids[FIRST]}/members", headers=headers
        ).json()
        for occasion in (FIRST, SECOND):
            view[list_key, occasion, "claims"] = client.get(
                f"/api/occasions/{ids[occasion]}/claims",
                headers=scenario.headers(INVITEES[list_key][occasion]),
            ).json()
            view[list_key, occasion, "hidden gifts"] = client.get(
                f"/api/occasions/{ids[occasion]}/hidden-gifts",
                headers=scenario.headers(INVITEES[list_key][occasion]),
            ).json()
        view[list_key, FIRST, "thread"] = client.get(
            f"/api/occasions/{ids[FIRST]}/gifts/{ids['gift_id']}/comments",
            headers=scenario.headers(INVITEES[list_key][FIRST]),
        ).json()
    return view


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=str)
def test_endpoint_by_role(client, scenario, endpoint, list_key, actor):
    relation = scenario.relation(actor, list_key)
    status = expected(endpoint, relation, list_key)
    before = owners_view(client, scenario)

    response = call(client, scenario, actor, endpoint, scenario.lists[list_key])

    assert response.status_code == status, response.text
    # An image's bytes are the only body that is not JSON.
    if response.headers.get("content-type") == "application/json":
        assert_reveals_nothing(
            response.json(),
            scenario.hidden_from(actor),
            owner=relation == OWNER,
            recipient=actor == ME_OWNER,
        )
    if status < 400:
        return
    # Refused: nothing changed, and the answer is the one for ids that exist
    # nowhere, so a real id cannot be told from a random one.
    assert owners_view(client, scenario) == before
    if status == 403:
        # A refusal about a gift they can see as a giver: never to the
        # recipient (hidden gifts plan D7).
        assert (relation, list_key) == (OWNER, FOR_SOMEONE)
        assert response.json()["code"] == "not_author"
        return
    random_ids = {name: str(uuid.uuid4()) for name in scenario.lists[list_key]}
    probe = call(client, scenario, actor, endpoint, random_ids)
    if status == 409:
        # A conflict on a gift its owner sees, not a refusal: an id that
        # exists nowhere gets the 404 every refusal gets (hidden gifts plan
        # D5, D6).
        assert relation == OWNER
        assert (probe.status_code, probe.json()) == (404, {"detail": "Not found"})
        return
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
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )


@pytest.mark.parametrize("actor", ACTORS)
def test_creating_a_list_by_role(client, scenario, actor):
    before = owners_view(client, scenario)

    response = client.post(
        "/api/lists",
        json={"title": "New", "recipient_kind": "self"},
        headers=scenario.headers(actor),
    )

    assert response.status_code == (401 if actor == SIGNED_OUT else 201)
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )
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
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )


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
    assert_reveals_nothing(
        preview, scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )


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
    assert_reveals_nothing(
        response.json(),
        scenario.hidden_from(actor) - {ids[FIRST]},
        recipient=actor == ME_OWNER,
    )


@pytest.mark.parametrize("actor", ACTORS)
def test_uploading_an_image_by_role(client, scenario, actor):
    """Anyone signed in uploads; the image is theirs, pending, and says
    nothing of anyone's lists."""
    before = owners_view(client, scenario)

    response = client.post(
        "/api/images", content=png(), headers=scenario.headers(actor)
    )

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert response.status_code == 401
        return
    assert response.status_code == 201
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )
    # Readable by its uploader only.
    for reader in ACTORS:
        read = client.get(response.json()["url"], headers=scenario.headers(reader))
        assert read.status_code == (
            200 if reader == actor else 401 if reader == SIGNED_OUT else 404
        )


@pytest.mark.parametrize("actor", ACTORS)
def test_image_from_url_by_role(client, scenario, url_fetcher, actor):
    url_fetcher.result = (png(), "image/png")
    before = owners_view(client, scenario)

    response = client.post(
        "/api/images/from-url",
        json={"url": "https://shop.example.com/h.png"},
        headers=scenario.headers(actor),
    )

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert response.status_code == 401
        assert url_fetcher.calls == []
        return
    assert response.status_code == 201
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )
    for reader in ACTORS:
        read = client.get(response.json()["url"], headers=scenario.headers(reader))
        assert read.status_code == (
            200 if reader == actor else 401 if reader == SIGNED_OUT else 404
        )


@pytest.mark.parametrize("actor", [actor for actor in ACTORS if actor != SIGNED_OUT])
@pytest.mark.parametrize("list_key", LISTS)
def test_attaching_a_lists_image_elsewhere_by_role(client, scenario, list_key, actor):
    """Nobody, the list's owner included, attaches an image already on a
    gift to another gift: the same 422 for everyone, whatever they may see."""
    headers = scenario.headers(actor)
    own_list = client.post(
        "/api/lists", json={"title": "Mine", "recipient_kind": "self"}, headers=headers
    ).json()["id"]
    before = owners_view(client, scenario)

    response = client.post(
        f"/api/lists/{own_list}/gifts",
        json={"title": "Copy", "image_id": scenario.lists[list_key]["image_id"]},
        headers=headers,
    )

    assert (response.status_code, response.json()) == (
        422,
        {"detail": "image_not_attachable"},
    )
    assert owners_view(client, scenario) == before


@pytest.fixture
def billing_client(make_client, billing_on):
    """A client for the same database with the gateway configured (a fake)."""
    return make_client(**billing_on)


@pytest.mark.parametrize("actor", ACTORS)
def test_billing_status_by_role(client, billing_client, scenario, actor):
    """Everyone's status is their own plan; nothing of a list shows."""
    before = owners_view(client, scenario)

    response = billing_client.get("/api/billing", headers=scenario.headers(actor))

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert response.status_code == 401
        return
    assert response.status_code == 200
    assert response.json()["plan"] == "free"
    assert_reveals_nothing(
        response.json(), scenario.hidden_from(actor), recipient=actor == ME_OWNER
    )


@pytest.mark.parametrize("actor", ACTORS)
def test_billing_sessions_by_role(client, billing_client, scenario, actor):
    """The same answers for every role: a session is about the caller alone."""
    before = owners_view(client, scenario)
    headers = scenario.headers(actor)

    before_any_customer = billing_client.post("/api/billing/portal", headers=headers)
    checkout = billing_client.post("/api/billing/checkout", headers=headers)
    portal = billing_client.post("/api/billing/portal", headers=headers)

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert {
            before_any_customer.status_code,
            checkout.status_code,
            portal.status_code,
        } == {401}
        return
    assert before_any_customer.status_code == 409
    assert before_any_customer.json()["code"] == "no_subscription"
    assert checkout.status_code == 200
    assert portal.status_code == 200
    assert_reveals_nothing(checkout.json(), scenario.hidden_from(actor))
    assert_reveals_nothing(portal.json(), scenario.hidden_from(actor))


@pytest.mark.parametrize("actor", ACTORS)
def test_stripe_webhook_by_role(client, billing_client, scenario, actor):
    """A session is nothing to the webhook: without a signature, every actor
    gets the same refusal and changes nothing, and with no gateway the same
    404."""
    before = owners_view(client, scenario)
    gateway = billing_client.app.state.stripe_gateway

    refused = billing_client.post(
        "/api/billing/webhook", content=b"{}", headers=scenario.headers(actor)
    )
    absent = client.post(
        "/api/billing/webhook", content=b"{}", headers=scenario.headers(actor)
    )

    assert (refused.status_code, refused.json()) == (
        400,
        {"detail": "Invalid webhook"},
    )
    assert (absent.status_code, absent.json()) == (404, {"detail": "Not found"})
    assert gateway.calls == []
    assert owners_view(client, scenario) == before


@pytest.fixture
def apple_client(make_client, billing_on):
    """A client for the same database with Apple's gateway configured (Apple
    IAP plan D7): the real one, with Apple's root and a generated key. No
    call reaches Apple: nothing sent below passes verification, which fails
    before any network."""
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return make_client(
        **billing_on,
        apple_product_id="example.premium.yearly",
        apple_bundle_id="com.example.shushgift",
        apple_iap_issuer_id="issuer-placeholder",
        apple_iap_key_id="KEYPLACEHOLDER",
        apple_iap_private_key=key.decode(),
    )


@pytest.mark.parametrize("actor", ACTORS)
def test_apple_transactions_by_role(client, apple_client, scenario, actor):
    """A transaction is about the caller alone: without Apple's signature,
    every actor gets the same refusal and changes nothing, and with no
    gateway the same 404."""
    before = owners_view(client, scenario)
    headers = scenario.headers(actor)
    body = {"signed_transaction": "not a transaction"}

    refused = apple_client.post(
        "/api/billing/apple/transactions", json=body, headers=headers
    )
    absent = client.post("/api/billing/apple/transactions", json=body, headers=headers)

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert {refused.status_code, absent.status_code} == {401}
        return
    assert (refused.status_code, refused.json()) == (
        400,
        {"detail": "Invalid transaction", "code": "invalid_transaction"},
    )
    assert (absent.status_code, absent.json()) == (404, {"detail": "Not found"})


@pytest.mark.parametrize("actor", ACTORS)
def test_apple_notifications_by_role(client, apple_client, scenario, actor):
    """A session is nothing to Apple's notifications: without Apple's
    signature, every actor gets the same refusal and changes nothing, and
    with no gateway the same 404."""
    before = owners_view(client, scenario)
    headers = scenario.headers(actor)
    body = {"signedPayload": "not a notification"}

    refused = apple_client.post(
        "/api/billing/apple/notifications", json=body, headers=headers
    )
    absent = client.post("/api/billing/apple/notifications", json=body, headers=headers)

    assert (refused.status_code, refused.json()) == (
        400,
        {"detail": "Invalid notification"},
    )
    assert (absent.status_code, absent.json()) == (404, {"detail": "Not found"})
    assert owners_view(client, scenario) == before


@pytest.fixture
def google_client(make_client, billing_on):
    """A client for the same database with Google Play's gateway configured
    (Android release plan D6): the real one, with a generated service account
    key. No call reaches Google: nothing sent below is a purchase token or a
    Pub/Sub token, which is refused before any network."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    account = {
        "type": "service_account",
        "private_key": pem.decode(),
        "client_email": "play-api@example-project.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    return make_client(
        **billing_on,
        google_play_product_id="premium_yearly",
        google_play_package_name="com.example.shushgift",
        google_play_service_account_json=json.dumps(account),
        google_play_pubsub_audience="https://shushgift.example.test/notifications",
        google_play_pubsub_service_account="push@example.iam.gserviceaccount.com",
    )


@pytest.mark.parametrize("actor", ACTORS)
def test_google_purchases_by_role(client, google_client, scenario, actor):
    """A purchase is about the caller alone: without a purchase token, every
    actor gets the same refusal and changes nothing, and with no gateway the
    same 404."""
    before = owners_view(client, scenario)
    headers = scenario.headers(actor)
    body = {"purchase_token": "not a purchase token"}

    refused = google_client.post(
        "/api/billing/google/purchases", json=body, headers=headers
    )
    absent = client.post("/api/billing/google/purchases", json=body, headers=headers)

    assert owners_view(client, scenario) == before
    if actor == SIGNED_OUT:
        assert {refused.status_code, absent.status_code} == {401}
        return
    assert (refused.status_code, refused.json()) == (
        400,
        {"detail": "Invalid purchase", "code": "invalid_purchase"},
    )
    assert (absent.status_code, absent.json()) == (404, {"detail": "Not found"})


@pytest.mark.parametrize("actor", ACTORS)
def test_google_notifications_by_role(client, google_client, scenario, actor):
    """A session is nothing to Play's notifications: its token is no Pub/Sub
    token, so every actor gets the same refusal and changes nothing, and with
    no gateway the same 404."""
    before = owners_view(client, scenario)
    headers = scenario.headers(actor)
    notification = {
        "packageName": "com.example.shushgift",
        "subscriptionNotification": {"purchaseToken": "token-1"},
    }
    data = base64.b64encode(json.dumps(notification).encode()).decode()
    body = {"message": {"data": data}}

    refused = google_client.post(
        "/api/billing/google/notifications", json=body, headers=headers
    )
    absent = client.post(
        "/api/billing/google/notifications", json=body, headers=headers
    )

    assert (refused.status_code, refused.json()) == (
        400,
        {"detail": "Invalid notification"},
    )
    assert (absent.status_code, absent.json()) == (404, {"detail": "Not found"})
    assert owners_view(client, scenario) == before


def giver_route(method: str, path: str) -> Endpoint:
    return next(row for row in ENDPOINTS if (row.method, row.path) == (method, path))


OCCASION = "/api/occasions/{occasion_id}"
GIFT = OCCASION + "/gifts/{gift_id}"
HIDDEN = OCCASION + "/hidden-gifts"
# Every giver route, in an order where each still applies after the ones before
# it, where the matrix gives each a fresh scenario: the hidden gift's image
# before the gift goes, and a gift pledged on and released before it is bought.
GIVER_RUN = [
    giver_route("GET", OCCASION + "/claims"),
    giver_route("GET", HIDDEN),
    giver_route("POST", HIDDEN),
    giver_route("PATCH", HIDDEN + "/{hidden_gift_id}"),
    giver_route("GET", OCCASION + "/images/{hidden_image_id}/thumb"),
    giver_route("DELETE", HIDDEN + "/{hidden_gift_id}"),
    giver_route("GET", GIFT + "/comments"),
    giver_route("POST", GIFT + "/comments"),
    giver_route("PATCH", GIFT + "/comments/{comment_id}"),
    giver_route("DELETE", GIFT + "/comments/{comment_id}"),
    giver_route("PUT", GIFT + "/follow"),
    giver_route("DELETE", GIFT + "/follow"),
    giver_route("PUT", GIFT + "/pledge"),
    giver_route("DELETE", GIFT + "/pledge"),
    giver_route("POST", GIFT + "/reservation"),
    giver_route("DELETE", GIFT + "/reservation"),
    giver_route("POST", GIFT + "/bought"),
]
# The routes about what the first occasion's invitee wrote: nothing of their
# own to an invitee of the second.
NAMES_THE_FIRST_OCCASIONS = ("{hidden_gift_id}", "{hidden_image_id}", "{comment_id}")


def test_every_giver_route_is_in_the_limit_run():
    assert {str(row) for row in GIVER_RUN} == {
        str(row) for row in ENDPOINTS if row.recipient is not None
    }


@pytest.mark.parametrize("actor", ACTORS)
@pytest.mark.parametrize("list_key", LISTS)
def test_the_limit_by_role(client, billing_on, scenario, list_key, actor):
    """Both lists full and each of their owners at one list (premium plan D4,
    D5, NEEDS "Only owners pay"): an owner's growth gets the same 402 on both
    lists, what no owner may do gets the random id's answer, and every giver
    route still works, for the giving owner and whatever the giver's plan."""
    ids = scenario.lists[list_key]
    relation = scenario.relation(actor, list_key)
    headers = scenario.headers(actor)
    enforce(client, billing_on, free_max_gifts_per_list=3, free_max_lists=1)
    before = owners_view(client, scenario)
    gift_route = "/api/lists/{}/gifts"
    received_route = "/api/gifts/{}/received"
    keep_route = "/api/gifts/{}/keep"
    next_gift = {"title": "Next"}

    new_list = client.post(
        "/api/lists", json={"title": "Next", "recipient_kind": "self"}, headers=headers
    )
    new_gift = client.post(
        gift_route.format(ids["list_id"]), json=next_gift, headers=headers
    )
    put_back = client.delete(received_route.format(ids["gift_id"]), headers=headers)
    keep = client.post(keep_route.format(ids["gift_id"]), headers=headers)

    assert owners_view(client, scenario) == before
    if relation == SIGNED_OUT:
        answers = {new_list.status_code, new_gift.status_code}
        assert answers | {put_back.status_code, keep.status_code} == {401}
    else:
        if actor in (ME_OWNER, OTHER_OWNER):
            assert (new_list.status_code, new_list.json()) == (
                402,
                plan_limit("lists", 1),
            )
        else:
            # Their first list: they are not limited for being invited.
            assert new_list.status_code == 201, new_list.text
        if relation == OWNER:
            assert (new_gift.status_code, new_gift.json()) == (
                402,
                plan_limit("gifts", 3),
            )
            assert put_back.status_code == 204, put_back.text
            assert keep.status_code == 409, keep.text
        else:
            # Refused, and a real id cannot be told from a random one.
            random = str(uuid.uuid4())
            for real, probe in (
                (
                    new_gift,
                    client.post(
                        gift_route.format(random), json=next_gift, headers=headers
                    ),
                ),
                (
                    put_back,
                    client.delete(received_route.format(random), headers=headers),
                ),
                (keep, client.post(keep_route.format(random), headers=headers)),
            ):
                assert (real.status_code, real.json()) == (404, {"detail": "Not found"})
                assert (probe.status_code, probe.json()) == (
                    real.status_code,
                    real.json(),
                )
        for refused in (new_list, new_gift, put_back, keep):
            if refused.status_code >= 400:
                assert_reveals_nothing(
                    refused.json(),
                    scenario.hidden_from(actor),
                    recipient=actor == ME_OWNER,
                )

    run, giver, occasion = GIVER_RUN, relation, ids[FIRST]
    if relation == INVITEE_ELSEWHERE:
        # Their own occasion, the second, where they are a giver.
        run = [
            row
            for row in GIVER_RUN
            if not any(name in row.path for name in NAMES_THE_FIRST_OCCASIONS)
        ]
        giver, occasion = INVITEE, ids[SECOND]
    for endpoint in run:
        answer = call(client, scenario, actor, endpoint, ids | {FIRST: occasion})
        assert answer.status_code == expected(endpoint, giver, list_key), (
            endpoint,
            answer.text,
        )


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
