"""A thread under a gift in one occasion (comments plan D1 to D3, D5, D8).

The world of `test_reservations.py`: one list whose gifts cost 100 EUR, Ana
and Ben invitees of its first occasion, Cleo of its second. What the
recipient gets is also in `test_roles.py` and `test_surprise.py`.
"""

import uuid

import pytest
import test_reservations
from test_hidden_model import add_hidden, gift_row
from test_received import keep, mark_received, put_back, revealed_gift
from test_reservations import NOT_FOUND, PAST, move
from test_roles import walk

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world

COMMENT_KEYS = {"id", "author_name", "mine", "body", "created_at", "edited"}


def path(occasion, gift, comment=None):
    base = f"/api/occasions/{occasion}/gifts/{gift}/comments"
    return base if comment is None else f"{base}/{comment}"


def thread(client, account, occasion, gift):
    response = client.get(path(occasion, gift), headers=account.headers)
    assert response.status_code == 200, response.text
    return response.json()


def post(client, account, occasion, gift, body="Hello"):
    return client.post(
        path(occasion, gift), json={"body": body}, headers=account.headers
    )


def posted(client, account, occasion, gift, body="Hello"):
    response = post(client, account, occasion, gift, body)
    assert response.status_code == 201, response.text
    return response.json()


def edit(client, account, occasion, gift, comment, body="Edited"):
    return client.patch(
        path(occasion, gift, comment), json={"body": body}, headers=account.headers
    )


def delete(client, account, occasion, gift, comment):
    return client.delete(path(occasion, gift, comment), headers=account.headers)


def thread_routes(client, account, occasion, gift, comment):
    """The status of every route of the thread, as `account`, with `comment`
    named on the routes that take one; the writes aim at something that
    would otherwise succeed."""
    return [
        client.get(path(occasion, gift), headers=account.headers).status_code,
        post(client, account, occasion, gift).status_code,
        edit(client, account, occasion, gift, comment).status_code,
        delete(client, account, occasion, gift, comment).status_code,
        client.put(
            f"/api/occasions/{occasion}/gifts/{gift}/follow", headers=account.headers
        ).status_code,
        client.delete(
            f"/api/occasions/{occasion}/gifts/{gift}/follow", headers=account.headers
        ).status_code,
    ]


NOT_FOUND_EVERYWHERE = [404] * 6


# Reading and posting


def test_a_new_thread_is_empty_and_not_followed(client, world):
    assert thread(client, world.ana, world.first, world.gifts[0]) == {
        "following": False,
        "comments": [],
    }


def test_posting_and_reading(client, world):
    gift = world.gifts[0]

    first = posted(client, world.ana, world.first, gift, "I'll take the blue one")
    second = posted(client, world.ben, world.first, gift, "Fine by me")

    assert set(first) == COMMENT_KEYS
    assert (first["author_name"], first["mine"], first["body"], first["edited"]) == (
        "Ana",
        True,
        "I'll take the blue one",
        False,
    )
    seen = thread(client, world.ana, world.first, gift)
    assert seen["comments"] == [first, second | {"mine": False}]
    # Oldest first, the caller's own marked for each reader.
    assert [
        c["mine"] for c in thread(client, world.ben, world.first, gift)["comments"]
    ] == [
        False,
        True,
    ]


def test_threads_are_per_gift_and_occasion(client, world):
    posted(client, world.ana, world.first, world.gifts[0], "On the first gift")

    assert thread(client, world.ana, world.first, world.gifts[1])["comments"] == []
    assert thread(client, world.cleo, world.second, world.gifts[0])["comments"] == []


def test_a_comment_is_trimmed_and_keeps_its_lines(client, world):
    gift = world.gifts[0]

    comment = posted(client, world.ana, world.first, gift, "  one\n\ttwo  \n")

    assert comment["body"] == "one\n\ttwo"


def test_no_user_id_in_any_response(client, world):
    gift = world.gifts[0]
    created = posted(client, world.ana, world.first, gift)
    ids = {world.ana.id, world.ben.id, world.owner.id}

    answers = [
        created,
        edit(client, world.ana, world.first, gift, created["id"]).json(),
        thread(client, world.ben, world.first, gift),
    ]

    for key, value in walk(answers):
        assert key not in ("author_id", "user_id")
        if isinstance(value, str):
            assert not any(user_id in value for user_id in ids)


# What a comment is (D2)


def test_2000_code_points_are_accepted_emoji_counted_as_one(client, world):
    gift = world.gifts[0]

    assert post(client, world.ana, world.first, gift, "a" * 2000).status_code == 201
    emoji = post(client, world.ana, world.first, gift, "🎁" * 2000)
    assert emoji.status_code == 201, emoji.text
    assert len(emoji.json()["body"]) == 2000


def test_2001_code_points_are_refused(client, world, rows):
    gift = world.gifts[0]

    for body in ("a" * 2001, "🎁" * 2001):
        assert post(client, world.ana, world.first, gift, body).status_code == 422
    assert rows("comments") == 0


def test_the_limit_is_counted_after_trimming(client, world):
    comment = post(
        client, world.ana, world.first, world.gifts[0], " " + "a" * 2000 + " "
    )

    assert comment.status_code == 201, comment.text


@pytest.mark.parametrize(
    "body",
    ["", "   ", " \n\t ", " ", "with\x00nul", "with\x01control", "bell\x07", "cr\r\n"],
)
def test_empty_whitespace_and_control_characters_are_refused(client, world, rows, body):
    gift = world.gifts[0]
    existing = posted(client, world.ana, world.first, gift)["id"]

    assert post(client, world.ana, world.first, gift, body).status_code == 422
    response = edit(client, world.ana, world.first, gift, existing, body)
    assert response.status_code == 422
    assert rows("comments") == 1
    assert (
        thread(client, world.ana, world.first, gift)["comments"][0]["body"] == "Hello"
    )


def test_a_lone_surrogate_is_refused_not_a_500(client, world):
    response = client.post(
        path(world.first, world.gifts[0]),
        content=b'{"body": "\\ud800"}',
        headers=world.ana.headers | {"content-type": "application/json"},
    )

    assert response.status_code == 422, response.text


def test_a_refused_comment_is_not_quoted_back(client, world):
    response = post(client, world.ana, world.first, world.gifts[0], "secret\x00text")

    assert response.status_code == 422
    assert "secret" not in response.text


@pytest.mark.parametrize("extra", [{"author_id": "x"}, {"created_at": "2026-01-01"}])
def test_an_extra_field_is_refused(client, world, rows, extra):
    gift = world.gifts[0]
    body = {"body": "Hello"} | extra
    existing = posted(client, world.ana, world.first, gift)["id"]

    assert (
        client.post(
            path(world.first, gift), json=body, headers=world.ana.headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            path(world.first, gift, existing), json=body, headers=world.ana.headers
        ).status_code
        == 422
    )
    assert rows("comments") == 1


# Editing and deleting


def test_the_author_edits(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    edited = edit(client, world.ana, world.first, gift, comment["id"], "  Better  ")

    assert edited.status_code == 200, edited.text
    assert edited.json() == comment | {"body": "Better", "edited": True}
    assert thread(client, world.ben, world.first, gift)["comments"] == [
        comment | {"body": "Better", "edited": True, "mine": False}
    ]


def test_the_author_deletes_and_it_is_gone(client, world):
    gift = world.gifts[0]
    kept = posted(client, world.ana, world.first, gift, "Kept")
    gone = posted(client, world.ana, world.first, gift, "Gone")

    response = delete(client, world.ana, world.first, gift, gone["id"])

    assert response.status_code == 204, response.text
    assert thread(client, world.ana, world.first, gift)["comments"] == [kept]
    # Gone means gone: a second delete and an edit find nothing.
    assert delete(client, world.ana, world.first, gift, gone["id"]).status_code == 404
    assert edit(client, world.ana, world.first, gift, gone["id"]).status_code == 404


def test_someone_elses_comment_cannot_be_edited_or_deleted(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    for response in (
        edit(client, world.ben, world.first, gift, comment["id"]),
        delete(client, world.ben, world.first, gift, comment["id"]),
    ):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert thread(client, world.ana, world.first, gift)["comments"] == [comment]


def test_a_comment_of_another_thread_is_not_found(client, world):
    gift, other = world.gifts[0], world.gifts[1]
    comment = posted(client, world.ana, world.first, gift)

    # Another gift of the same occasion.
    for response in (
        edit(client, world.ana, world.first, other, comment["id"]),
        delete(client, world.ana, world.first, other, comment["id"]),
    ):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    # Another occasion: even its author, once a giver of both.
    token = client.post(
        f"/api/occasions/{world.second}/link", headers=world.owner.headers
    ).json()["join_token"]
    assert (
        client.post(
            "/api/join", json={"token": token}, headers=world.ana.headers
        ).status_code
        == 200
    )
    for response in (
        edit(client, world.ana, world.second, gift, comment["id"]),
        delete(client, world.ana, world.second, gift, comment["id"]),
    ):
        assert (response.status_code, response.json()) == (404, NOT_FOUND)
    assert thread(client, world.ana, world.first, gift)["comments"] == [comment]


def test_a_random_comment_is_not_found(client, world):
    gift = world.gifts[0]

    response = edit(client, world.ana, world.first, gift, uuid.uuid4())

    assert (response.status_code, response.json()) == (404, NOT_FOUND)


# Who reaches a thread (D5)


def test_an_invitee_of_another_occasion_gets_not_found_on_every_route(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    statuses = thread_routes(client, world.cleo, world.first, gift, comment["id"])

    assert statuses == NOT_FOUND_EVERYWHERE


def test_the_recipient_gets_not_found_on_every_route(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    statuses = thread_routes(client, world.owner, world.first, gift, comment["id"])

    assert statuses == NOT_FOUND_EVERYWHERE
    assert thread(client, world.ana, world.first, gift)["comments"] == [comment]


def test_a_stranger_gets_not_found_on_every_route(client, world, make_account):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    statuses = thread_routes(
        client, make_account("Eve"), world.first, gift, comment["id"]
    )

    assert statuses == NOT_FOUND_EVERYWHERE


def test_a_gift_of_another_list_is_not_found(client, world, make_world):
    other = make_world()

    assert (
        thread_routes(client, world.ana, world.first, other.gifts[0], uuid.uuid4())
        == NOT_FOUND_EVERYWHERE
    )


def test_the_owner_of_a_list_for_someone_else_comments_and_the_invitee_sees_their_name(
    client, make_world
):
    world = make_world(kind="other")
    gift = world.gifts[0]

    comment = posted(client, world.owner, world.first, gift, "I'll get the receipt")

    assert (comment["author_name"], comment["mine"]) == ("Olga", True)
    assert thread(client, world.ana, world.first, gift)["comments"] == [
        comment | {"mine": False}
    ]


# Names (D3)


@pytest.mark.parametrize("how", ["removed", "left"])
def test_someone_gone_keeps_their_name(client, world, how):
    gift = world.gifts[0]
    comment = posted(client, world.ben, world.first, gift, "Mine")
    if how == "removed":
        gone = client.delete(
            f"/api/occasions/{world.first}/members/{world.ben.id}",
            headers=world.owner.headers,
        )
    else:
        gone = client.delete(
            f"/api/occasions/{world.first}/membership", headers=world.ben.headers
        )
    assert gone.status_code == 204, gone.text

    assert thread(client, world.ana, world.first, gift)["comments"] == [
        comment | {"mine": False}
    ]
    # And they no longer reach the thread.
    assert (
        thread_routes(client, world.ben, world.first, gift, comment["id"])
        == NOT_FOUND_EVERYWHERE
    )


def test_a_deleted_account_is_unsigned_and_nothing_else_changes(client, world, rows):
    gift = world.gifts[0]
    theirs = posted(client, world.ben, world.first, gift, "Mine")
    other = posted(client, world.ana, world.first, gift, "Yours")
    edited = edit(client, world.ben, world.first, gift, theirs["id"], "Mine, edited")
    assert edited.status_code == 200

    assert client.delete("/api/me", headers=world.ben.headers).status_code == 204

    assert rows("comments") == 2
    seen = thread(client, world.ana, world.first, gift)["comments"]
    assert seen == [
        edited.json() | {"author_name": None, "mine": False},
        other,
    ]


# States of the gift and the occasion (D2, D5, D8)


def test_a_passed_occasion_still_accepts_comments(client, world):
    gift = world.gifts[0]
    move(client, world, world.first, PAST)

    comment = posted(client, world.ana, world.first, gift, "Settling up")

    assert thread(client, world.ben, world.first, gift)["comments"] == [
        comment | {"mine": False}
    ]
    assert edit(client, world.ana, world.first, gift, comment["id"]).status_code == 200
    assert (
        client.put(
            f"/api/occasions/{world.first}/gifts/{gift}/follow",
            headers=world.ben.headers,
        ).status_code
        == 204
    )


def test_a_received_gifts_thread_is_gone_and_comes_back_with_it(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift, "Kept for later")

    assert mark_received(client, world.owner, gift).status_code == 204
    assert (
        thread_routes(client, world.ana, world.first, gift, comment["id"])
        == NOT_FOUND_EVERYWHERE
    )

    assert put_back(client, world.owner, gift).status_code == 204
    # As it was, the author's follow included: the 404s changed nothing.
    assert thread(client, world.ana, world.first, gift) == {
        "following": True,
        "comments": [comment],
    }


def test_a_hidden_gift_has_a_thread_in_its_occasion_only(client, world, engine):
    gift = add_hidden(engine, world, world.first, world.ana)

    comment = posted(client, world.ben, world.first, gift, "Who bought it?")

    assert thread(client, world.ana, world.first, gift)["comments"] == [
        comment | {"mine": False}
    ]
    assert (
        thread_routes(client, world.cleo, world.second, gift, comment["id"])
        == NOT_FOUND_EVERYWHERE
    )


def test_after_keep_the_kept_gift_starts_empty_and_the_old_id_is_gone(
    client, world, engine
):
    gift = revealed_gift(client, world, engine)
    comment = posted(client, world.ana, world.first, gift, "Before the reveal")

    kept = keep(client, world.owner, gift)

    assert kept.status_code == 200, kept.text
    new_id = kept.json()["id"]
    assert gift_row(engine, gift) is None
    assert thread(client, world.ana, world.first, new_id)["comments"] == []
    assert (
        thread_routes(client, world.ana, world.first, gift, comment["id"])
        == NOT_FOUND_EVERYWHERE
    )


def test_a_deleted_gift_answers_not_found_on_every_route(client, world):
    gift = world.gifts[0]
    comment = posted(client, world.ana, world.first, gift)

    deleted = client.delete(f"/api/gifts/{gift}", headers=world.owner.headers)

    assert deleted.status_code == 204, deleted.text
    assert (
        thread_routes(client, world.ana, world.first, gift, comment["id"])
        == NOT_FOUND_EVERYWHERE
    )


def test_deleting_an_occasion_deletes_its_threads(client, world, rows):
    gift = world.gifts[0]
    posted(client, world.ana, world.first, gift)
    posted(client, world.cleo, world.second, gift)
    assert rows("comments") == 2

    deleted = client.delete(
        f"/api/occasions/{world.first}", headers=world.owner.headers
    )

    assert deleted.status_code == 204, deleted.text
    assert rows("comments") == 1
    assert rows("gift_follows", "occasion_id", world.first) == 0


def test_a_comment_body_is_stored_as_plain_text(client, world):
    gift = world.gifts[0]
    body = '<script>alert("x")</script> & [link](http://x)'

    comment = posted(client, world.ana, world.first, gift, body)

    assert comment["body"] == body
    assert thread(client, world.ben, world.first, gift)["comments"][0]["body"] == body
