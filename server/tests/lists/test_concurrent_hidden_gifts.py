"""Hidden gifts at the same moment as a purchase, a reservation, the
occasion's deletion or their author's removal (hidden gifts plan D10): the
outcome is one of the serial orders, never a 500, and the claims' invariants
hold.

The world of `test_reservations.py`.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial

import test_reservations
from claims_invariants import assert_claims_consistent
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text
from test_hidden_gifts import add, added, edit, remove, titles
from test_hidden_model import claim_count, gift_row
from test_reservations import BOUGHT, NOT_FOUND, mark_bought, reserve, share

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

ROUNDS = 20


def test_an_edit_racing_mark_bought(client, world, engine):
    for _ in range(ROUNDS):
        gift = added(client, world.ana, world.first, "Before")

        edited, bought = together(
            partial(edit, client, world.ana, world.first, gift, title="After"),
            partial(mark_bought, client, world.ben, world.first, gift),
        )

        assert bought.status_code == 200, bought.text
        # The edit landed before the purchase, or was refused after it:
        # never written on a gift already bought.
        if edited.status_code == 200:
            assert gift_row(engine, gift).title == "After"
        else:
            assert (edited.status_code, edited.json()) == (409, BOUGHT)
            assert gift_row(engine, gift).title == "Before"
    assert_claims_consistent(engine)


def test_a_delete_racing_a_reservation(client, world, engine):
    for _ in range(ROUNDS):
        gift = added(client, world.ana, world.first)

        deleted, reserved = together(
            partial(remove, client, world.ana, world.first, gift),
            partial(reserve, client, world.ben, world.first, gift),
        )

        # Deleted first and the reservation finds nothing, or reserved first
        # and deleted with its claim.
        assert deleted.status_code == 204, deleted.text
        assert reserved.status_code in (200, 404), reserved.text
        assert gift_row(engine, gift) is None
        assert claim_count(engine, gift) == 0
    assert titles(client, world.ben, world.first) == []
    assert_claims_consistent(engine)


def new_occasion(client, world):
    """An occasion with Ana in it; returns its id."""
    return share(client, world.owner, world.list_id, "Round", world.ana)


def test_an_add_racing_the_occasions_deletion(client, world, rows, engine):
    for _ in range(ROUNDS):
        occasion = new_occasion(client, world)

        response, deleted = together(
            partial(add, client, world.ana, occasion),
            partial(
                client.delete,
                f"/api/occasions/{occasion}",
                headers=world.owner.headers,
            ),
        )

        assert deleted.status_code == 204, deleted.text
        # Before the reveal date: added and settled with it (D9), or refused.
        assert response.status_code in (201, 404), response.text
        assert rows("gifts", "hidden_occasion_id", occasion) == 0
    assert rows("gifts") == len(world.gifts)
    assert_claims_consistent(engine)


def test_an_add_waiting_on_the_occasions_deletion_is_a_404(client, world, rows, engine):
    # Deterministic: the deletion is made here, as the endpoint makes it (the
    # occasion FOR UPDATE), and held uncommitted; the add waits on the
    # occasion, then finds it gone.
    occasion = new_occasion(client, world)
    values = {"occasion": occasion}
    with engine.connect() as deleting:
        deleting.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            adding = pool.submit(add, client, world.ana, occasion)
            wait_until_blocked_on_a_lock(engine)
            deleting.execute(text("DELETE FROM occasions WHERE id = :occasion"), values)
            deleting.commit()
            response = adding.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert rows("gifts") == len(world.gifts)
    assert_claims_consistent(engine)


def test_a_deletion_waiting_on_an_add_settles_the_new_gift(client, world, rows, engine):
    # Deterministic: the add is made here, as the endpoint makes it (the
    # occasion FOR SHARE, then the insert), and held uncommitted; the
    # deletion waits on the occasion, then settles the new gift (D9).
    occasion = new_occasion(client, world)
    values = {"occasion": occasion, "list": world.list_id, "author": world.ana.id}
    with engine.connect() as adding:
        adding.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"), values
        )
        adding.execute(
            text(
                "INSERT INTO gifts (id, for_list_id, hidden_occasion_id, hidden_by,"
                " title, description, links)"
                " VALUES (gen_random_uuid(), :list, :occasion, :author, 'Drone', '',"
                " '{}')"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            deleting = pool.submit(
                client.delete,
                f"/api/occasions/{occasion}",
                headers=world.owner.headers,
            )
            wait_until_blocked_on_a_lock(engine)
            adding.commit()
            response = deleting.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == 204, response.text
    assert rows("gifts", "hidden_occasion_id", occasion) == 0
    assert rows("gifts") == len(world.gifts)
    assert_claims_consistent(engine)


def test_an_add_racing_the_authors_removal(client, world, rows, engine):
    for _ in range(ROUNDS):
        occasion = new_occasion(client, world)

        response, removed = together(
            partial(add, client, world.ana, occasion),
            partial(
                client.delete,
                f"/api/occasions/{occasion}/members/{world.ana.id}",
                headers=world.owner.headers,
            ),
        )

        assert removed.status_code == 204, removed.text
        # Refused, or committed and deleted by the removal: never a hidden
        # gift left by a removed author with nobody's purchase.
        assert response.status_code in (201, 404), response.text
        assert rows("gifts", "hidden_occasion_id", occasion) == 0
    assert_claims_consistent(engine)
