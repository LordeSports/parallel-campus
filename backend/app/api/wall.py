"""校园墙路由（spec/03 §5）。"""

from __future__ import annotations

import base64
import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Query, Response
from sqlmodel import col, select

from ..config import settings
from ..constants import decompose_tick, time_label as fmt_time_label
from ..errors import NotFound, RateLimited
from ..models import Character, Comment, HumanRateLog, Like, Post, User, new_id, now_utc
from ..schemas.views import (
    AuthorView,
    CommentView,
    CreateCommentRequest,
    CreatePostRequest,
    LikeResponse,
    PostDetailView,
    PostView,
    SourceView,
)
from ..sim.bus import bus
from ..sim.filter import check_text, sanitize_url
from ..sim.world import get_world
from .deps import CurrentUser, OptionalUser, SessionDep

log = logging.getLogger("pc.api.wall")

router = APIRouter(prefix="/wall", tags=["wall"])

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


# ─────────────────────────── 分页游标 ───────────────────────────


def encode_cursor(tick: int, post_id: str) -> str:
    raw = f"{tick}:{post_id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str | None) -> tuple[int, str] | None:
    if not cursor:
        return None
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode()).decode()
        tick_s, _, post_id = raw.partition(":")
        return int(tick_s), post_id
    except Exception:
        return None


# ─────────────────────────── 视图构造 ───────────────────────────


async def author_view(session: SessionDep, world, author_id: str | None) -> AuthorView | None:
    if not author_id:
        return None
    char = world.get_character(author_id)
    if char is not None:
        return AuthorView(id=char.id, name=char.name, avatar_key=char.avatar_key, kind=char.kind)
    user = (await session.exec(select(User).where(User.id == author_id))).first()
    if user is not None:
        return AuthorView(id=user.id, name=user.display_name, avatar_key=user.avatar_key, kind="player")
    return None


async def post_view(
    session: SessionDep, world, post: Post, me_user_id: str | None
) -> PostView:
    day, minute = decompose_tick(post.tick)
    author = await author_view(session, world, post.author_id)
    source = None
    url = sanitize_url(post.source_url)
    if post.source_title or url:
        source = SourceView(title=post.source_title or "知乎", url=url or "")
    liked = False
    if me_user_id:
        liked = (
            await session.exec(
                select(Like).where(col(Like.post_id) == post.id, col(Like.liker_id) == me_user_id)
            )
        ).first() is not None
    return PostView(
        id=post.id, board=post.board, author=author, author_label=post.author_label,
        text=post.text, tick=post.tick, time_label=fmt_time_label(day, minute),
        like_count=post.like_count, comment_count=post.comment_count,
        source=source, event_id=post.event_id, liked_by_me=liked,
    )


async def comment_view(session: SessionDep, world, comment: Comment) -> CommentView:
    day, minute = decompose_tick(comment.tick)
    author = await author_view(session, world, comment.author_id)
    return CommentView(
        id=comment.id, post_id=comment.post_id, author=author,
        author_label=comment.author_label, text=comment.text, tick=comment.tick,
        time_label=fmt_time_label(day, minute),
    )


# ─────────────────────────── 人类限流 ───────────────────────────


async def _enforce_rate(
    session: SessionDep, user: User, action: str, per_hour: int
) -> None:
    """count in last hour >= per_hour → 429（03 §5）。"""
    since = now_utc() - timedelta(hours=1)
    rows = (
        await session.exec(
            select(HumanRateLog).where(
                col(HumanRateLog.user_id) == user.id,
                col(HumanRateLog.action) == action,
                col(HumanRateLog.at) >= since,
            )
        )
    ).all()
    if len(rows) >= per_hour:
        oldest = min(r.at for r in rows)
        retry = max(1, int((oldest + timedelta(hours=1) - now_utc()).total_seconds()))
        raise RateLimited(f"操作太频繁，{retry}s 后再试", retry_after_seconds=retry)


def _note_rate(session: SessionDep, user: User, action: str, day: int) -> None:
    session.add(HumanRateLog(id=new_id("hrl_"), user_id=user.id, action=action,
                             at=now_utc(), day=day))


# ─────────────────────────── 路由 ───────────────────────────


@router.get("/posts", response_model=dict)
async def list_posts(
    session: SessionDep,
    user: CurrentUser,
    board: str = Query(default="wall"),
    cursor: str | None = None,
    limit: int = Query(default=DEFAULT_LIMIT, le=MAX_LIMIT),
) -> dict[str, Any]:
    world = await get_world()
    stmt = (
        select(Post)
        .where(col(Post.board) == board, col(Post.deleted) == False)  # noqa: E712
        .order_by(col(Post.tick).desc(), col(Post.id).desc())
    )
    dec = decode_cursor(cursor)
    if dec is not None:
        tick, post_id = dec
        stmt = stmt.where(
            (col(Post.tick) < tick) | ((col(Post.tick) == tick) & (col(Post.id) < post_id))
        )

    rows = (await session.exec(stmt.limit(limit + 1))).all()
    has_more = len(rows) > limit
    rows = rows[:limit]

    items = [await post_view(session, world, p, user.id) for p in rows]
    next_cursor = encode_cursor(rows[-1].tick, rows[-1].id) if has_more and rows else None
    return {"items": [i.model_dump() for i in items], "next_cursor": next_cursor}


@router.get("/posts/{post_id}", response_model=PostDetailView)
async def get_post(post_id: str, session: SessionDep, user: CurrentUser) -> PostDetailView:
    world = await get_world()
    post = (await session.exec(select(Post).where(Post.id == post_id))).first()
    if post is None or post.deleted:
        raise NotFound("帖子不存在")

    comments = (
        await session.exec(
            select(Comment)
            .where(col(Comment.post_id) == post_id, col(Comment.deleted) == False)  # noqa: E712
            .order_by(col(Comment.tick).asc())
            .limit(200)
        )
    ).all()

    return PostDetailView(
        post=await post_view(session, world, post, user.id),
        comments=[await comment_view(session, world, c) for c in comments],
    )


@router.post("/posts", response_model=PostView, status_code=201)
async def create_post(
    payload: CreatePostRequest, session: SessionDep, user: CurrentUser
) -> PostView:
    """人类只能发树洞（03 §5）。"""
    if payload.board != "tree_hole":
        from ..errors import ValidationError

        raise ValidationError("只能发树洞帖", {"board": "tree_hole"})

    text = payload.text.strip()
    ok, reason = check_text(text)
    if not ok:
        from ..errors import ValidationError

        raise ValidationError("内容未通过审核", {"reason": "content_filtered"})

    await _enforce_rate(session, user, "post", settings.human_post_per_hour)

    world = await get_world()
    post = Post(
        id=new_id("p_"), board="tree_hole", author_id=user.id, author_label="围观者",
        text=text[:500], tick=world.tick, day=world.day,
    )
    session.add(post)
    _note_rate(session, user, "post", world.day)
    await session.commit()

    world.note_new_post(post)
    from ..schemas.events import make_event

    bus.emit(make_event("post_created", world.tick, world.day, {"post_id": post.id},
                        actor_id=user.id, location_id=None))
    return await post_view(session, world, post, user.id)


@router.post("/posts/{post_id}/comments", response_model=CommentView, status_code=201)
async def create_comment(
    post_id: str, payload: CreateCommentRequest, session: SessionDep, user: CurrentUser
) -> CommentView:
    post = (await session.exec(select(Post).where(Post.id == post_id))).first()
    if post is None or post.deleted:
        raise NotFound("帖子不存在")

    text = payload.text.strip()
    ok, reason = check_text(text)
    if not ok:
        from ..errors import ValidationError

        raise ValidationError("内容未通过审核", {"reason": "content_filtered"})

    await _enforce_rate(session, user, "comment", settings.human_comment_per_hour)

    world = await get_world()
    comment = Comment(
        id=new_id("c_"), post_id=post.id, author_id=user.id, author_label="围观者",
        text=text[:200], tick=world.tick, day=world.day,
    )
    session.add(comment)
    post.comment_count += 1
    session.add(post)
    _note_rate(session, user, "comment", world.day)
    await session.commit()

    from ..schemas.events import make_event

    bus.emit(make_event("comment_created", world.tick, world.day,
                        {"comment_id": comment.id, "post_id": post.id},
                        actor_id=user.id, target_id=post.id))
    return await comment_view(session, world, comment)


@router.post("/posts/{post_id}/like", response_model=LikeResponse)
async def toggle_like(post_id: str, session: SessionDep, user: CurrentUser) -> LikeResponse:
    post = (await session.exec(select(Post).where(Post.id == post_id))).first()
    if post is None or post.deleted:
        raise NotFound("帖子不存在")

    existing = (
        await session.exec(
            select(Like).where(col(Like.post_id) == post_id, col(Like.liker_id) == user.id)
        )
    ).first()

    if existing is not None:
        await session.delete(existing)
        post.like_count = max(0, post.like_count - 1)
        liked = False
    else:
        session.add(Like(id=new_id("lk_"), post_id=post_id, liker_id=user.id))
        post.like_count += 1
        liked = True
    session.add(post)
    await session.commit()

    if liked:
        world = await get_world()
        from ..schemas.events import make_event

        bus.emit(make_event("like_created", world.tick, world.day,
                            {"post_id": post_id, "liker_id": user.id, "like_count": post.like_count},
                            actor_id=user.id, target_id=post_id))

    return LikeResponse(liked=liked, like_count=post.like_count)


__all__ = ["router", "post_view", "comment_view", "author_view", "encode_cursor", "decode_cursor"]
