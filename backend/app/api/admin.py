"""管理路由（spec/03 §8）。需 `X-Admin-Token`。"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlmodel import col, select

from ..config import settings
from ..errors import NotFound
from ..models import Comment, LlmUsage, Post, QuotaLog, WorldState
from ..schemas.views import (
    AdminStatusView,
    FastForwardResponse,
    HotPullResponse,
    LlmTodayView,
    ModeResponse,
    ZhihuTodayView,
)
from ..sim.bus import bus
from ..sim.env_agent import bj_today, maybe_pull_hot
from ..sim.ticker import decide_mode, ticker
from ..sim.world import get_world
from ..db import session_scope, write_lock, write_session
from .deps import AdminGuard, SessionDep

log = logging.getLogger("pc.api.admin")

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[])

BJ = timezone(timedelta(hours=8))


@router.post("/fast-forward", response_model=FastForwardResponse, status_code=202)
async def fast_forward(
    _: AdminGuard, ticks: int = Query(default=48, ge=1, le=1000)
) -> FastForwardResponse:
    remaining = await ticker.fast_forward(ticks)
    return FastForwardResponse(mode="fast_forward", remaining_ticks=remaining)


@router.post("/pause", response_model=ModeResponse)
async def pause(_: AdminGuard) -> ModeResponse:
    mode = await ticker.pause()
    return ModeResponse(mode=mode)


@router.post("/resume", response_model=ModeResponse)
async def resume(_: AdminGuard) -> ModeResponse:
    mode = await ticker.resume()
    return ModeResponse(mode=mode)


@router.post("/hot-pull", response_model=HotPullResponse)
async def hot_pull(_: AdminGuard) -> HotPullResponse:
    world = await get_world()
    async with write_lock:
        async with write_session() as session:
            created = await maybe_pull_hot(session, world, force=True)
    return HotPullResponse(events_created=created)


@router.get("/status", response_model=AdminStatusView)
async def status(_: AdminGuard, session: SessionDep) -> AdminStatusView:
    world = await get_world()
    today = bj_today()
    start = datetime.now(BJ).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)

    rows = (
        await session.exec(select(LlmUsage).where(col(LlmUsage.at) >= start))
    ).all()
    gpt = sum(r.prompt_tokens for r in rows)
    gct = sum(r.completion_tokens for r in rows)

    quotas = (await session.exec(select(QuotaLog).where(col(QuotaLog.date) == today))).all()
    qmap = {q.api: q.count for q in quotas}

    return AdminStatusView(
        mode=world.state.speed_mode,
        remaining_ticks=world.state.remaining_ticks,
        tick=world.tick,
        llm_today=LlmTodayView(
            calls=len(rows), prompt_tokens=gpt, completion_tokens=gct,
            fail_streak=world.state.llm_fail_streak,
        ),
        zhihu_today=ZhihuTodayView(
            hot_list=qmap.get("hot_list", 0),
            zhihu_search=qmap.get("zhihu_search", 0),
            zhida=qmap.get("zhida", 0),
            user_data=qmap.get("user_data", 0),
        ),
    )


@router.delete("/posts/{post_id}", status_code=204)
async def delete_post(post_id: str, _: AdminGuard, session: SessionDep) -> None:
    post = (await session.exec(select(Post).where(Post.id == post_id))).first()
    if post is None:
        raise NotFound("帖子不存在")
    post.deleted = True
    session.add(post)
    await session.commit()


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(comment_id: str, _: AdminGuard, session: SessionDep) -> None:
    comment = (await session.exec(select(Comment).where(Comment.id == comment_id))).first()
    if comment is None:
        raise NotFound("评论不存在")
    comment.deleted = True
    session.add(comment)
    post = (await session.exec(select(Post).where(Post.id == comment.post_id))).first()
    if post is not None:
        post.comment_count = max(0, post.comment_count - 1)
        session.add(post)
    await session.commit()


@router.post("/reseed", status_code=200)
async def reseed(_: AdminGuard) -> dict:
    """仅 DEV。"""
    if not settings.dev_mode:
        raise NotFound("reseed 未启用")
    from ..seed_runtime import reseed as do_reseed

    await do_reseed()
    return {"status": "ok"}


__all__ = ["router"]
