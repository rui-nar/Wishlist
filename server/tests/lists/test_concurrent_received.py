"""Received and keep at the same moment as a giver's claim, a date change
or another keep (hidden gifts plan D10): the outcome is one of the serial
orders, never a 500, and the claims' invariants hold.

The world of `test_reservations.py`; hidden gifts and their claims are
written directly in the database, as in `test_hidden_model.py`.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial

import test_reservations
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text
from test_hidden_model import add_claim, add_hidden, claim_count, gift_row, noon_after
from test_received import detail, ids, keep, mark_received, put_back
from test_reservations import NOT_FOUND, claims, release, reserve, share

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

ROUNDS = 20


def statuses(*responses):
    return sorted(response.status_code for response in responses)


def test_received_racing_a_reservation(client, world, engine):
    gift = world.gifts[0]

    for _ in range(ROUNDS):
        received, reserved = together(
            partial(mark_received, client, world.owner, gift),
            partial(reserve, client, world.ana, world.first, gift),
        )

        assert received.status_code == 204, received.text
        # Made before the receipt, and kept; or after it, on a gift no
        # occasion shows.
        assert reserved.status_code in (200, 404), reserved.text
        made = reserved.status_code == 200
        assert claim_count(engine, gift) == (1 if made else 0)
        assert claims(client, world.ana, world.first).json()["gifts"] == []
        assert put_back(client, world.owner, gift).status_code == 204
        shown = claims(client, world.ana, world.first).json()["gifts"]
        assert [claim["gift_id"] for claim in shown] == ([gift] if made else [])
        if made:
            assert release(client, world.ana, world.first, gift).status_code == 204
    assert_claims_consistent(engine)


def revealed_in_new_occasion(client, world, engine, day):
    """A bought hidden gift in a new occasion dated `day`, whose reveal date
    has passed by the test's clock; returns the occasion and the gift."""
    occasion = share(client, world.owner, world.list_id, "Soon", on=day.isoformat())
    gift = add_hidden(engine, world, occasion, world.ana)
    add_claim(engine, gift, occasion, world.ben, bought=True)
    return occasion, gift


def test_keep_racing_a_date_moved_later(client, world, engine):
    day = date.today() + timedelta(days=2)
    later = (day + timedelta(days=30)).isoformat()
    client.app.state.clock = lambda: noon_after(day)

    for _ in range(ROUNDS):
        occasion, gift = revealed_in_new_occasion(client, world, engine, day)

        kept, moved = together(
            partial(keep, client, world.owner, gift),
            partial(
                client.patch,
                f"/api/occasions/{occasion}",
                json={"date": later},
                headers=world.owner.headers,
            ),
        )

        assert moved.status_code == 200, moved.text
        if kept.status_code == 200:
            # Kept first: on the list, the hidden row gone.
            assert kept.json()["id"] in ids(detail(client, world)["gifts"])
            assert gift_row(engine, gift) is None
        else:
            # Hidden again first: the random id's answer, nothing changed.
            assert (kept.status_code, kept.json()) == (404, NOT_FOUND), kept.text
            assert str(gift_row(engine, gift).hidden_occasion_id) == occasion
            assert claim_count(engine, gift) == 1
    assert_claims_consistent(engine)


def test_keep_waiting_on_a_date_moved_later_is_a_404(client, world, engine):
    # Deterministic: the date change is made here, as the endpoint makes it
    # (the occasion FOR NO KEY UPDATE), and held uncommitted; the keep waits
    # on the occasion, then finds the gift hidden again.
    day = date.today() + timedelta(days=2)
    client.app.state.clock = lambda: noon_after(day)
    occasion, gift = revealed_in_new_occasion(client, world, engine, day)
    with engine.connect() as moving:
        moving.execute(
            text(
                "UPDATE occasions SET latest_date = date, date = :later"
                " WHERE id = :occasion"
            ),
            {"later": day + timedelta(days=30), "occasion": occasion},
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            keeping = pool.submit(keep, client, world.owner, gift)
            wait_until_blocked_on_a_lock(engine)
            moving.commit()
            response = keeping.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert str(gift_row(engine, gift).hidden_occasion_id) == occasion
    assert ids(detail(client, world)["gifts"]) == world.gifts
    assert_claims_consistent(engine)


def test_two_keeps_at_once_one_keeps(client, world, engine):
    day = date.today() + timedelta(days=2)
    client.app.state.clock = lambda: noon_after(day)

    for _ in range(ROUNDS):
        _, gift = revealed_in_new_occasion(client, world, engine, day)

        results = together(
            partial(keep, client, world.owner, gift),
            partial(keep, client, world.owner, gift),
        )

        assert statuses(*results) == [200, 404], [r.text for r in results]
        refused = next(r for r in results if r.status_code == 404)
        assert refused.json() == NOT_FOUND
        kept = next(r for r in results if r.status_code == 200).json()["id"]
        assert ids(detail(client, world)["gifts"]).count(kept) == 1
        assert gift_row(engine, gift) is None
    # One kept gift per round.
    assert len(detail(client, world)["gifts"]) == len(world.gifts) + ROUNDS
    assert_claims_consistent(engine)
