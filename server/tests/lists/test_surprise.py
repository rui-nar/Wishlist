"""The recipient sees nothing, endpoint by endpoint (reserving plan D12).

An owner of a "for me" list, its recipient, gets the same answer from every
endpoint they can call whatever the activity on their gifts: the same status,
the same body and the same headers, apart from `Date`.

Each test builds two worlds with the same calls, side by side: one where the
invitees left the activity of a state (`STATES`) on gift G1, and a control
where nobody did anything. A world is a "for me" list with two gifts identical
in every field, G1 and G2, each with its image; four occasions, A and B dated
in the future, P moved into the past after the activity and D deleted after
it, each with its invitees; and a co-owner, Cora, who was an invitee of A
until the activity was made and is blind from then on (D4). The recipient,
the owner or Cora, then calls every route of the API (read from the OpenAPI
document by `test_every_route_is_called`, which fails on a route this module
does not call): reads, every activity route, edits, and deletions. Their
answers are compared:

- world against control, after renaming each id and token of the world into
  the control's: identical, from the owner's first call of the setup on;
- G1 against its twin G2 within the world, and removing the invitee who holds
  the activity against removing one who holds none, after swapping their ids;
- every activity route, on every occasion, against the same route on ids
  that exist nowhere (D4);
- no answer carries an activity key, nor an invitee's name outside the
  members list.

Lock waits are not compared: an owner's change can wait a few milliseconds on
a giver's write, which cannot be told from network jitter (review round 2).
The owner of a list for someone else, a giver, is the contrast: the same
comparison finds the activity (`test_a_giving_owner_sees_the_activity`).

Hidden gifts are activity too (hidden gifts plan D11). `HIDDEN_STATES` are
built on the `none` state of G1: only the world has the hidden gift, whose id
and image's id are random in the control, and the recipient's calls name them
in both. `test_a_revealed_gift_shows_as_the_gift_alone` is the decided
exception, once the occasion has passed. Comments and following are activity
too (comments plan D5): the "commented" state on G1, whose comment's id is
random in the control, and the recipient's calls name it in both.
"""

import io
import json
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from typing import Any

import pytest
from claims_invariants import assert_claims_consistent
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_hidden_model import noon_after

from app.accounts import sessions
from app.media.images import VARIANTS

# Relative to today: a fixed date would turn into a passed occasion (D8).
FUTURE = (date.today() + timedelta(days=60)).isoformat()
LATER = (date.today() + timedelta(days=90)).isoformat()
# Passed for good.
PAST = "2001-01-01"
# For the reveal: the clock is moved past them, within a session's 90 days.
SOON = date.today() + timedelta(days=3)
MOVED = date.today() + timedelta(days=10)

OWNER = "owner"
CO_OWNER = "co-owner"
NAMES = {
    OWNER: "Olga Owner",
    CO_OWNER: "Cora Coowner",
    "ana": "Ana Giver",
    "eve": "Eve Giver",
    "ben": "Ben Giver",
    "cleo": "Cleo Giver",
    "pia": "Pia Giver",
    "dan": "Dan Giver",
}
INVITEE_NAMES = [name for key, name in NAMES.items() if key not in (OWNER, CO_OWNER)]

# Each occasion of a world, by the name of its id: its name and who joined it.
# The co-owner joined A as an invitee before she became an owner (D4).
OCCASIONS = {
    "A": ("Birthday", ["ana", "eve", "ben", CO_OWNER]),
    "B": ("Christmas", ["cleo"]),
    "P": ("Last year", ["pia"]),
    "D": ("Cancelled", ["dan"]),
}

# G1 and G2: identical in every field but their ids and their images' ids.
GIFT = {
    "title": "Headphones",
    "description": "Over-ear, black",
    "links": ["https://shop.example.com/h"],
    "price_amount": 149,
    "price_currency": "EUR",
}

# What the invitees do on G1, in order: (who, in which occasion, the activity
# route, the pledge). P is moved into the past and D deleted afterwards, in
# every world.
STATES = {
    "none": [],
    "reserved": [("ana", "A", "reservation", None)],
    "reserved and bought": [
        ("ana", "A", "reservation", None),
        ("ana", "A", "bought", None),
    ],
    "group gift with pledges": [
        ("ana", "A", "pledge", "30.00"),
        ("eve", "A", "pledge", None),
    ],
    "group gift bought": [
        ("ana", "A", "pledge", "30.00"),
        ("eve", "A", "pledge", None),
        ("ana", "A", "bought", None),
    ],
    "taken by the other occasion": [("cleo", "B", "reservation", None)],
    "claim of the passed occasion, bought": [
        ("pia", "P", "reservation", None),
        ("pia", "P", "bought", None),
    ],
    # Expired: no giver but its own sees it any more (D8, review R3-1).
    "claim of the passed occasion, expired": [("pia", "P", "reservation", None)],
    "bought for an occasion since deleted": [("dan", "D", "bought", None)],
    # A thread with an edited comment, a comment by a since-removed invitee,
    # and a follower (comments plan D5); the owner's removal happens in both
    # worlds.
    "commented": [
        ("ana", "A", "comment", None),
        ("ana", "A", "edit comment", None),
        ("ben", "A", "comment", None),
        ("eve", "A", "follow", None),
        ("ben", "A", "remove", None),
    ],
}

ADD = ("ana", "A", "add", None)
# What the invitees do with a hidden gift H, with its image, on top of G1's
# `none` state (hidden gifts plan D11): in the world only, but for the owner's
# "remove" and the invitee's "leave", which both worlds see.
HIDDEN_STATES = {
    "hidden gift with an image": [ADD],
    "hidden gift reserved": [ADD, ("eve", "A", "reservation", None)],
    "hidden group gift with pledges": [
        ADD,
        ("eve", "A", "pledge", "30.00"),
        ("ben", "A", "pledge", None),
    ],
    "hidden gift bought": [
        ADD,
        ("eve", "A", "reservation", None),
        ("eve", "A", "bought", None),
    ],
    # Added and bought before the owner moves P into the past (D3).
    "hidden gift bought in the passed occasion": [
        ("pia", "P", "add", None),
        ("pia", "P", "bought", None),
    ],
    # Deleted with the occasion, which had not passed (D9).
    "hidden gift bought in the deleted occasion": [
        ("dan", "D", "add", None),
        ("dan", "D", "bought", None),
    ],
    # Deleted by the removal (D8).
    "hidden gift of a removed author": [
        ("ben", "A", "add", None),
        ("ben", "A", "remove", None),
    ],
    # Kept: somebody bought it (D8).
    "hidden gift bought, its author removed": [
        ("ben", "A", "add", None),
        ("ana", "A", "bought", None),
        ("ben", "A", "remove", None),
    ],
    "hidden gift of an author who left": [
        ("eve", "A", "add", None),
        ("eve", "A", "leave", None),
    ],
}
# The steps of a state, of either kind.
STEPS = STATES | HIDDEN_STATES

COMMENTS = "/api/occasions/{occasion_id}/gifts/{gift_id}/comments"
FOLLOW = "/api/occasions/{occasion_id}/gifts/{gift_id}/follow"
# The activity routes but the claims read, each with its body (D6).
ACTIVITY = [
    ("POST", "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation", None),
    ("DELETE", "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation", None),
    ("POST", "/api/occasions/{occasion_id}/gifts/{gift_id}/bought", None),
    ("PUT", "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge", {"amount": "20.00"}),
    ("DELETE", "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge", None),
    # The hidden gifts of the occasion (hidden gifts plan D7).
    ("GET", "/api/occasions/{occasion_id}/hidden-gifts", None),
    ("POST", "/api/occasions/{occasion_id}/hidden-gifts", {"title": "Lamp"}),
    (
        "PATCH",
        "/api/occasions/{occasion_id}/hidden-gifts/{gift_id}",
        {"title": "Renamed"},
    ),
    ("DELETE", "/api/occasions/{occasion_id}/hidden-gifts/{gift_id}", None),
    # The thread and following (comments plan D5).
    ("GET", COMMENTS, None),
    ("POST", COMMENTS, {"body": "Hello"}),
    ("PATCH", COMMENTS + "/{comment_id}", {"body": "Edited"}),
    ("DELETE", COMMENTS + "/{comment_id}", None),
    ("PUT", FOLLOW, None),
    ("DELETE", FOLLOW, None),
]
CLAIMS = "/api/occasions/{occasion_id}/claims"
HIDDEN_GIFTS = "/api/occasions/{occasion_id}/hidden-gifts"
# The routes an owner calls on a gift, each with its body.
OWNER_GIFT_ROUTES = [
    ("PATCH", "/api/gifts/{gift_id}", {"title": "Renamed"}),
    ("DELETE", "/api/gifts/{gift_id}", None),
    ("POST", "/api/gifts/{gift_id}/received", None),
    ("DELETE", "/api/gifts/{gift_id}/received", None),
    ("POST", "/api/gifts/{gift_id}/keep", None),
]
IMAGE = "/api/images/{image_id}/{variant}"
OCCASION_IMAGE = "/api/occasions/{occasion_id}/images/{image_id}/{variant}"
ACTIVITY_ROUTES = {route for _, route, _ in ACTIVITY} | {CLAIMS}
MEMBERS = "/api/occasions/{occasion_id}/members"

# What only a giver may read (D6): never a key of an answer to the recipient.
ACTIVITY_KEYS = {
    "claims",
    "participants",
    "pledge_amount",
    "state",
    "bought",
    "expired",
    "passed",
    "taken",
    "author",
    "mine",
    "comments",
    "following",
    "author_name",
    "edited",
}

# The twins of a world, by the names of their ids: swapped, each answer about
# the first is the answer about the second.
TWINS = [("G1", "G2"), ("img1", "img2"), ("up1", "up2")]

# How each test ends: the deletion that reaches G1's activity first.
ENDINGS = ["gifts first", "occasions first", "list first"]


# Each state is run for the owner and for the co-owner, with the endings in
# turn, so that it meets two of the three: every combination would take
# minutes, at tens of milliseconds a request. Stepping by two puts the
# co-owner's runs of the states left unbought (`UNBOUGHT`) on all three.
def runs_of(states: Iterable[str]) -> list[tuple[str, str, str]]:
    return [
        (state, actor, ENDINGS[(2 * number + turn) % len(ENDINGS)])
        for number, state in enumerate(states)
        for turn, actor in enumerate((OWNER, CO_OWNER))
    ]


RUNS = runs_of(STATES)
HIDDEN_RUNS = runs_of(HIDDEN_STATES)


def png() -> bytes:
    buffer = io.BytesIO()
    Image.linear_gradient("L").resize((64, 48)).save(buffer, "PNG")
    return buffer.getvalue()


@dataclass(frozen=True)
class Answer:
    # The call, with the names of its ids, for failure messages.
    call: str
    method: str
    route: str
    status: int
    # Lowercase names, without `Date`.
    headers: tuple[tuple[str, str], ...]
    # JSON as text, anything else as bytes (an image).
    body: str | bytes

    def renamed(self, rename: Callable[[str], str]) -> Answer:
        return Answer(
            self.call,
            self.method,
            self.route,
            self.status,
            tuple((name, rename(value)) for name, value in self.headers),
            rename(self.body) if isinstance(self.body, str) else self.body,
        )


def renamer(mapping: dict[str, str]) -> Callable[[str], str]:
    """Replaces every id or token of `mapping` by its image, all at once, in
    a text; ids in their hex form too (an image's ETag)."""
    full = dict(mapping)
    for old, new in mapping.items():
        try:
            full[uuid.UUID(old).hex] = uuid.UUID(new).hex
        except ValueError:
            pass  # a token or an email
    pattern = re.compile("|".join(map(re.escape, sorted(full, key=len, reverse=True))))
    return lambda value: pattern.sub(lambda found: full[found.group()], value)


@dataclass
class Recorder:
    """Calls the API as one account and keeps every answer, in order."""

    client: Any
    headers: dict[str, str]
    # The ids and tokens of the world, by name; the calls name them.
    ids: dict[str, str]
    answers: list[Answer] = field(default_factory=list)
    # Pairs of answers about twins, with the names they differ by.
    twins: list[tuple[Answer, Answer, list[tuple[str, str]]]] = field(
        default_factory=list
    )

    def call(
        self,
        method: str,
        route: str,
        json: Any = None,
        content: bytes | None = None,
        headers: dict[str, str] | None = None,
        **params: str,
    ) -> Any:
        """Each path parameter is the name of an id, a variant itself."""
        values = {
            param: name if param == "variant" else self.ids[name]
            for param, name in params.items()
        }
        response = self.client.request(
            method,
            route.format(**values),
            json=json,
            content=content,
            headers=headers or self.headers,
        )
        is_json = response.headers.get("content-type") == "application/json"
        self.answers.append(
            Answer(
                call=f"{method} {route.format(**params)}",
                method=method,
                route=route,
                status=response.status_code,
                headers=tuple(
                    (name.lower(), value)
                    for name, value in response.headers.items()
                    if name.lower() != "date"
                ),
                body=response.text if is_json else response.content,
            )
        )
        return response

    def twin(
        self,
        method: str,
        route: str,
        sides: dict[str, tuple[str, str]],
        body: Callable[[int], Any] | None = None,
        **params: str,
    ) -> None:
        """Calls the route on the first twin of each pair in `sides`, then on
        the second."""
        for side in (0, 1):
            self.call(
                method,
                route,
                json=body(side) if body else None,
                **params,
                **{param: names[side] for param, names in sides.items()},
            )
        self.twins.append((self.answers[-2], self.answers[-1], list(sides.values())))

    def register(self, name: str, response: Any, key: str = "id") -> None:
        """Names what a call created, so later calls and the renaming find it."""
        assert response.status_code in (200, 201), response.text
        assert name not in self.ids
        self.ids[name] = response.json()[key]


@dataclass
class World:
    accounts: dict[str, Any]
    ids: dict[str, str]
    # The owner's calls while building it.
    setup: Recorder


def holder(state: str) -> tuple[str, str]:
    """Who holds the state's activity, on G1 or its hidden gift, and in which
    occasion; Ana, in A, when nobody, or nobody who is still an invitee, does."""
    gone = departed(state)
    for who, occasion, _, _ in STEPS[state]:
        if occasion != "D" and who not in gone:
            return who, occasion
    return "ana", "A"


def holders(state: str) -> set[str]:
    """Everyone in the state's activity who is still an invitee."""
    gone = departed(state)
    return {
        who
        for who, occasion, _, _ in STEPS[state]
        if occasion != "D" and who not in gone
    }


def departed(state: str) -> set[str]:
    """Who the owner removed or who left, as a step of the state."""
    return {who for who, _, action, _ in STEPS[state] if action in ("remove", "leave")}


# The states whose claim, on G1 or the hidden gift, is not bought: the
# co-owner's runs keep their holders until after the deletions, which would
# otherwise only ever meet bought claims, removal releasing the others (review
# R7-1).
UNBOUGHT = {
    state
    for state, done in STEPS.items()
    if any(action in ("reservation", "pledge") for _, _, action, _ in done)
    and all(action != "bought" for _, _, action, _ in done)
}


def add_hidden(
    client, ids: dict[str, str], account: Any, occasion: str, name: str, title: str
) -> None:
    """The account adds a hidden gift with an image to the occasion: its id is
    `name` in `ids`, its image's id `name image`."""
    image = client.post("/api/images", content=png(), headers=account.headers)
    assert image.status_code == 201, image.text
    added = client.post(
        f"/api/occasions/{ids[occasion]}/hidden-gifts",
        json=GIFT | {"title": title, "image_id": image.json()["id"]},
        headers=account.headers,
    )
    assert added.status_code == 201, added.text
    ids[name] = added.json()["id"]
    ids[f"{name} image"] = image.json()["id"]


def not_added(ids: dict[str, str], name: str) -> None:
    """The control has no hidden gift: `name` and its image are random ids."""
    ids[name] = str(uuid.uuid4())
    ids[f"{name} image"] = str(uuid.uuid4())


def build(
    client,
    make_account,
    engine,
    state: str,
    kind: str = "self",
    control: bool = False,
    when: str = FUTURE,
) -> World:
    """A world, with the state's activity unless `control`: the control keeps
    only the steps both worlds see, an invitee removed or leaving."""
    owner = make_account(NAMES[OWNER])
    accounts = {OWNER: owner}
    ids = {
        OWNER: owner.id,
        "nowhere": str(uuid.uuid4()),
        "nowhere gift": str(uuid.uuid4()),
        "nowhere comment": str(uuid.uuid4()),
        # Replaced by the state's first comment, when it has one: the
        # recipient's calls name it in every world.
        "comment": str(uuid.uuid4()),
    }
    setup = Recorder(client, owner.headers, ids)
    body = {"title": "My birthday", "recipient_kind": kind}
    if kind == "other":
        body |= {"title": "Leo's birthday", "recipient_name": "Leo"}
    setup.register("list", setup.call("POST", "/api/lists", json=body))
    for gift, image in (("G1", "img1"), ("G2", "img2")):
        setup.register(image, setup.call("POST", "/api/images", content=png()))
        setup.register(
            gift,
            setup.call(
                "POST",
                "/api/lists/{list_id}/gifts",
                json=GIFT | {"image_id": ids[image]},
                list_id="list",
            ),
        )
    for occasion, (name, invitees) in OCCASIONS.items():
        setup.register(
            occasion,
            setup.call(
                "POST",
                "/api/lists/{list_id}/occasions",
                json={"name": name, "date": when},
                list_id="list",
            ),
        )
        setup.register(
            f"token {occasion}",
            setup.call(
                "POST", "/api/occasions/{occasion_id}/link", occasion_id=occasion
            ),
            key="join_token",
        )
        for invitee in invitees:
            account = make_account(NAMES[invitee])
            accounts[invitee] = account
            ids[invitee] = account.id
            joined = client.post(
                "/api/join",
                json={"token": ids[f"token {occasion}"]},
                headers=account.headers,
            )
            assert joined.status_code == 200, joined.text

    hidden = state in HIDDEN_STATES
    if hidden and control:
        not_added(ids, "H")
    for who, occasion, action, amount in STEPS[state]:
        headers = accounts[who].headers
        if action == "remove":
            removed = setup.call(
                "DELETE",
                "/api/occasions/{occasion_id}/members/{user_id}",
                occasion_id=occasion,
                user_id=who,
            )
            assert removed.status_code == 204, removed.text
        elif action == "leave":
            left = client.delete(
                f"/api/occasions/{ids[occasion]}/membership", headers=headers
            )
            assert left.status_code == 204, left.text
        elif control:
            continue
        elif action == "add":
            add_hidden(client, ids, accounts[who], occasion, "H", GIFT["title"])
        elif action in ("comment", "edit comment", "follow"):
            thread_step(client, ids, headers, occasion, action, who == "ana")
        else:
            gift = ids["H" if hidden else "G1"]
            path = f"/api/occasions/{ids[occasion]}/gifts/{gift}/{action}"
            done = (
                client.put(path, json={"amount": amount}, headers=headers)
                if action == "pledge"
                else client.post(path, headers=headers)
            )
            assert done.status_code == 200, done.text

    # Cora saw the activity as an invitee; from now on she owns the list. No
    # endpoint adds a co-owner yet: the row is added directly.
    seen = client.get(
        f"/api/occasions/{ids['A']}/claims", headers=accounts[CO_OWNER].headers
    )
    assert seen.status_code == 200, seen.text
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO list_owners (list_id, user_id) VALUES (:list, :user)"),
            {"list": ids["list"], "user": ids[CO_OWNER]},
        )
        for account in (OWNER, CO_OWNER):
            ids[f"email of {account}"] = connection.scalar(
                text("SELECT email FROM users WHERE id = :user"), {"user": ids[account]}
            )
    setup.call(
        "PATCH", "/api/occasions/{occasion_id}", json={"date": PAST}, occasion_id="P"
    )
    setup.call("DELETE", "/api/occasions/{occasion_id}", occasion_id="D")

    # The state is really there: its holder sees it, Ana as "taken" when it
    # was bought in the deleted occasion (D6, D8, review R3-1).
    if hidden and not control:
        assert_hidden_gift_is_there(client, engine, state, accounts, ids)
    elif state == "commented" and not control:
        assert_thread_is_there(client, accounts, ids)
    elif not hidden and not control and STATES[state]:
        who, occasion = holder(state)
        seen = client.get(
            f"/api/occasions/{ids[occasion]}/claims", headers=accounts[who].headers
        )
        assert ids["G1"] in [gift["gift_id"] for gift in seen.json()["gifts"]]
    return World(accounts=accounts, ids=ids, setup=setup)


def thread_step(client, ids, headers, occasion, action, named) -> None:
    """A step of the "commented" state on G1 (comments plan D5). A `named`
    comment's id is the one the recipient's calls name."""
    thread = f"/api/occasions/{ids[occasion]}/gifts/{ids['G1']}"
    if action == "comment":
        done = client.post(
            f"{thread}/comments", json={"body": "Who has it?"}, headers=headers
        )
        assert done.status_code == 201, done.text
        if named:
            ids["comment"] = done.json()["id"]
    elif action == "edit comment":
        done = client.patch(
            f"{thread}/comments/{ids['comment']}",
            json={"body": "Who has the receipt?"},
            headers=headers,
        )
        assert done.status_code == 200, done.text
    else:
        done = client.put(f"{thread}/follow", headers=headers)
        assert done.status_code == 204, done.text


def assert_thread_is_there(client, accounts, ids) -> None:
    """The thread of the "commented" state, as a giver sees it: the edited
    comment, and the comment of an invitee since removed, with their name."""
    seen = client.get(
        f"/api/occasions/{ids['A']}/gifts/{ids['G1']}/comments",
        headers=accounts["eve"].headers,
    )
    assert seen.status_code == 200, seen.text
    assert seen.json()["following"] is True
    assert [
        (comment["author_name"], comment["edited"])
        for comment in seen.json()["comments"]
    ] == [(NAMES["ana"], True), (NAMES["ben"], False)]


# The hidden states whose gift no longer exists once the world is built (D8,
# D9), so no giver can see anything of it.
HIDDEN_GONE = {
    "hidden gift bought in the deleted occasion",
    "hidden gift of a removed author",
}


def assert_hidden_gift_is_there(client, engine, state, accounts, ids) -> None:
    """The hidden state is really there: a giver of its occasion sees the
    gift with its author's name, or nobody does because it was deleted."""
    if state in HIDDEN_GONE:
        with engine.connect() as connection:
            assert 0 == connection.scalar(
                text("SELECT count(*) FROM gifts WHERE id = :gift"), {"gift": ids["H"]}
            )
        return
    author, occasion, _, _ = HIDDEN_STATES[state][0]
    giver = OCCASIONS[occasion][1][0]
    seen = client.get(
        f"/api/occasions/{ids[occasion]}/hidden-gifts", headers=accounts[giver].headers
    )
    assert [(gift["id"], gift["author"]) for gift in seen.json()] == [
        (ids["H"], NAMES[author])
    ]


def assert_twin_gifts(rec: Recorder, gifts: list[dict[str, Any]], order: Iterable[str]):
    """The gifts in creation order (D3), and G1 shown as G2 is, swapped."""
    assert [gift["id"] for gift in gifts] == [rec.ids[name] for name in order]
    swap = renamer(swap_mapping(rec.ids, TWINS))
    assert json.loads(swap(json.dumps(gifts[0]))) == gifts[1]


def swap_mapping(
    ids: dict[str, str], pairs: Iterable[tuple[str, str]]
) -> dict[str, str]:
    mapping = {}
    for first, second in pairs:
        if first in ids and second in ids:
            mapping[ids[first]] = ids[second]
            mapping[ids[second]] = ids[first]
    return mapping


def reads(
    rec: Recorder,
    gifts: tuple[str, ...],
    images: tuple[str, str],
    revealed: tuple[str, ...] = (),
) -> None:
    """Everything the recipient can read, the claims included, with the
    gifts named in `gifts`, the twin images `images` on G1 and G2 and the
    hidden gifts named in `revealed` shown as revealed, in their order."""
    rec.call("GET", "/api/me")
    rec.call("GET", "/api/me/preferences")
    rec.call("PATCH", "/api/me/preferences", json={"language": "fr"})
    # A join token is no unsubscribe token.
    rec.call("POST", "/api/unsubscribe/{token}", token="token A")
    rec.call("GET", "/api/lists")
    detail = rec.call("GET", "/api/lists/{list_id}", list_id="list")
    assert_twin_gifts(rec, detail.json()["gifts"], gifts)
    # Only the expected hidden gifts are revealed, and nothing is left
    # received (hidden gifts plan D5, D6).
    assert detail.json()["received"] == []
    assert [gift["id"] for gift in detail.json()["revealed"]] == [
        rec.ids[name] for name in revealed
    ]
    rec.call("GET", "/api/shared")
    for occasion in OCCASIONS:
        view = rec.call("GET", "/api/occasions/{occasion_id}", occasion_id=occasion)
        if occasion != "D":
            assert_twin_gifts(rec, view.json()["gifts"], gifts)
        rec.call("GET", MEMBERS, occasion_id=occasion)
        rec.call("GET", CLAIMS, occasion_id=occasion)
        rec.call(
            "POST", "/api/join/preview", json={"token": rec.ids[f"token {occasion}"]}
        )
    rec.call("POST", "/api/join", json={"token": rec.ids["token A"]})
    for variant in VARIANTS:
        rec.twin(
            "GET",
            "/api/images/{image_id}/{variant}",
            {"image_id": images},
            variant=variant,
        )
        for occasion in ("A", "B", "P"):
            rec.twin(
                "GET",
                "/api/occasions/{occasion_id}/images/{image_id}/{variant}",
                {"image_id": images},
                occasion_id=occasion,
                variant=variant,
            )
    for route in ("/api/version", "/api/config", "/api/health"):
        rec.call("GET", route)
    rec.call("POST", "/api/auth/google", json={"id_token": "not a token"})


def activity(rec: Recorder) -> None:
    """Every activity route on G1 in every occasion, hidden gifts included,
    and every activity route on ids that exist nowhere. `reads` reads each
    occasion's claims."""
    targets = [(occasion, "G1", "comment") for occasion in OCCASIONS]
    for occasion, gift, comment in [
        *targets,
        ("nowhere", "nowhere gift", "nowhere comment"),
    ]:
        for method, route, body in ACTIVITY:
            rec.call(
                method,
                route,
                json=body,
                occasion_id=occasion,
                gift_id=gift,
                comment_id=comment,
            )
    rec.call("GET", CLAIMS, occasion_id="nowhere")


def hidden_routes(rec: Recorder, gift: str, image: str) -> None:
    """A hidden gift's id and its image's id on every route the recipient can
    call with them, on every occasion: what random ids answer (D11)."""
    for occasion in OCCASIONS:
        for method, route, body in ACTIVITY:
            if "{gift_id}" in route:
                rec.call(
                    method,
                    route,
                    json=body,
                    occasion_id=occasion,
                    gift_id=gift,
                    comment_id="comment",
                )
        for variant in VARIANTS:
            rec.call(
                "GET",
                OCCASION_IMAGE,
                occasion_id=occasion,
                image_id=image,
                variant=variant,
            )
    for method, route, body in OWNER_GIFT_ROUTES:
        rec.call(method, route, json=body, gift_id=gift)
    for variant in VARIANTS:
        rec.call("GET", IMAGE, image_id=image, variant=variant)


def edits(rec: Recorder, state: str, keep_holders: bool) -> None:
    """Every change the recipient can make short of deleting their gifts,
    occasions and list; the holders of the state's activity stay invitees
    when `keep_holders`."""
    rec.call("PATCH", "/api/lists/{list_id}", json={"title": "Big day"}, list_id="list")
    rec.register(
        "new list",
        rec.call(
            "POST", "/api/lists", json={"title": "Next", "recipient_kind": "self"}
        ),
    )
    rec.register(
        "G3",
        rec.call(
            "POST", "/api/lists/{list_id}/gifts", json={"title": "Lamp"}, list_id="list"
        ),
    )
    rec.register("up1", rec.call("POST", "/api/images", content=png()))
    rec.register(
        "up2",
        rec.call(
            "POST",
            "/api/images/from-url",
            json={"url": "https://shop.example.com/h.png"},
        ),
    )
    gift = "/api/gifts/{gift_id}"
    # A new currency on a gift with pledges included (D9).
    rec.twin(
        "PATCH",
        gift,
        {"gift_id": ("G1", "G2")},
        body=lambda _: {
            "title": "Wireless",
            "price_amount": 199,
            "price_currency": "USD",
        },
    )
    rec.twin(
        "PATCH",
        gift,
        {"gift_id": ("G1", "G2")},
        body=lambda side: {"image_id": rec.ids[("up1", "up2")[side]]},
    )
    # Received and put back, G1 as its twin: G1's claim is kept meanwhile
    # and comes back with it (hidden gifts plan D5). Keep is refused on a
    # gift on the list (D6).
    received = "/api/gifts/{gift_id}/received"
    rec.twin("POST", received, {"gift_id": ("G1", "G2")})
    detail = rec.call("GET", "/api/lists/{list_id}", list_id="list").json()
    assert [gift["id"] for gift in detail["gifts"]] == [rec.ids["G3"]]
    # Newest first.
    assert [gift["id"] for gift in detail["received"]] == [
        rec.ids["G2"],
        rec.ids["G1"],
    ]
    rec.twin("DELETE", received, {"gift_id": ("G1", "G2")})
    rec.twin("POST", "/api/gifts/{gift_id}/keep", {"gift_id": ("G1", "G2")})
    statuses = [answer.status for answer in rec.answers[-7:]]
    assert statuses == [204, 204, 200, 204, 204, 409, 409]
    rec.register(
        "E",
        rec.call(
            "POST",
            "/api/lists/{list_id}/occasions",
            json={"name": "Easter", "date": LATER},
            list_id="list",
        ),
    )
    occasion = "/api/occasions/{occasion_id}"
    rec.call("PATCH", occasion, json={"name": "Big birthday"}, occasion_id="A")
    rec.call("PATCH", occasion, json={"date": LATER}, occasion_id="B")
    # Back in the future: its unbought claims are live again (D8).
    rec.call("PATCH", occasion, json={"date": FUTURE}, occasion_id="P")
    rec.register(
        "token A again",
        rec.call("POST", "/api/occasions/{occasion_id}/link", occasion_id="A"),
        key="join_token",
    )
    rec.call("DELETE", "/api/occasions/{occasion_id}/link", occasion_id="B")
    who, where = holder(state)
    member = "/api/occasions/{occasion_id}/members/{user_id}"
    if keep_holders:
        # Not removed: the deletions meet their claim (review R7-1).
        kept = holders(state)
    else:
        # The invitee who holds the activity, against one who holds none
        # (D10).
        rec.twin(
            "DELETE", member, {"occasion_id": (where, "A"), "user_id": (who, "ben")}
        )
        kept = {who, "ben"}
    for occasion_name, (_, invitees) in OCCASIONS.items():
        for invitee in invitees:
            if invitee not in kept:
                rec.call("DELETE", member, occasion_id=occasion_name, user_id=invitee)
    rec.call(
        "DELETE",
        "/api/occasions/{occasion_id}/removals/{user_id}",
        occasion_id=where,
        user_id=who,
    )
    rec.call("DELETE", "/api/occasions/{occasion_id}/membership", occasion_id="A")


def deletions(rec: Recorder, ending: str, second_token: str) -> None:
    def gifts() -> None:
        rec.twin("DELETE", "/api/gifts/{gift_id}", {"gift_id": ("G1", "G2")})

    def occasions() -> None:
        for occasion in ("A", "B", "P", "E"):
            rec.call("DELETE", "/api/occasions/{occasion_id}", occasion_id=occasion)

    def whole() -> None:
        rec.call("DELETE", "/api/lists/{list_id}", list_id="list")

    steps = {
        "gifts first": (gifts, occasions, whole),
        "occasions first": (occasions, gifts, whole),
        "list first": (whole, gifts, occasions),
    }
    for step in steps[ending]:
        step()
    rec.call("DELETE", "/api/lists/{list_id}", list_id="new list")
    rec.call("GET", "/api/lists")
    rec.call(
        "POST",
        "/api/auth/sign-out",
        headers={"Authorization": f"Bearer {second_token}"},
    )
    rec.call("DELETE", "/api/me")


def second_session(engine, user_id: str) -> str:
    with Session(engine) as db, db.begin():
        return sessions.create(db, uuid.UUID(user_id), sessions.utc_now())


def differences(world: list[Answer], control: list[Answer], mapping) -> list[str]:
    """The calls whose answers differ, once the world's ids are renamed."""
    rename = renamer(mapping)
    assert [answer.call for answer in world] == [answer.call for answer in control]
    return [
        f"{ours.call}: {ours.renamed(rename)} != {theirs}"
        for ours, theirs in zip(world, control, strict=True)
        if ours.renamed(rename) != theirs
    ]


def walk(value: Any) -> Iterable[tuple[str | None, Any]]:
    """Every (key, value) pair of a JSON document, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield None, item
            yield from walk(item)


def assert_shows_no_activity(answers: Iterable[Answer]) -> None:
    for answer in answers:
        if not isinstance(answer.body, str) or not answer.body:
            continue
        keys = {key for key, _ in walk(json.loads(answer.body))}
        assert not keys & ACTIVITY_KEYS, answer.call
        if answer.route != MEMBERS:
            assert not [n for n in INVITEE_NAMES if n in answer.body], answer.call


def run(
    client,
    engine,
    built: World,
    actor: str,
    state: str,
    ending: str,
    unbought: int | None = None,
) -> Recorder:
    """The recipient's calls, in order. The co-owner keeps the holders of the
    state's activity in place (review R7-1); `unbought`, when given, is how
    many unbought claims G1, or the hidden gift, must still have when the
    deletions start."""
    rec = Recorder(client, built.accounts[actor].headers, built.ids)
    reads(rec, ("G1", "G2"), ("img1", "img2"))
    activity(rec)
    if state in HIDDEN_STATES:
        hidden_routes(rec, "H", "H image")
    edits(rec, state, keep_holders=actor == CO_OWNER)
    reads(rec, ("G1", "G2", "G3"), ("up1", "up2"))
    if unbought is not None:
        with engine.connect() as connection:
            assert unbought == connection.scalar(
                text(
                    "SELECT count(*) FROM gift_claims"
                    " WHERE gift_id = :gift AND bought_at IS NULL"
                ),
                {"gift": built.ids["H" if state in HIDDEN_STATES else "G1"]},
            )
    deletions(rec, ending, second_session(engine, built.ids[actor]))
    return rec


def answered(answer: Answer) -> tuple[int, tuple[tuple[str, str], ...], str | bytes]:
    return answer.status, answer.headers, answer.body


@pytest.mark.parametrize(("state", "actor", "ending"), [*RUNS, *HIDDEN_RUNS])
def test_the_recipient_sees_nothing(
    client, make_account, engine, url_fetcher, state, actor, ending
):
    url_fetcher.result = (png(), "image/png")
    control = build(client, make_account, engine, state, control=True)
    world = build(client, make_account, engine, state)
    meets_unbought = actor == CO_OWNER and state in UNBOUGHT
    theirs = run(client, engine, control, actor, state, ending)
    ours = run(
        client, engine, world, actor, state, ending, 1 if meets_unbought else None
    )

    # Whatever the activity, the same answers, from the first call of the
    # setup to the account's deletion.
    assert world.ids.keys() == control.ids.keys()
    mapping = {world.ids[name]: control.ids[name] for name in world.ids}
    assert differences(world.setup.answers, control.setup.answers, mapping) == []
    assert differences(ours.answers, theirs.answers, mapping) == []
    # G1 answered as its twin G2, the holder's removal as another's.
    for first, second, pairs in ours.twins:
        swap = renamer(swap_mapping(world.ids, [*TWINS, *pairs]))
        assert answered(first.renamed(swap)) == answered(second), first.call
    # Every activity route, on every occasion: what ids that exist nowhere
    # get (D4).
    refused = {
        answered(answer) for answer in ours.answers if answer.route in ACTIVITY_ROUTES
    }
    assert len(refused) == 1
    [(status, _, body)] = refused
    assert (status, json.loads(body)) == (404, {"detail": "Not found"})
    assert_shows_no_activity(
        [*world.setup.answers, *ours.answers, *control.setup.answers, *theirs.answers]
    )
    assert_claims_consistent(engine)


def test_the_recipients_deletions_meet_unbought_claims_in_every_ending():
    """Guard for review R7-1: the runs whose deletions meet an unbought
    claim on G1 (checked in the database before they start) end in every
    way."""
    assert {
        ending
        for state, actor, ending in RUNS
        if actor == CO_OWNER and state in UNBOUGHT
    } == set(ENDINGS)


def test_every_route_is_called(client, make_account, engine, url_fetcher):
    """The recipient's calls cover every route of the API, read from the
    OpenAPI document as `test_roles.py` does: a new route fails here until
    this module calls it."""
    url_fetcher.result = (png(), "image/png")
    world = build(client, make_account, engine, "reserved")

    rec = run(client, engine, world, OWNER, "reserved", ENDINGS[0])

    routes = {
        (method.upper(), path)
        for path, operations in client.app.openapi()["paths"].items()
        for method in operations
    }
    called = {(answer.method, answer.route) for answer in rec.answers}
    assert {"never called": routes - called, "no such route": called - routes} == {
        "never called": set(),
        "no such route": set(),
    }


# Activity no giver but its holder can see: none, or expired (D8, review R3-1);
# or a hidden gift deleted before anyone else saw it.
UNSEEN = {"none", "claim of the passed occasion, expired"} | HIDDEN_GONE


@pytest.mark.parametrize("state", [*STATES, *HIDDEN_STATES])
def test_a_giving_owner_sees_the_activity(client, make_account, engine, state):
    """The contrast: the owner of a list for someone else is a giver (D4).
    The same comparison finds the activity, through the claims route only,
    and the hidden-gift route for a hidden gift, whenever a giver who is not
    in it can see it. Were D4's check inverted,
    the recipient's comparisons would fail the same way."""
    control = build(client, make_account, engine, state, kind="other", control=True)
    world = build(client, make_account, engine, state, kind="other")
    recorders = []
    for built in (world, control):
        rec = Recorder(client, built.accounts[OWNER].headers, built.ids)
        reads(rec, ("G1", "G2"), ("img1", "img2"))
        if state in HIDDEN_STATES:
            for occasion in OCCASIONS:
                rec.call("GET", HIDDEN_GIFTS, occasion_id=occasion)
        for occasion in OCCASIONS:
            rec.call("GET", COMMENTS, occasion_id=occasion, gift_id="G1")
        recorders.append(rec)
    ours, theirs = recorders

    mapping = {world.ids[name]: control.ids[name] for name in world.ids}
    differing = {
        line.split(":")[0]
        for line in differences(ours.answers, theirs.answers, mapping)
    }
    claims = {f"GET {CLAIMS.format(occasion_id=name)}" for name in OCCASIONS}
    if state == "commented":
        # Through the thread alone: no claim is involved (comments plan D5).
        assert differing == {f"GET {COMMENTS.format(occasion_id='A', gift_id='G1')}"}
    elif state in STATES:
        assert differing <= claims
    else:
        # Through the hidden gift's occasion alone, its claim included (D7).
        home = HIDDEN_STATES[state][0][1]
        hidden = f"GET {HIDDEN_GIFTS.format(occasion_id=home)}"
        assert differing <= {f"GET {CLAIMS.format(occasion_id=home)}", hidden}
        assert (hidden in differing) == (state not in UNSEEN)
    assert bool(differing) == (state not in UNSEEN)
    assert [answer.status for answer in ours.answers if answer.route == CLAIMS] == [
        200,
        200,
        200,
        404,
    ]


# The hidden gifts of the reveal test, by the name of their ids: their author,
# occasion, title and claim, if any. Bought ones are revealed, by title (D6).
REVEAL = {
    "H1": ("ana", "A", "Zebra", "bought"),
    "H2": ("cleo", "B", "Apple", "bought"),
    "H3": ("ana", "A", "Yarn", "reservation"),
    "H4": ("ben", "A", "Xylophone", None),
}
REVEALED = ("H2", "H1")
UNREVEALED = ("H3", "H4")
GIFT_OUT_KEYS = {
    "id",
    "list_id",
    "title",
    "description",
    "links",
    "price_amount",
    "price_currency",
    "image",
}
# What the recipient can do with a revealed gift, without changing it: the
# only calls whose answers may differ from a random id's (D11).
ACTS_ON_REVEALED = {("PATCH", "/api/gifts/{gift_id}"), ("GET", IMAGE)}
DETAIL = "/api/lists/{list_id}"


def without_revealed(answer: Answer) -> Answer:
    """The list detail with its `revealed` left out, and what its length says."""
    if (answer.method, answer.route) != ("GET", DETAIL):
        return answer
    body = {k: v for k, v in json.loads(answer.body).items() if k != "revealed"}
    headers = tuple(h for h in answer.headers if h[0] != "content-length")
    return replace(answer, headers=headers, body=json.dumps(body))


def names_revealed(answer: Answer) -> bool:
    """Whether the answer is a call that acts on a revealed gift or its image."""
    names = {*REVEALED, *(f"{name} image" for name in REVEALED)}
    return (answer.method, answer.route) in ACTS_ON_REVEALED and bool(
        names & set(answer.call.split(" ", 1)[1].split("/"))
    )


def compared(answers: Iterable[Answer]) -> list[Answer]:
    """The answers that must match a world without hidden gifts, once revealed."""
    return [without_revealed(a) for a in answers if not names_revealed(a)]


def on_revealed(rec: Recorder) -> None:
    """The calls on the revealed gifts that leave them as they are: an empty
    edit, and both image routes on the occasions the gifts belong to."""
    for name in REVEALED:
        rec.call("PATCH", "/api/gifts/{gift_id}", json={}, gift_id=name)
        for variant in VARIANTS:
            rec.call("GET", IMAGE, image_id=f"{name} image", variant=variant)
            for occasion in ("A", "B"):
                rec.call(
                    "GET",
                    OCCASION_IMAGE,
                    occasion_id=occasion,
                    image_id=f"{name} image",
                    variant=variant,
                )


@pytest.mark.parametrize("actor", (OWNER, CO_OWNER))
def test_a_revealed_gift_shows_as_the_gift_alone(client, make_account, engine, actor):
    """The decided exception (D3, D6, D11): once an occasion has passed, its
    bought hidden gifts are in `ListDetail.revealed` as the gift alone, and
    every other answer is the control's."""
    control = build(
        client, make_account, engine, "none", control=True, when=SOON.isoformat()
    )
    world = build(client, make_account, engine, "none", when=SOON.isoformat())
    accounts = world.accounts
    for name, (author, occasion, title, claim) in REVEAL.items():
        add_hidden(client, world.ids, accounts[author], occasion, name, title)
        not_added(control.ids, name)
        if claim:
            done = client.post(
                f"/api/occasions/{world.ids[occasion]}/gifts/{world.ids[name]}/{claim}",
                headers=accounts[author].headers,
            )
            assert done.status_code == 200, done.text

    def recorders() -> tuple[Recorder, Recorder]:
        return (
            Recorder(client, world.accounts[actor].headers, world.ids),
            Recorder(client, control.accounts[actor].headers, control.ids),
        )

    mapping = {world.ids[name]: control.ids[name] for name in world.ids}
    every_hidden = [(name, f"{name} image") for name in REVEAL]
    occasion_path = "/api/occasions/{occasion_id}"
    gifts = ("G1", "G2")
    images = ("img1", "img2")
    assert differences(world.setup.answers, control.setup.answers, mapping) == []

    # Past the occasions: the bought ones are revealed, the others are not.
    client.app.state.clock = lambda: noon_after(SOON)
    ours, theirs = recorders()
    for rec, revealed in ((ours, REVEALED), (theirs, ())):
        reads(rec, gifts, images, revealed)
        for name in UNREVEALED:
            hidden_routes(rec, name, f"{name} image")
        on_revealed(rec)
    assert differences(compared(ours.answers), compared(theirs.answers), mapping) == []
    assert_shows_no_activity(ours.answers)
    shown = client.get(
        DETAIL.format(list_id=world.ids["list"]),
        headers=accounts[actor].headers,
    ).json()["revealed"]
    assert [gift["id"] for gift in shown] == [world.ids[name] for name in REVEALED]
    for gift, name in zip(shown, REVEALED, strict=True):
        assert set(gift) == GIFT_OUT_KEYS
        expected = GIFT | {"price_amount": "149.00", "title": REVEAL[name][2]}
        assert {key: gift[key] for key in expected} == expected
        assert gift["list_id"] == world.ids["list"]
        assert gift["image"]["id"] == world.ids[f"{name} image"]

    # Dates moved later: nothing is revealed, as if nothing was ever bought.
    ours, theirs = recorders()
    for rec in (ours, theirs):
        for occasion in ("A", "B"):
            changed = rec.call(
                "PATCH",
                occasion_path,
                json={"date": MOVED.isoformat()},
                occasion_id=occasion,
            )
            assert changed.status_code == 200, changed.text
        reads(rec, gifts, images)
        for name, image in every_hidden:
            hidden_routes(rec, name, image)
    assert differences(ours.answers, theirs.answers, mapping) == []
    assert_shows_no_activity(ours.answers)

    # Past them again, and an occasion deleted: its bought hidden gift stays
    # revealed, its others go (D9).
    client.app.state.clock = lambda: noon_after(MOVED)
    ours, theirs = recorders()
    for rec in (ours, theirs):
        deleted = rec.call("DELETE", occasion_path, occasion_id="A")
        assert deleted.status_code == 204, deleted.text
        rec.call("GET", DETAIL, list_id="list")
        for name in UNREVEALED:
            hidden_routes(rec, name, f"{name} image")
        on_revealed(rec)
    assert differences(compared(ours.answers), compared(theirs.answers), mapping) == []
    assert_shows_no_activity(ours.answers)
    detail = client.get(
        DETAIL.format(list_id=world.ids["list"]),
        headers=accounts[actor].headers,
    ).json()
    assert [gift["id"] for gift in detail["revealed"]] == [
        world.ids[name] for name in REVEALED
    ]

    # Review R1-1: marked received, it stays there whatever its occasion's
    # date becomes, and survives the occasion's deletion.
    ours, _ = recorders()
    marked = ours.call("POST", "/api/gifts/{gift_id}/received", gift_id="H2")
    assert marked.status_code == 204, marked.text
    moved = ours.call("PATCH", occasion_path, json={"date": LATER}, occasion_id="B")
    assert moved.status_code == 200, moved.text
    for deleting in (False, True):
        if deleting:
            gone = ours.call("DELETE", occasion_path, occasion_id="B")
            assert gone.status_code == 204, gone.text
        detail = ours.call("GET", DETAIL, list_id="list").json()
        assert [gift["id"] for gift in detail["received"]] == [world.ids["H2"]]
        assert [gift["id"] for gift in detail["revealed"]] == [world.ids["H1"]]
    assert_shows_no_activity(ours.answers)
    assert_claims_consistent(engine)
