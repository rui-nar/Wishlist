"""The previous release keeps working on this schema, for an image-only
rollback (comments plan, Boundaries crossed; DevOps plan D15; review R1-1).

It deletes a gift with its row alone, no foreign key cascading its claim any
more: an orphaned claim it cannot see. Then it deletes the list or the account,
through `delete_gift_claims` and the cascades, whose occasions' `SET NULL` must
meet no check constraint. Its `drop_gift_activity` deleted the claims: put back
here for the paths that call it. The world of `test_reservations.py`.
"""

import pytest
import test_reservations
from claims_invariants import assert_claims_consistent
from sqlalchemy import delete, text
from test_reservations import claims, reserve

from app.reserving.models import GiftClaim

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world


@pytest.fixture(autouse=True)
def previous_hook(monkeypatch):
    def old_body(db, gift_ids):
        if gift_ids:
            db.execute(delete(GiftClaim).where(GiftClaim.gift_id.in_(gift_ids)))

    monkeypatch.setattr("app.lists.router.drop_gift_activity", old_body)
    monkeypatch.setattr("app.hidden_gifts.lifecycle.drop_gift_activity", old_body)


def delete_row(engine, gift):
    """As the previous release deletes a gift on this schema."""
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM gifts WHERE id = :gift"), {"gift": gift})


@pytest.fixture
def orphan(client, world, engine):
    """An unbought reservation whose gift row is gone."""
    gift = world.gifts[0]
    reserve(client, world.ana, world.first, gift)
    delete_row(engine, gift)
    return gift


def test_the_list_deleted_with_an_orphaned_unbought_claim(
    client, world, engine, rows, orphan
):
    response = client.delete(f"/api/lists/{world.list_id}", headers=world.owner.headers)

    assert response.status_code == 204, response.text
    assert rows("gift_claims", "gift_id", orphan) == 1
    assert_claims_consistent(engine)


def test_the_owners_account_deleted_with_an_orphaned_unbought_claim(
    client, world, engine, rows, orphan
):
    response = client.delete("/api/me", headers=world.owner.headers)

    assert response.status_code == 204, response.text
    assert rows("gift_claims", "gift_id", orphan) == 1
    assert_claims_consistent(engine)


def test_a_participants_account_deleted_with_an_orphaned_unbought_claim(
    client, world, engine, rows, orphan
):
    response = client.delete("/api/me", headers=world.ana.headers)

    assert response.status_code == 204, response.text
    assert rows("gift_claims", "gift_id", orphan) == 0
    assert_claims_consistent(engine)


def test_the_occasion_deleted_with_an_orphaned_unbought_claim(
    client, world, engine, rows, orphan
):
    response = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )

    assert response.status_code == 204, response.text
    assert rows("gift_claims", "gift_id", orphan) == 0
    assert_claims_consistent(engine)


def test_the_claims_read_never_shows_the_orphan(client, world, engine, orphan):
    live = world.gifts[1]
    reserve(client, world.ana, world.first, live)

    shown = claims(client, world.ana, world.first).json()["gifts"]

    assert [claim["gift_id"] for claim in shown] == [live]
    assert_claims_consistent(engine)
