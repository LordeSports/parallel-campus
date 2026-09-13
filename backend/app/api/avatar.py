"""我的分身路由（spec/03 §6）。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from sqlmodel import col, select

from ..config import settings
from ..constants import decompose_tick, time_label as fmt_time_label
from ..errors import NotFound, RateLimited
from ..models import (
    Dialogue,
    Event,
    HumanRateLog,
    Persona,
    Report as ReportModel,
    Whisper,
    new_id,
    now_utc,
)
from ..schemas.views import (
    AvatarView,
    DiaryEntryView,
    DiaryView,
    MoodPointView,
    ReflectionItemView,
    ReportView,
    WhisperItemView,
    WhisperRequest,
    WhisperResponseView,
)
from ..sim import report as report_mod
from ..sim.bus import bus
from ..sim.filter import check_text
from ..sim.world import get_world
from .deps import CurrentCharacter, CurrentUser, SessionDep
from .world import character_detail_full

log = logging.getLogger("pc.api.avatar")

router = APIRouter(prefix="/avatar", tags=["avatar"])

DIARY_EVENT_TYPES = {
    "character_moved", "character_activity", "dialogue_ended", "post_created",
    "comment_created", "like_created", "dm_sent", "whisper_response", "reflection",
    "event_started",
}

TYPE_ICON = {
    "character_moved": "🚶", "character_activity": "🎯", "dialogue_ended": "💬",
    "post_created": "📝", "comment_created": "💭", "like_created": "👍",
    "dm_sent": "💌", "whisper_response": "🗣", "reflection": "🌙", "event_started": "📣",
}


async def _whispers_left_today(session: SessionDep, user_id: str, day: int) -> int:
    rows = (
        await session.exec(
            select(Whisper).where(
                col(Whisper.user_id) == user_id, col(Whisper.day) == day
            )
        )
    ).all()
    return max(0, settings.whispers_per_day - len(rows))


@router.get("", response_model=AvatarView)
async def get_avatar(
    session: SessionDep, user: CurrentUser, character: CurrentCharacter
) -> AvatarView:
    world = await get_world()
    data = await character_detail_full(world, character, user.id, session)

    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()

    left = await _whispers_left_today(session, user.id, world.day)
    return AvatarView.model_validate({
        **data,
        "whispers_left_today": left,
        "deployed_at_tick": character.deployed_at_tick,
        "persona_version": persona.version if persona else 1,
    })


@router.get("/diary", response_model=DiaryView)
async def get_diary(
    session: SessionDep,
    character: CurrentCharacter,
    day: int | None = Query(default=None),
    user: CurrentUser | None = None,
) -> DiaryView:
    world = await get_world()
    target_day = day if day is not None else world.day

    # 事件时间线（actor 或 target 命中我）
    rows = (
        await session.exec(
            select(Event)
            .where(
                col(Event.day) == target_day,
                (col(Event.actor_id) == character.id) | (col(Event.target_id) == character.id),
            )
            .order_by(col(Event.tick).asc())
            .limit(400)
        )
    ).all()

    entries: list[DiaryEntryView] = []
    seen_refs: set[str] = set()
    for e in rows:
        if e.type not in DIARY_EVENT_TYPES:
            continue
        payload = dict(e.payload or {})
        text = _diary_text(world, character, e)
        if not text:
            continue
        dedup = f"{e.type}:{payload.get('dialogue_id') or payload.get('post_id') or e.id}"
        if dedup in seen_refs:
            continue
        seen_refs.add(dedup)
        d, m = decompose_tick(e.tick)
        entries.append(DiaryEntryView(
            tick=e.tick, time_label=fmt_time_label(d, m), type=e.type,
            text=text, payload=payload,
        ))

    # 心情曲线：从 character_activity / tick 事件重建（近似：每 tick 取一次快照不现实，
    # 改为从日记条目 + 当前值合成一条平滑曲线）
    mood_series = await _mood_series(session, world, character, target_day)

    # 反思
    from ..models import Memory

    reflections = (
        await session.exec(
            select(Memory)
            .where(
                col(Memory.character_id) == character.id,
                col(Memory.day) == target_day,
                col(Memory.kind) == "reflection",
            )
            .order_by(col(Memory.tick).asc())
        )
    ).all()

    whispers = (
        await session.exec(
            select(Whisper)
            .where(col(Whisper.character_id) == character.id, col(Whisper.day) == target_day)
            .order_by(col(Whisper.tick).asc())
        )
    ).all()

    return DiaryView(
        day=target_day,
        entries=entries,
        mood_series=mood_series,
        reflections=[ReflectionItemView(tick=r.tick, text=r.text, importance=r.importance)
                     for r in reflections],
        whispers=[WhisperItemView(id=w.id, text=w.text, tick=w.tick,
                                  accepted=w.accepted, reason=w.reason)
                  for w in whispers],
    )


def _diary_text(world, character, e: Event) -> str:
    p = e.payload or {}
    cid = character.id
    if e.type == "character_moved" and p.get("character_id") == cid:
        frm = world.location_name(p.get("from"))
        to = world.location_name(p.get("to"))
        return f"从{frm}去了{to}"
    if e.type == "dialogue_ended" and cid in (p.get("a_id"), p.get("b_id")):
        other_id = p.get("b_id") if p.get("a_id") == cid else p.get("a_id")
        other = world.display_name(other_id)
        delta = p.get("a_to_b_delta") if p.get("a_id") == cid else p.get("b_to_a_delta")
        sign = "+" if (delta or 0) > 0 else ""
        return f"和{other}聊了一会儿（好感 {sign}{delta}）"
    if e.type == "post_created" and e.actor_id == cid:
        post = world.posts_since(0)
        return "发了一条帖子"
    if e.type == "dm_sent" and p.get("from_id") == cid:
        return f"给{world.display_name(p.get('to_id'))}发了条私信"
    if e.type == "dm_sent" and p.get("to_id") == cid:
        return f"收到{world.display_name(p.get('from_id'))}的私信"
    if e.type == "whisper_response" and p.get("character_id") == cid:
        verdict = "接受了" if p.get("accepted") else "拒绝了"
        reason = p.get("reason") or ""
        return f"{verdict}你的耳语：{reason}"
    if e.type == "reflection" and p.get("character_id") == cid:
        return p.get("text", "")
    if e.type == "event_started":
        ev = p.get("event") or {}
        return f"校园里开始了「{ev.get('title', '')}」"
    if e.type == "character_activity" and p.get("character_id") == cid:
        return f"正在{p.get('activity')}"
    return ""


async def _mood_series(session: SessionDep, world, character, day: int) -> list[MoodPointView]:
    """当日从首 tick 到当前 tick 的情绪曲线。

    事件表不记录每 tick 心情快照，这里用「该日 character_activity 事件的时间点 +
    当前值为终点」合成；若当日无事件则给单点。
    """
    from ..schemas.events import SseEvent

    ticks = [t for t in range((day - 1) * 48, min((day - 1) * 48 + 48, world.tick + 1))]
    if not ticks:
        return []

    # 找当日所有 activity 事件，作为锚点
    rows = (
        await session.exec(
            select(Event)
            .where(
                col(Event.day) == day,
                col(Event.type) == "character_activity",
                col(Event.actor_id) == character.id,
            )
            .order_by(col(Event.tick).asc())
        )
    ).all()
    anchors: dict[int, tuple[float, float]] = {}
    for e in rows:
        mood = (e.payload or {}).get("mood") or {}
        anchors[e.tick] = (float(mood.get("valence", 0.0)), float(mood.get("arousal", 0.0)))

    out: list[MoodPointView] = []
    last = (character.mood_valence, character.mood_arousal)
    for t in ticks:
        if t in anchors:
            last = anchors[t]
        out.append(MoodPointView(tick=t, valence=round(last[0], 3), arousal=round(last[1], 3)))
    # 取最多 48 点，避免前端图表过密
    if len(out) > 48:
        step = max(1, len(out) // 48)
        out = out[::step]
    return out


@router.post("/whisper", response_model=WhisperResponseView, status_code=201)
async def send_whisper(
    payload: WhisperRequest, session: SessionDep, user: CurrentUser,
    character: CurrentCharacter,
) -> WhisperResponseView:
    """给分身留一句耳语（≤80 字）。下一 tick 强制决策（04 §5.4）。"""
    text = payload.text.strip()
    ok, reason = check_text(text)
    if not ok:
        from ..errors import ValidationError

        raise ValidationError("内容未通过审核", {"reason": "content_filtered"})

    world = await get_world()
    left = await _whispers_left_today(session, user.id, world.day)
    if left <= 0:
        raise RateLimited("今天的耳语次数已用完", retry_after_seconds=3600)

    whisper = Whisper(
        id=new_id("w_"), character_id=character.id, user_id=user.id,
        text=text[:80], tick=world.tick, day=world.day,
    )
    session.add(whisper)
    session.add(HumanRateLog(id=new_id("hrl_"), user_id=user.id, action="whisper",
                             at=now_utc(), day=world.day))

    # 立刻挂到角色上：下一 tick 强制决策
    character.pending_whisper_id = whisper.id
    session.add(character)
    await session.commit()

    await world.reload_characters()
    return WhisperResponseView(
        whisper_id=whisper.id,
        whispers_left_today=max(0, left - 1),
    )


@router.get("/report", response_model=ReportView)
async def get_report(
    session: SessionDep,
    user: CurrentUser,
    character: CurrentCharacter,
    day: int | None = Query(default=None),
) -> ReportView:
    world = await get_world()
    data = await report_mod.get_report_view(session, world, character, day)
    if data is None:
        # 404 带 next_at_tick（03 §6）
        from ..errors import AppError

        next_tick = ((world.tick // 48) + 1) * 48 + 47
        raise NotFound(
            "还没有报告",
            {"next_at_tick": next_tick},
        )
    return ReportView.model_validate(data)


__all__ = ["router"]
