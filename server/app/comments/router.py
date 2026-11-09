"""The thread under a gift in an occasion, and following it (comments plan D5).

Every route resolves the gift through `giving_gift` (D6), so a recipient
gets the random-id 404 on every route and for every state of the thread.
Writes follow the claims' lock order (D7): the user `FOR KEY SHARE` (taken by
`current_session`), the occasion `FOR SHARE`, the gift `FOR KEY SHARE`, then
the comment `FOR UPDATE` for an edit or delete. They write `comments`,
`gift_follows` and the outbox only (D9), never a row an owner reads.
"""

import uuid

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.accounts.deps import CurrentUser
from app.accounts.models import User
from app.comments.follows import auto_follow, set_following
from app.comments.models import Comment, GiftFollow
from app.comments.schemas import CommentIn, CommentOut, GiftThread
from app.db import DbSession
from app.lists.access import giving_gift, not_found
from app.notifications import events

router = APIRouter(
    prefix="/api/occasions/{occasion_id}/gifts/{gift_id}", tags=["comments"]
)


@router.get("/comments")
def thread(
    occasion_id: uuid.UUID, gift_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> GiftThread:
    # No lock: an owner's change never waits on a giver's read (D6).
    giving_gift(db, user, occasion_id, gift_id, lock=False)
    rows = db.execute(
        select(Comment, User.display_name)
        .outerjoin(User, User.id == Comment.author_id)
        .where(Comment.occasion_id == occasion_id, Comment.gift_id == gift_id)
        .order_by(Comment.created_at, Comment.id)
    )
    comments = [_comment_out(comment, name, user) for comment, name in rows]
    following = db.scalar(
        select(GiftFollow.following).where(
            GiftFollow.occasion_id == occasion_id,
            GiftFollow.gift_id == gift_id,
            GiftFollow.user_id == user.id,
        )
    )
    return GiftThread(following=following is True, comments=comments)


@router.post("/comments", status_code=status.HTTP_201_CREATED)
def post_comment(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    body: CommentIn,
    user: CurrentUser,
    db: DbSession,
) -> CommentOut:
    giving_gift(db, user, occasion_id, gift_id)
    comment = Comment(
        occasion_id=occasion_id, gift_id=gift_id, author_id=user.id, body=body.body
    )
    db.add(comment)
    db.flush()
    auto_follow(db, occasion_id, gift_id, user.id)
    events.comment_added(db, occasion_id, gift_id, user.id, comment.id)
    return _comment_out(comment, user.display_name, user)


@router.patch("/comments/{comment_id}")
def edit_comment(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    comment_id: uuid.UUID,
    body: CommentIn,
    request: Request,
    user: CurrentUser,
    db: DbSession,
) -> CommentOut:
    giving_gift(db, user, occasion_id, gift_id)
    comment = _own_comment(db, occasion_id, gift_id, comment_id, user)
    comment.body = body.body
    comment.edited_at = request.app.state.clock()
    db.flush()
    return _comment_out(comment, user.display_name, user)


@router.delete("/comments/{comment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_comment(
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: CurrentUser,
    db: DbSession,
) -> Response:
    giving_gift(db, user, occasion_id, gift_id)
    db.delete(_own_comment(db, occasion_id, gift_id, comment_id, user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/follow", status_code=status.HTTP_204_NO_CONTENT)
def follow(
    occasion_id: uuid.UUID, gift_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    giving_gift(db, user, occasion_id, gift_id)
    set_following(db, occasion_id, gift_id, user.id, True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/follow", status_code=status.HTTP_204_NO_CONTENT)
def unfollow(
    occasion_id: uuid.UUID, gift_id: uuid.UUID, user: CurrentUser, db: DbSession
) -> Response:
    giving_gift(db, user, occasion_id, gift_id)
    set_following(db, occasion_id, gift_id, user.id, False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _own_comment(
    db: Session,
    occasion_id: uuid.UUID,
    gift_id: uuid.UUID,
    comment_id: uuid.UUID,
    user: User,
) -> Comment:
    """The caller's comment of this thread, locked until the request commits
    (D7); otherwise the random-id 404 (D5)."""
    found = db.scalar(
        select(Comment)
        .where(
            Comment.id == comment_id,
            Comment.occasion_id == occasion_id,
            Comment.gift_id == gift_id,
            Comment.author_id == user.id,
        )
        .with_for_update()
    )
    if found is None:
        raise not_found()
    return found


def _comment_out(comment: Comment, author_name: str | None, user: User) -> CommentOut:
    return CommentOut(
        id=comment.id,
        author_name=author_name,
        mine=comment.author_id == user.id,
        body=comment.body,
        created_at=comment.created_at,
        edited=comment.edited_at is not None,
    )
