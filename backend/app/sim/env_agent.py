"""环境 agent（spec/04 §8）：新一天 / 热榜转译 / 简报。"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..errors import LlmError, LlmOutputError
from ..llm.gateway import get_llm
from ..models import Character, Memory, Post, Post as PostModel, WorldEvent, new_id
from ..schemas.domain import (
    Briefing,
    DailySchedule,
    HotEvents,
    NewDay,
    PersonaFile,
    ScheduleBatch,
    Weather,
)
from ..schemas.events import make_event
from ..seeds import (
    default_schedule,
    events_for_day,
    get_location,
    is_weekend,
    normalize_tags,
    weekday_courses,
)
from . import filter as content_filter
from . import memory as mem_mod

log = logging.getLogger("pc.env_agent")

BJ = timezone(timedelta(hours=8))

FALLBACK_WEATHER = [
    ({"kind": "sunny", "temp_c": 24, "text": "太阳很好，晒被子的最佳时机"}, 4),
    ({"kind": "cloudy", "temp_c": 22, "text": "阴沉沉的，但还没下雨"}, 3),
    ({"kind": "rainy", "temp_c": 19, "text": "小雨，湖边的椅子今天没人坐"}, 2),
    ({"kind": "windy", "temp_c": 20, "text": "风挺大，外套得拉上拉链"}, 1),
    ({"kind": "foggy", "temp_c": 17, "text": "早上有雾，图书馆的玻璃蒙了一层水汽"}, 1),
]


def bj_today() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d")


def _pick_fallback_weather() -> dict[str, Any]:
    pool = [w for w, n in FALLBACK_WEATHER for _ in range(n)]
    return dict(random.choice(pool))


# ─────────────────────────── 8.1 new_day（06:00）───────────────────────────


async def new_day(session: AsyncSession, world) -> None:
    """天气、公告、日程；重置当日计数。"""
    day = world.day
    weekday = world.weekday
    calendar_items = events_for_day(day)

    weather, announcements = await _gen_weather(
        day, weekday, calendar_items, world.state.last_briefing
    )
    world.state.weather = weather
    world.emit(
        make_event("weather", world.tick, world.day, {"day": day, "weather": weather})
    )

    # 公告由 sys_broadcast 发 notice
    for text in announcements[:2]:
        await _broadcast(session, world, text)

    await _generate_schedules(session, world, calendar_items)

    # 重置：affinity_delta_today=0（06:00 清零）
    from ..models import Relationship

    rels = (await session.exec(select(Relationship))).all()
    for rel in rels:
        rel.affinity_delta_today = 0

    world.state.hot_pull_count_today = 0
    await world.reload_active_events(session)
    await world.seed_events_for_day(session)


async def _gen_weather(
    day: int, weekday: int, calendar_items: list[dict], last_briefing: dict | None
) -> tuple[dict[str, Any], list[str]]:
    llm = get_llm()
    if not llm.offline:
        ctx = {
            "day": day,
            "weekday_label": f"第{day}天 周{weekday}",
            "season": "秋",
            "calendar_items": [
                f"{e['start']} {e['title']} @{e.get('location_id')}" for e in calendar_items
            ],
            "yesterday_briefing": (last_briefing or {}).get("text", ""),
            "yesterday_weather": "",
        }
        try:
            out = await llm.json("cheap", "env_new_day", ctx, NewDay, max_tokens=400)
            return out.weather.model_dump(), list(out.announcements)
        except (LlmError, LlmOutputError) as exc:
            log.warning("new_day 天气生成失败: %s", exc)
        except Exception:
            log.exception("new_day 天气生成异常")
    return _pick_fallback_weather(), []


async def _broadcast(session: AsyncSession, world, text: str) -> None:
    """sys_broadcast 发 notice 帖。"""
    ok, _ = content_filter.check_text(text)
    if not ok:
        return
    post = PostModel(
        id=new_id("p_"), board="notice", author_id="sys_broadcast",
        text=text[:500], tick=world.tick, day=world.day,
    )
    session.add(post)
    world.note_new_post(post)
    world.emit(
        make_event("post_created", world.tick, world.day, {"post_id": post.id},
                   actor_id="sys_broadcast", location_id="field")
    )


async def _generate_schedules(session: AsyncSession, world, calendar_items: list[dict]) -> None:
    """NPC 1 次批量（cheap）；player 各 1 次（strong）；失败用默认模板。"""
    awake = world.active_characters()
    if not awake:
        return

    npcs = [c for c in awake if c.kind == "npc"]
    players = [c for c in awake if c.kind == "player"]

    # ── NPC 批量 ──
    if npcs:
        ctx = {
            "mode": "batch",
            "characters": [
                {
                    "id": c.id,
                    "name": c.name,
                    "persona_brief": _brief(c),
                    "identity": _identity(c),
                    "habits": (c.persona or {}).get("habits", ""),
                    "yesterday_reflections": [],
                    "top_relations": [],
                }
                for c in npcs
            ],
            "day": world.day,
            "weekday_label": f"周{world.weekday}",
            "weather": world.weather,
            "calendar_items": [
                f"{e['start']} {e['title']} @{e.get('location_id')}" for e in calendar_items
            ],
            "locations": [f"{lid}: {l.name}（{'、'.join(l.affordances)}）"
                          for lid, l in world.locations.items()],
            "constraints": "07:00–23:30 无缝覆盖；30 分对齐；周一至周五上午至少一节课；周末不上课",
        }
        batch: dict[str, DailySchedule] = {}
        llm = get_llm()
        if not llm.offline:
            try:
                out = await llm.json("cheap", "daily_schedule", ctx, ScheduleBatch, max_tokens=2600)
                batch = out.schedules
            except (LlmError, LlmOutputError) as exc:
                log.warning("NPC 批量日程失败: %s", exc)
            except Exception:
                log.exception("NPC 批量日程异常")
        for c in npcs:
            sched = _validated(batch.get(c.id), world.day)
            c.schedule = sched.model_dump()
            c.schedule_day = world.day
            session.add(c)

    # ── player 单人 ──
    for c in players:
        ctx = {
            "mode": "single",
            "characters": [{
                "id": c.id, "name": c.name, "persona_brief": _brief(c),
                "identity": _identity(c), "habits": "",
                "yesterday_reflections": await _yesterday_reflections(session, c, world),
                "top_relations": await _top_relations(session, c),
            }],
            "day": world.day,
            "weekday_label": f"周{world.weekday}",
            "weather": world.weather,
            "calendar_items": [
                f"{e['start']} {e['title']} @{e.get('location_id')}" for e in calendar_items
            ],
            "locations": [f"{lid}: {l.name}（{'、'.join(l.affordances)}）"
                          for lid, l in world.locations.items()],
            "constraints": "07:00–23:30 无缝覆盖；30 分对齐；周一至周五上午至少一节课；周末不上课",
        }
        sched = None
        llm = get_llm()
        if not llm.offline:
            try:
                sched = await llm.json("strong", "daily_schedule", ctx, DailySchedule, max_tokens=1200)
            except (LlmError, LlmOutputError) as exc:
                log.warning("player 日程失败 %s: %s", c.name, exc)
            except Exception:
                log.exception("player 日程异常")
        final = _validated(sched, world.day)
        c.schedule = final.model_dump()
        c.schedule_day = world.day
        session.add(c)


def _validated(sched: DailySchedule | None, day: int) -> DailySchedule:
    if sched is not None and sched.is_valid_coverage():
        return sched
    if sched is not None:
        log.info("日程校验失败（块数 %d），使用默认模板", len(sched.blocks))
    return default_schedule(day)


async def _yesterday_reflections(session: AsyncSession, c: Character, world) -> list[str]:
    rows = (
        await session.exec(
            select(Memory)
            .where(
                col(Memory.character_id) == c.id,
                col(Memory.kind) == "reflection",
                col(Memory.day) == world.day - 1,
            )
            .order_by(col(Memory.importance).desc())
            .limit(3)
        )
    ).all()
    return [m.text for m in rows]


async def _top_relations(session: AsyncSession, c: Character) -> list[dict]:
    from ..models import Relationship

    rows = (
        await session.exec(
            select(Relationship)
            .where(col(Relationship.from_id) == c.id)
            .order_by(col(Relationship.affinity).desc())
            .limit(3)
        )
    ).all()
    out = []
    for r in rows:
        other = next((x for x in (await _all_chars(session)) if x.id == r.to_id), None)
        if other:
            out.append({"name": other.name, "affinity": r.affinity, "tags": list(r.tags or [])[:3]})
    return out


_char_cache: list[Character] = []


async def _all_chars(session: AsyncSession) -> list[Character]:
    global _char_cache
    if not _char_cache:
        _char_cache = list((await session.exec(select(Character))).all())
    return _char_cache


def _brief(c: Character) -> str:
    try:
        return PersonaFile.model_validate(c.persona).brief()
    except Exception:
        return f"{c.name}：一位同学。"


def _identity(c: Character) -> str:
    p = c.persona or {}
    ci = p.get("campus_identity") or {}
    major = ci.get("major", "")
    grade = ci.get("grade", "")
    club = ci.get("club")
    return f"{major} {grade}" + (f" · {club}" if club else "")


# ─────────────────────────── 8.2 maybe_pull_hot ───────────────────────────


async def maybe_pull_hot(session: AsyncSession, world, *, force: bool = False) -> int:
    """距上次 ≥60 real min 且今日 <24 次 → 拉热榜转译。返回新建事件数。"""
    from ..zhihu.client import quota_count
    from ..zhihu.content import hot_list

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = bj_today()
    used = await quota_count(session, "hot_list", today)

    if not force:
        if used >= settings.hot_daily_cap:
            return 0
        last = world.state.last_hot_pull_at
        if last is not None and (now - last) < timedelta(minutes=settings.hot_pull_interval_min):
            return 0

    try:
        items = await hot_list(limit=30, session=session)
    except Exception as exc:
        log.info("热榜拉取失败（跳过，不重试）: %s", exc)
        return 0

    if not items:
        return 0

    llm = get_llm()
    events_out: list[Any] = []
    if not llm.offline:
        active_titles = [e.title for e in world.active_events]
        ctx = {
            "hot_items": [
                f"H{i + 1} {it.get('title', '')} — {(it.get('summary') or '')[:80]} — {it.get('url', '')}"
                for i, it in enumerate(items[:30])
            ],
            "locations": [
                {
                    "id": lid,
                    "name": l.name,
                    "kind": getattr(l, "kind", "") or "",
                    "tags": list(getattr(l, "affordances", None) or [])[:4],
                }
                for lid, l in world.locations.items()
            ],
            "active_titles": active_titles,
            "day_label": world.time_label(),
            "weather": (world.weather or {}).get("text", ""),
        }
        try:
            out = await llm.json("cheap", "env_hot_events", ctx, HotEvents, max_tokens=2000)
            events_out = out.events
        except (LlmError, LlmOutputError) as exc:
            log.warning("热榜转译失败: %s", exc)
        except Exception:
            log.exception("热榜转译异常")

    if not events_out:
        return 0

    created = 0
    index_map = {f"H{i + 1}": items[i] for i in range(min(len(items), 30))}
    active_titles = [e.title for e in world.active_events]

    for he in events_out[:5]:
        src = index_map.get(he.source_index)
        if src is None:
            continue          # 映射失败丢弃
        if _similar_title(he.title, active_titles):
            continue          # 与 active 相似丢弃
        loc_id = he.location_id if get_location(he.location_id) else "field"
        start = world.tick + 1
        ev = WorldEvent(
            id=new_id("e_"), kind="hot", title=he.title[:30],
            description=he.description[:120], location_id=loc_id,
            start_tick=start, end_tick=start + max(4, min(12, he.duration_ticks)),
            tags=normalize_tags(list(he.tags)),
            source_title=(src.get("title") or "")[:80],
            source_url=content_filter.sanitize_url(src.get("url")),
            status="scheduled",
        )
        session.add(ev)
        # sys_broadcast 发 notice，带 source
        wall_text = he.wall_post or he.title
        ok, _ = content_filter.check_text(wall_text)
        if ok:
            post = PostModel(
                id=new_id("p_"), board="notice", author_id="sys_broadcast",
                text=wall_text[:500], tick=world.tick, day=world.day,
                source_title=ev.source_title, source_url=ev.source_url, event_id=ev.id,
            )
            session.add(post)
            world.note_new_post(post)
            ev.post_id = post.id
            world.emit(
                make_event("post_created", world.tick, world.day, {"post_id": post.id},
                           actor_id="sys_broadcast", location_id=loc_id)
            )
        active_titles.append(ev.title)
        created += 1

    if created:
        world.state.last_hot_pull_at = now
        world.state.hot_pull_count_today += 1
        await session.flush()
        await _inject_interest(session, world, created)
        await world.reload_active_events()
        await session.commit()
        log.info("热榜转译：新建 %d 个事件", created)
    return created


def _similar_title(title: str, others: list[str]) -> bool:
    t = title.strip()
    for o in others:
        if not o:
            continue
        if t in o or o in t:
            return True
    return False


async def _inject_interest(session: AsyncSession, world, _count: int) -> None:
    """对 tags ∩ interests[:5] 的清醒角色写 event 记忆(5)，按 weight 降序 ≤6 人。"""
    candidates: list[tuple[float, Character, list[str]]] = []
    for c in world.awake_characters():
        if c.kind == "system":
            continue
        try:
            p = PersonaFile.model_validate(c.persona)
        except Exception:
            continue
        my_topics = {normalize_tags([i.topic])[0] if i.topic else "" for i in p.interests[:5]}
        my_topics = {t for t in my_topics if t}
        for ev in world.active_events:
            if ev.status != "scheduled" and ev.start_tick <= world.tick:
                continue
            tags = set(normalize_tags(list(ev.tags or [])))
            if tags & my_topics:
                top_weight = max(
                    (i.weight for i in p.interests[:5] if normalize_tags([i.topic])[0] in tags),
                    default=0.0,
                )
                candidates.append((top_weight, c, [ev.title, ev.id]))
    candidates.sort(key=lambda x: x[0], reverse=True)
    for _w, c, payload in candidates[: settings.event_interest_inject_max]:
        mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                    kind="event", text=f"听说{payload[0]}", importance=5, ref_id=payload[1],
                    extra_keywords=[payload[0]])


# ─────────────────────────── 事件状态机（§5.3）───────────────────────────


async def roll_events(session: AsyncSession, world) -> None:
    """scheduled→active（emit event_started）；active→ended（emit event_ended）。"""
    from ..models import WorldEvent as WE

    rows = (
        await session.exec(
            select(WE).where(col(WE.status).in_(["scheduled", "active"]))
        )
    ).all()

    for ev in rows:
        if ev.status == "scheduled" and ev.start_tick <= world.tick < ev.end_tick:
            ev.status = "active"
            session.add(ev)
            world.emit(
                make_event("event_started", world.tick, world.day,
                           {"event": _event_payload(ev)}, location_id=ev.location_id)
            )
        elif ev.status in ("scheduled", "active") and world.tick >= ev.end_tick:
            ev.status = "ended"
            session.add(ev)
            world.emit(
                make_event("event_ended", world.tick, world.day,
                           {"event": _event_payload(ev)}, location_id=ev.location_id)
            )
    await session.flush()
    await world.reload_active_events()


def _event_payload(ev: WorldEvent) -> dict[str, Any]:
    return {
        "id": ev.id, "kind": ev.kind, "title": ev.title, "description": ev.description,
        "location_id": ev.location_id, "start_tick": ev.start_tick, "end_tick": ev.end_tick,
        "tags": list(ev.tags or []), "source_title": ev.source_title,
        "source_url": ev.source_url, "status": ev.status,
    }


# ─────────────────────────── 8.3 briefing（23:30）───────────────────────────


async def briefing(session: AsyncSession, world) -> Briefing:
    day = world.day
    dialogues = await _count_dialogues(session, day)
    posts = await _count_posts(session, day)
    comments = await _count_comments(session, day)
    top_posts = await _top_posts(session, day)
    events = [e.title for e in world.active_events]

    llm = get_llm()
    text = ""
    if not llm.offline:
        ctx = {
            "day_label": world.time_label(),
            "weather": world.weather,
            "stats": {"dialogues": dialogues, "posts": posts, "comments": comments},
            "top_posts": top_posts,
            "events": events,
            "notable": await _notable(session, world),
        }
        try:
            out = await llm.json("cheap", "env_briefing", ctx, Briefing, max_tokens=400)
            text = out.text
        except (LlmError, LlmOutputError) as exc:
            log.warning("简报生成失败: %s", exc)
        except Exception:
            log.exception("简报生成异常")

    if not text:
        text = f"第{day}天，{world.weather.get('text', '')}。校园里发生了{dialogues}场对话、{posts}条新帖。"

    ok, _ = content_filter.check_text(text)
    if not ok:
        text = f"第{day}天，校园里发生了{dialogues}场对话、{posts}条新帖。"

    world.state.last_briefing = {"day": day, "text": text[:150]}
    world.emit(
        make_event("briefing", world.tick, world.day, {"day": day, "text": text[:150]})
    )
    return Briefing(text=text[:150])


async def _count_dialogues(session: AsyncSession, day: int) -> int:
    from ..models import Dialogue
    from sqlalchemy import func

    row = (
        await session.exec(
            select(func.count()).select_from(Dialogue).where(col(Dialogue.day) == day)
        )
    ).one()
    return int(row[0] if isinstance(row, tuple) else row)


async def _count_posts(session: AsyncSession, day: int) -> int:
    from sqlalchemy import func

    row = (
        await session.exec(
            select(func.count()).select_from(Post)
            .where(col(Post.day) == day, col(Post.deleted) == False)  # noqa: E712
        )
    ).one()
    return int(row[0] if isinstance(row, tuple) else row)


async def _count_comments(session: AsyncSession, day: int) -> int:
    from sqlalchemy import func

    from ..models import Comment

    row = (
        await session.exec(
            select(func.count()).select_from(Comment)
            .where(col(Comment.day) == day, col(Comment.deleted) == False)  # noqa: E712
        )
    ).one()
    return int(row[0] if isinstance(row, tuple) else row)


async def _top_posts(session: AsyncSession, day: int) -> list[str]:
    rows = (
        await session.exec(
            select(Post)
            .where(col(Post.day) == day, col(Post.deleted) == False)  # noqa: E712
            .order_by(col(Post.like_count).desc())
            .limit(3)
        )
    ).all()
    return [f"（{p.like_count}赞）{(p.text or '')[:60]}" for p in rows]


async def _notable(session: AsyncSession, world) -> list[str]:
    from ..models import Relationship

    rows = (
        await session.exec(
            select(Relationship)
            .where(col(Relationship.affinity_delta_today) != 0)
            .order_by(col(Relationship.affinity_delta_today).desc())
            .limit(3)
        )
    ).all()
    out = []
    for r in rows:
        frm = world.display_name(r.from_id)
        to = world.display_name(r.to_id)
        sign = "+" if r.affinity_delta_today > 0 else ""
        out.append(f"{frm} 和 {to} 好感 {sign}{r.affinity_delta_today}")
    return out


__all__ = ["new_day", "maybe_pull_hot", "roll_events", "briefing", "bj_today", "_broadcast"]
