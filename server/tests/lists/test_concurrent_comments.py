"""Commenting at the same moment as the author's removal, the gift's deletion
or their own edit (comments plan D7): the outcome is one of the serial
orders, never a 500. A comment waits on an owner's write through the locks of
`giving_gift`, and a read waits on nothing (D6).
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from functools import partial

import pytest
from locks import TIMEOUT_SECONDS, together, wait_until_blocked_on_a_lock
from sqlalchemy import text
from test_comments import edit, path, post, posted, thread

ROUNDS = 20
FUTURE = (date.today() + timedelta(days=60)).isoformat()


@pytest.fixture
def owner(make_account):
    return make_account("Olga")


@pytest.fixture
def list_id(client, owner):
    return client.post(
        "/api/lists",
        json={"title": "Birthday", "recipient_kind": "self"},
        headers=owner.headers,
    ).json()["id"]


def add_gift(client, owner, list_id):
    return client.post(
        f"/api/lists/{list_id}/gifts", json={"title": "Bike"}, headers=owner.headers
    ).json()["id"]


def share(client, owner, list_id):
    occasion = client.post(
        f"/api/lists/{list_id}/occasions",
        json={"name": "Christmas", "date": FUTURE},
        headers=owner.headers,
    ).json()["id"]
    token = client.post(
        f"/api/occasions/{occasion}/link", headers=owner.headers
    ).json()["join_token"]
    return occasion, token


def join(client, account, token):
    joined = client.post("/api/join", json={"token": token}, headers=account.headers)
    assert joined.status_code == 200, joined.text


def remove(client, owner, occasion, account):
    return client.delete(
        f"/api/occasions/{occasion}/members/{account.id}", headers=owner.headers
    )


def test_a_comment_racing_its_authors_removal(
    client, make_account, owner, list_id, rows
):
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)

    for round_ in range(ROUNDS):
        ana = make_account(f"Ana {round_}")
        join(client, ana, token)

        commented, removed = together(
            partial(post, client, ana, occasion, gift),
            partial(remove, client, owner, occasion, ana),
        )

        assert commented.status_code in (201, 404), commented.text
        assert removed.status_code == 204, removed.text
        # Committed before the removal: it keeps their name (D7).
        if commented.status_code == 201:
            assert commented.json()["author_name"] == f"Ana {round_}"
    assert rows("comments") <= ROUNDS


def test_a_comment_racing_the_gifts_deletion(client, make_account, owner, list_id):
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)

    for _ in range(ROUNDS):
        gift = add_gift(client, owner, list_id)

        commented, deleted = together(
            partial(post, client, ana, occasion, gift),
            partial(client.delete, f"/api/gifts/{gift}", headers=owner.headers),
        )

        assert commented.status_code in (201, 404), commented.text
        assert deleted.status_code == 204, deleted.text
        # Either way the thread is out of reach now.
        assert client.get(path(occasion, gift), headers=ana.headers).status_code == 404


@pytest.mark.parametrize("outcome, status", [("commit", 404), ("rollback", 201)])
def test_a_comment_waiting_on_its_authors_removal_follows_its_outcome(
    client, make_account, owner, list_id, engine, rows, outcome, status
):
    # Deterministic: the removal is made here as the endpoint makes it (the
    # occasion FOR UPDATE) and held uncommitted; the comment waits on the
    # occasion, then finds them no longer a member, or still one.
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    values = {"occasion": occasion, "user": ana.id}
    with engine.connect() as removal:
        removal.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        removal.execute(
            text(
                "DELETE FROM occasion_members"
                " WHERE occasion_id = :occasion AND user_id = :user"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            commenting = pool.submit(post, client, ana, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            getattr(removal, outcome)()
            response = commenting.result(timeout=TIMEOUT_SECONDS)

    assert response.status_code == status, response.text
    if status == 404:
        assert response.json() == {"detail": "Not found"}
    assert rows("comments") == (status == 201)


def test_a_comment_waiting_on_the_gifts_deletion_is_a_404(
    client, make_account, owner, list_id, engine, rows
):
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    with engine.connect() as deletion:
        deletion.execute(text("DELETE FROM gifts WHERE id = :gift"), {"gift": gift})
        with ThreadPoolExecutor(max_workers=1) as pool:
            commenting = pool.submit(post, client, ana, occasion, gift)
            wait_until_blocked_on_a_lock(engine)
            deletion.commit()
            response = commenting.result(timeout=TIMEOUT_SECONDS)

    assert (response.status_code, response.json()) == (404, {"detail": "Not found"})
    assert rows("comments") == 0


def test_editing_and_deleting_a_comment_at_once_take_turns(
    client, make_account, owner, list_id, rows
):
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)

    for _ in range(ROUNDS):
        comment = posted(client, ana, occasion, gift)

        edited, deleted = together(
            partial(edit, client, ana, occasion, gift, comment["id"]),
            partial(
                client.delete,
                path(occasion, gift, comment["id"]),
                headers=ana.headers,
            ),
        )

        # Whichever came first, the comment ends up deleted; the edit found
        # it, or found nothing.
        assert edited.status_code in (200, 404), edited.text
        assert deleted.status_code == 204, deleted.text
        assert rows("comments") == 0


def test_a_comment_in_progress_does_not_block_an_owners_edit(
    client, make_account, owner, list_id, engine
):
    # The gift is only locked FOR KEY SHARE (D7): an edit of it does not wait
    # for a comment that has not committed.
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    values = {"occasion": occasion, "gift": gift, "author": ana.id}
    with engine.connect() as commenting:
        commenting.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR SHARE"), values
        )
        commenting.execute(
            text("SELECT list_id FROM gifts WHERE id = :gift FOR KEY SHARE"), values
        )
        commenting.execute(
            text(
                "INSERT INTO comments (id, occasion_id, gift_id, author_id, body)"
                " VALUES (gen_random_uuid(), :occasion, :gift, :author, 'Hi')"
            ),
            values,
        )
        with ThreadPoolExecutor(max_workers=1) as pool:
            editing = pool.submit(
                client.patch,
                f"/api/gifts/{gift}",
                json={"title": "Red bike"},
                headers=owner.headers,
            )
            edited = editing.result(timeout=TIMEOUT_SECONDS)
        commenting.rollback()

    assert edited.status_code == 200, edited.text


def test_reading_a_thread_waits_on_nothing(
    client, make_account, owner, list_id, engine
):
    # Neither the occasion nor the gift is locked for a read (D6): a thread
    # is read while an owner's change holds both.
    gift = add_gift(client, owner, list_id)
    occasion, token = share(client, owner, list_id)
    ana = make_account("Ana")
    join(client, ana, token)
    comment = posted(client, ana, occasion, gift)
    values = {"occasion": occasion, "gift": gift}
    with engine.connect() as held:
        held.execute(
            text("SELECT id FROM occasions WHERE id = :occasion FOR UPDATE"), values
        )
        held.execute(text("SELECT id FROM gifts WHERE id = :gift FOR UPDATE"), values)
        with ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(thread, client, ana, occasion, gift)
            seen = reading.result(timeout=TIMEOUT_SECONDS)
        held.rollback()

    assert seen["comments"] == [comment]
