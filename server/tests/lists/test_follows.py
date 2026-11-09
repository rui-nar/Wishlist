"""Following a gift in an occasion, by hand and on commenting (comments plan
D4, D5).

Automatic follows from the claim routes and follows dropped on leaving come
later (unit U3). The world of `test_reservations.py`.
"""

import test_reservations
from test_comments import posted, thread

# Its fixtures, registered here by name.
make_world = test_reservations.make_world
world = test_reservations.world


def path(occasion, gift):
    return f"/api/occasions/{occasion}/gifts/{gift}/follow"


def follow(client, account, occasion, gift):
    return client.put(path(occasion, gift), headers=account.headers)


def unfollow(client, account, occasion, gift):
    return client.delete(path(occasion, gift), headers=account.headers)


def following(client, account, occasion, gift):
    return thread(client, account, occasion, gift)["following"]


def test_following_and_unfollowing(client, world):
    gift = world.gifts[0]
    assert following(client, world.ana, world.first, gift) is False

    response = follow(client, world.ana, world.first, gift)
    assert (response.status_code, response.content) == (204, b"")
    assert following(client, world.ana, world.first, gift) is True

    response = unfollow(client, world.ana, world.first, gift)
    assert (response.status_code, response.content) == (204, b"")
    assert following(client, world.ana, world.first, gift) is False


def test_following_and_unfollowing_are_idempotent(client, world, rows):
    gift = world.gifts[0]

    for _ in range(2):
        assert follow(client, world.ana, world.first, gift).status_code == 204
    assert following(client, world.ana, world.first, gift) is True
    for _ in range(2):
        assert unfollow(client, world.ana, world.first, gift).status_code == 204
    assert following(client, world.ana, world.first, gift) is False
    assert rows("gift_follows") == 1


def test_posting_follows_the_author_only(client, world):
    gift = world.gifts[0]

    posted(client, world.ana, world.first, gift)

    assert following(client, world.ana, world.first, gift) is True
    assert following(client, world.ben, world.first, gift) is False


def test_posting_after_an_explicit_unfollow_stays_unfollowed(client, world):
    gift = world.gifts[0]
    posted(client, world.ana, world.first, gift)
    assert unfollow(client, world.ana, world.first, gift).status_code == 204

    posted(client, world.ana, world.first, gift, "Still commenting")

    assert following(client, world.ana, world.first, gift) is False


def test_an_unfollow_before_any_comment_sticks_too(client, world):
    gift = world.gifts[0]
    assert unfollow(client, world.ana, world.first, gift).status_code == 204

    posted(client, world.ana, world.first, gift)

    assert following(client, world.ana, world.first, gift) is False


def test_a_follow_by_hand_after_an_unfollow_follows_again(client, world):
    gift = world.gifts[0]
    assert unfollow(client, world.ana, world.first, gift).status_code == 204

    assert follow(client, world.ana, world.first, gift).status_code == 204

    assert following(client, world.ana, world.first, gift) is True


def test_a_follow_is_of_one_gift_in_one_occasion(client, world):
    gift, other = world.gifts[0], world.gifts[1]
    token = client.post(
        f"/api/occasions/{world.second}/link", headers=world.owner.headers
    ).json()["join_token"]
    joined = client.post("/api/join", json={"token": token}, headers=world.ana.headers)
    assert joined.status_code == 200, joined.text

    assert follow(client, world.ana, world.first, gift).status_code == 204

    assert following(client, world.ana, world.first, gift) is True
    assert following(client, world.ana, world.first, other) is False
    assert following(client, world.ana, world.second, gift) is False


def test_the_recipient_cannot_follow_and_nothing_is_written(client, world, rows):
    gift = world.gifts[0]

    for call in (follow, unfollow):
        response = call(client, world.owner, world.first, gift)
        assert (response.status_code, response.json()) == (
            404,
            {"detail": "Not found"},
        )
    assert rows("gift_follows") == 0


def test_a_giving_owner_follows(client, make_world):
    world = make_world(kind="other")
    gift = world.gifts[0]

    assert follow(client, world.owner, world.first, gift).status_code == 204

    assert following(client, world.owner, world.first, gift) is True


def test_a_deleted_account_leaves_no_follow(client, world, rows):
    gift = world.gifts[0]
    assert follow(client, world.ben, world.first, gift).status_code == 204

    assert client.delete("/api/me", headers=world.ben.headers).status_code == 204

    assert rows("gift_follows") == 0
