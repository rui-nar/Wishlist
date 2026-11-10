"""The free plan's limits under concurrency (premium plan D8).

Two requests at one place left take turns and one gets it. No owner's add,
creation or put back waits on a giver's open transaction, and none queues
behind a keep that waits on a giver: only keep's own wait on its revealed
gift is accepted (Review envelope).

The world of `test_reservations.py`; hidden gifts and their claims are written
directly in the database, as in `test_hidden_model.py`.
"""

import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from functools import partial

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text
from test_concurrent_received import revealed_in_new_occasion, statuses
from test_hidden_model import gift_row, noon_after
from test_owner_work import enforce
from test_plan_limits import lists_of, new_gift, new_list, refusal
from test_received import detail, gift_count, ids, keep, mark_received, put_back

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

ROUNDS = 20


def add(client, world):
    return new_gift(client, world.owner, world.list_id)


def test_adds_at_one_place_left_one_takes_it(client, world, billing_on):
    enforce(client, billing_on, free_max_gifts_per_list=4)

    for _ in range(ROUNDS):
        results = together(partial(add, client, world), partial(add, client, world))

        assert statuses(*results) == [201, 402], [r.text for r in results]
        refused = next(r for r in results if r.status_code == 402)
        assert refused.json() == refusal("gifts", 4)
        assert gift_count(client, world) == 4
        created = next(r for r in results if r.status_code == 201).json()["id"]
        client.delete(f"/api/gifts/{created}", headers=world.owner.headers)


def test_two_creations_at_one_place_left_one_takes_it(client, make_account, billing_on):
    enforce(client, billing_on, free_max_lists=1)
    ada = make_account()

    for _ in range(ROUNDS):
        results = together(
            partial(new_list, client, ada), partial(new_list, client, ada)
        )

        assert statuses(*results) == [201, 402], [r.text for r in results]
        assert len(lists_of(client, ada)) == 1
        created = next(r for r in results if r.status_code == 201).json()["id"]
        client.delete(f"/api/lists/{created}", headers=ada.headers)


def test_keep_racing_an_add_for_the_last_place(client, world, billing_on, engine):
    day = date.today() + timedelta(days=2)
    client.app.state.clock = lambda: noon_after(day)
    enforce(client, billing_on, free_max_gifts_per_list=4)

    for _ in range(ROUNDS):
        _, gift = revealed_in_new_occasion(client, world, engine, day)

        kept, added = together(
            partial(keep, client, world.owner, gift), partial(add, client, world)
        )

        assert sorted((kept.status_code, added.status_code)) in (
            [200, 402],
            [201, 402],
        ), (kept.text, added.text)
        assert gift_count(client, world) == 4
        if kept.status_code == 200:
            assert gift_row(engine, gift) is None
            placed = kept.json()["id"]
        else:
            # Refused: still revealed, nothing lost.
            assert gift in ids(detail(client, world)["revealed"])
            placed = added.json()["id"]
            client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)
        client.delete(f"/api/gifts/{placed}", headers=world.owner.headers)
    assert_claims_consistent(engine)


def test_put_back_racing_an_add_for_the_last_place(client, world, billing_on):
    gift = world.gifts[0]
    assert mark_received(client, world.owner, gift).status_code == 204
    enforce(client, billing_on, free_max_gifts_per_list=3)

    for _ in range(ROUNDS):
        back, added = together(
            partial(put_back, client, world.owner, gift),
            partial(add, client, world),
        )

        assert sorted((back.status_code, added.status_code)) in (
            [204, 402],
            [201, 402],
        ), (back.text, added.text)
        assert gift_count(client, world) == 3
        if back.status_code == 204:
            assert gift in ids(detail(client, world)["gifts"])
            assert mark_received(client, world.owner, gift).status_code == 204
        else:
            assert gift in ids(detail(client, world)["received"])
            client.delete(
                f"/api/gifts/{added.json()['id']}", headers=world.owner.headers
            )


def test_two_put_backs_of_one_gift_do_not_refuse_each_other(client, world, billing_on):
    # One place left, and the gift takes it: the repeat finds it on the list,
    # a no-op, never a 402.
    gift = world.gifts[0]
    enforce(client, billing_on, free_max_gifts_per_list=3)

    for _ in range(ROUNDS):
        assert mark_received(client, world.owner, gift).status_code == 204

        results = together(
            partial(put_back, client, world.owner, gift),
            partial(put_back, client, world.owner, gift),
        )

        assert statuses(*results) == [204, 204], [r.text for r in results]
        assert gift_count(client, world) == 3


@contextmanager
def a_givers_open_transaction(engine, world) -> Iterator[None]:
    """What a giver's requests hold until they commit, held open: the occasion
    `FOR SHARE`, a hidden gift inserted, a gift `FOR KEY SHARE` with a claim
    on it, and the same `FOR KEY SHARE` on the gift being put back."""
    with engine.connect() as giving:
        giving.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"),
            {"occasion": world.first},
        )
        giving.execute(
            text(
                "INSERT INTO gifts (id, for_list_id, hidden_occasion_id, hidden_by,"
                " title, description, links, price_amount, price_currency)"
                " VALUES (:id, :list, :occasion, :author, 'Hidden', '', '{}',"
                " 100, 'EUR')"
            ),
            {
                "id": uuid.uuid4(),
                "list": world.list_id,
                "occasion": world.first,
                "author": world.ana.id,
            },
        )
        giving.execute(
            text("SELECT id FROM gifts WHERE id = ANY(:gifts) FOR KEY SHARE"),
            {"gifts": [uuid.UUID(gift) for gift in world.gifts]},
        )
        giving.execute(
            text(
                "INSERT INTO gift_claims (gift_id, occasion_id, kind)"
                " VALUES (:gift, :occasion, 'reservation')"
            ),
            {"gift": world.gifts[1], "occasion": world.first},
        )
        giving.execute(
            text(
                "INSERT INTO claim_participants (gift_id, user_id)"
                " VALUES (:gift, :user)"
            ),
            {"gift": world.gifts[1], "user": world.ana.id},
        )
        yield
        giving.rollback()


@pytest.mark.parametrize("path", ["add", "create", "put back"])
def test_a_givers_open_transaction_does_not_delay_the_owner(
    client, world, billing_on, engine, path
):
    gift = world.gifts[0]
    assert mark_received(client, world.owner, gift).status_code == 204
    enforce(client, billing_on, free_max_gifts_per_list=4, free_max_lists=2)
    calls = {
        "add": (partial(add, client, world), 201),
        "create": (partial(new_list, client, world.owner), 201),
        "put back": (partial(put_back, client, world.owner, gift), 204),
    }
    call, expected = calls[path]

    # The transaction ends first on a failure: the pool waits for the request.
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        a_givers_open_transaction(engine, world),
    ):
        response = pool.submit(call).result(timeout=TIMEOUT_SECONDS)

        assert response.status_code == expected, response.text


def test_an_add_does_not_queue_behind_a_keep_waiting_on_a_giver(
    client, world, billing_on, engine
):
    day = date.today() + timedelta(days=2)
    client.app.state.clock = lambda: noon_after(day)
    _, gift = revealed_in_new_occasion(client, world, engine, day)
    enforce(client, billing_on, free_max_gifts_per_list=4)

    with (
        ThreadPoolExecutor(max_workers=2) as pool,
        engine.connect() as giving,
    ):
        giving.execute(
            text("SELECT id FROM gifts WHERE id = :gift FOR KEY SHARE"),
            {"gift": gift},
        )
        keeping = pool.submit(keep, client, world.owner, gift)
        wait_until_blocked_on_a_lock(engine)

        added = pool.submit(add, client, world).result(timeout=TIMEOUT_SECONDS)

        assert added.status_code == 201, added.text
        giving.commit()
        kept = keeping.result(timeout=TIMEOUT_SECONDS)

    # The last place went to the add; the keep, once the giver committed, finds
    # the list full and leaves the gift revealed.
    assert (kept.status_code, kept.json()) == (402, refusal("gifts", 4))
    assert gift_count(client, world) == 4
    assert gift in ids(detail(client, world)["revealed"])
    assert_claims_consistent(engine)
