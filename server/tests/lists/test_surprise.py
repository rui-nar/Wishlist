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
"""

import io
import json
import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import pytest
from claims_invariants import assert_claims_consistent
from PIL import Image
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.accounts import sessions
from app.media.images import VARIANTS

# Relative to today: a fixed date would turn into a passed occasion (D8).
FUTURE = (date.today() + timedelta(days=60)).isoformat()
LATER = (date.today() + timedelta(days=90)).isoformat()
# Passed for good.
PAST = "2001-01-01"

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
}

# The activity routes but the claims read, each with its body (D6).
ACTIVITY = [
    ("POST", "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation", None),
    ("DELETE", "/api/occasions/{occasion_id}/gifts/{gift_id}/reservation", None),
    ("POST", "/api/occasions/{occasion_id}/gifts/{gift_id}/bought", None),
    ("PUT", "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge", {"amount": "20.00"}),
    ("DELETE", "/api/occasions/{occasion_id}/gifts/{gift_id}/pledge", None),
]
CLAIMS = "/api/occasions/{occasion_id}/claims"
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
}

# The twins of a world, by the names of their ids: swapped, each answer about
# the first is the answer about the second.
TWINS = [("G1", "G2"), ("img1", "img2"), ("up1", "up2")]

# How each test ends: the deletion that reaches G1's activity first.
ENDINGS = ["gifts first", "occasions first", "list first"]
# Each state is run for the owner and for the co-owner, with the endings in
# turn, so that it meets two of the three: every combination would take
# minutes, at tens of milliseconds a request.
RUNS = [
    (state, actor, ENDINGS[(number + turn) % len(ENDINGS)])
    for number, state in enumerate(STATES)
    for turn, actor in enumerate((OWNER, CO_OWNER))
]


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
    """Who holds G1's activity in the state, and in which occasion; Ana, in A,
    when nobody, or nobody who is still an invitee, does."""
    for who, occasion, _, _ in STATES[state]:
        if occasion != "D":
            return who, occasion
    return "ana", "A"


def build(client, make_account, engine, state: str, kind: str = "self") -> World:
    owner = make_account(NAMES[OWNER])
    accounts = {OWNER: owner}
    ids = {
        OWNER: owner.id,
        "nowhere": str(uuid.uuid4()),
        "nowhere gift": str(uuid.uuid4()),
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
                json={"name": name, "date": FUTURE},
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

    for who, occasion, action, amount in STATES[state]:
        path = f"/api/occasions/{ids[occasion]}/gifts/{ids['G1']}/{action}"
        headers = accounts[who].headers
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
    if STATES[state]:
        who, occasion = holder(state)
        seen = client.get(
            f"/api/occasions/{ids[occasion]}/claims", headers=accounts[who].headers
        )
        assert ids["G1"] in [gift["gift_id"] for gift in seen.json()["gifts"]]
    return World(accounts=accounts, ids=ids, setup=setup)


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


def reads(rec: Recorder, gifts: tuple[str, ...], images: tuple[str, str]) -> None:
    """Everything the recipient can read, the claims included, with the
    gifts named in `gifts` and the twin images `images` on G1 and G2."""
    rec.call("GET", "/api/me")
    rec.call("GET", "/api/lists")
    detail = rec.call("GET", "/api/lists/{list_id}", list_id="list")
    assert_twin_gifts(rec, detail.json()["gifts"], gifts)
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
    """Every activity write on G1 in every occasion, and every activity route
    on ids that exist nowhere. `reads` reads each occasion's claims."""
    targets = [(occasion, "G1") for occasion in OCCASIONS]
    for occasion, gift in [*targets, ("nowhere", "nowhere gift")]:
        for method, route, body in ACTIVITY:
            rec.call(method, route, json=body, occasion_id=occasion, gift_id=gift)
    rec.call("GET", CLAIMS, occasion_id="nowhere")


def edits(rec: Recorder, state: str) -> None:
    """Every change the recipient can make short of deleting their gifts,
    occasions and list."""
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
    # The invitee who holds the activity, against one who holds none (D10).
    who, where = holder(state)
    member = "/api/occasions/{occasion_id}/members/{user_id}"
    rec.twin("DELETE", member, {"occasion_id": (where, "A"), "user_id": (who, "ben")})
    for occasion_name, (_, invitees) in OCCASIONS.items():
        for invitee in invitees:
            if invitee not in (who, "ben"):
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


def run(client, engine, built: World, actor: str, state: str, ending: str) -> Recorder:
    """The recipient's calls, in order."""
    rec = Recorder(client, built.accounts[actor].headers, built.ids)
    reads(rec, ("G1", "G2"), ("img1", "img2"))
    activity(rec)
    edits(rec, state)
    reads(rec, ("G1", "G2", "G3"), ("up1", "up2"))
    deletions(rec, ending, second_session(engine, built.ids[actor]))
    return rec


def answered(answer: Answer) -> tuple[int, tuple[tuple[str, str], ...], str | bytes]:
    return answer.status, answer.headers, answer.body


@pytest.mark.parametrize(("state", "actor", "ending"), RUNS)
def test_the_recipient_sees_nothing(
    client, make_account, engine, url_fetcher, state, actor, ending
):
    url_fetcher.result = (png(), "image/png")
    control = build(client, make_account, engine, "none")
    world = build(client, make_account, engine, state)
    theirs = run(client, engine, control, actor, state, ending)
    ours = run(client, engine, world, actor, state, ending)

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


# Activity no giver but its holder can see: none, or expired (D8, review R3-1).
UNSEEN = {"none", "claim of the passed occasion, expired"}


@pytest.mark.parametrize("state", STATES)
def test_a_giving_owner_sees_the_activity(client, make_account, engine, state):
    """The contrast: the owner of a list for someone else is a giver (D4).
    The same comparison finds the activity, through the claims route only,
    whenever a giver who is not in it can see it. Were D4's check inverted,
    the recipient's comparisons would fail the same way."""
    control = build(client, make_account, engine, "none", kind="other")
    world = build(client, make_account, engine, state, kind="other")
    recorders = []
    for built in (world, control):
        rec = Recorder(client, built.accounts[OWNER].headers, built.ids)
        reads(rec, ("G1", "G2"), ("img1", "img2"))
        recorders.append(rec)
    ours, theirs = recorders

    mapping = {world.ids[name]: control.ids[name] for name in world.ids}
    differing = {
        line.split(":")[0]
        for line in differences(ours.answers, theirs.answers, mapping)
    }
    claims = {f"GET {CLAIMS.format(occasion_id=name)}" for name in OCCASIONS}
    assert differing <= claims
    assert bool(differing) == (state not in UNSEEN)
    assert [answer.status for answer in ours.answers if answer.route == CLAIMS] == [
        200,
        200,
        200,
        404,
    ]
