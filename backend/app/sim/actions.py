"""动作落地（spec/04 §6）。

执行顺序：move → talk 配对 → post → comment → like → dm → attend → do → search_zhihu → idle。
任一动作校验失败 → 降级为 follow_schedule；敏感词命中 → 丢弃动作并写占位记忆。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..models import Character, Comment, Like, Message, Post, new_id
from ..schemas.domain import Decision, ScheduleBlock
from ..schemas.events import make_event
from ..seeds import normalize_tags
from . import filter as content_filter
from . import memory as mem_mod

log = logging.getLogger("pc.actions")

MAX_POST_LEN = 500
MAX_COMMENT_LEN = 200
MAX_DM_LEN = 200
MAX_ACTIVITY_LEN = 30
MAX_QUERY_LEN = 30


@dataclass
class ActionOutcome:
    """`apply_all` 的产物，交给 dialogue.run_all 与持久化。"""

    talk_pairs: list[tuple[Character, Character, str | None]] = field(default_factory=list)
    moved: dict[str, str] = field(default_factory=dict)          # cid → 新地点
    spoken: list[tuple[str, str]] = field(default_factory=list)   # (cid, 开场白)
    new_posts: list[Post] = field(default_factory=list)
    applied: int = 0
    filtered: int = 0
    fallback: int = 0


async def apply_all(
    session: AsyncSession,
    world,
    decisions: dict[str, Decision],
) -> ActionOutcome:
    """按固定顺序应用所有决策。返回中间产物供对话阶段使用。"""
    outcome = ActionOutcome()
    chars = {cid: world.get_character(cid) for cid in decisions}
    chars = {cid: c for cid, c in chars.items() if c is not None}

    def _skip_action(cid: str) -> None:
        pass

    # ── 1. move ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "move":
            continue
        target = d.action.location_id
        if not target or target not in world.locations or target == c.location_id:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        before = c.location_id
        c.location_id = target
        c.activity = (d.thought or f"前往{world.location_name(target)}")[:MAX_ACTIVITY_LEN]
        outcome.moved[cid] = target
        world.emit(
            make_event(
                "character_moved", world.tick, world.day,
                {"character_id": cid, "from": before, "to": target, "activity": c.activity},
                actor_id=cid, location_id=target,
            )
        )
        await _write_decision_memory(session, world, c, d, default_text=f"我去了{world.location_name(target)}")
        outcome.applied += 1

    # ── 2. talk 配对 ──
    seen_pairs: set[tuple[str, str]] = set()
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "talk":
            continue
        target = world.get_character(d.action.target_id or "")
        ok, reason = _validate_talk(world, c, target)
        if not ok:
            log.debug("talk 校验失败 %s→%s: %s", cid, d.action.target_id, reason)
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        assert target is not None
        pair = (cid, target.id)
        if pair in seen_pairs or (target.id, cid) in seen_pairs:
            outcome.applied += 1
            continue
        seen_pairs.add(pair)
        opener = d.action.text
        if opener is not None:
            ok, reason = content_filter.check_text(opener)
            if not ok:
                outcome.filtered += 1
                log.info("content_filtered", extra={"event": "content_filtered", "where": "talk"})
                opener = None
        outcome.talk_pairs.append((c, target, opener))
        outcome.spoken.append((cid, opener or ""))
        await _write_decision_memory(session, world, c, d, default_text=f"我想找{target.name}说话")
        outcome.applied += 1

    # ── 3. post ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "post":
            continue
        board = d.action.board
        text = (d.action.text or "").strip()
        if board not in ("wall", "tree_hole") or not text or len(text) > MAX_POST_LEN:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        ok, reason = content_filter.check_text(text)
        if not ok:
            outcome.filtered += 1
            log.info("content_filtered", extra={"event": "content_filtered", "where": "post"})
            mem_mod.add(
                session, character_id=cid, tick=world.tick, day=world.day,
                kind="observation", text="想说点什么，最后还是没说", importance=1,
            )
            continue

        post = Post(
            id=new_id("p_"), board=board, author_id=cid, text=text,
            tick=world.tick, day=world.day,
        )
        source = await _recent_search_source(session, world, c)
        if source:
            post.source_title, post.source_url = source
            post.text = (text + f"（来源：知乎 · {source[0]}）")[:MAX_POST_LEN]
        session.add(post)
        outcome.new_posts.append(post)
        world.note_new_post(post)
        world.emit(
            make_event("post_created", world.tick, world.day, {"post_id": post.id},
                       actor_id=cid, location_id=c.location_id)
        )
        await _write_decision_memory(session, world, c, d, default_text="我发了一条帖子", importance=4)
        outcome.applied += 1

    # ── 4. comment ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "comment":
            continue
        text = (d.action.text or "").strip()
        post = await _get_post(session, d.action.post_id)
        if post is None or post.deleted or not text or len(text) > MAX_COMMENT_LEN:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        if await _comments_today(session, cid, post.id, world.day) >= 2:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        ok, _ = content_filter.check_text(text)
        if not ok:
            outcome.filtered += 1
            continue
        comment = Comment(
            id=new_id("c_"), post_id=post.id, author_id=cid, text=text,
            tick=world.tick, day=world.day,
        )
        session.add(comment)
        post.comment_count += 1
        world.emit(
            make_event("comment_created", world.tick, world.day,
                       {"comment_id": comment.id, "post_id": post.id},
                       actor_id=cid, target_id=post.id)
        )
        await _write_decision_memory(session, world, c, d, default_text="我评论了别人的帖子", importance=3)
        outcome.applied += 1

    # ── 5. like ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "like":
            continue
        post = await _get_post(session, d.action.post_id)
        if post is None or post.deleted:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        exists = (
            await session.exec(
                select(Like).where(col(Like.post_id) == post.id, col(Like.liker_id) == cid)
            )
        ).first()
        if exists:
            outcome.applied += 1
            continue
        session.add(Like(id=new_id("lk_"), post_id=post.id, liker_id=cid, tick=world.tick))
        post.like_count += 1
        world.emit(
            make_event("like_created", world.tick, world.day,
                       {"post_id": post.id, "liker_id": cid, "like_count": post.like_count},
                       actor_id=cid, target_id=post.id)
        )
        outcome.applied += 1

    # ── 6. dm ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "dm":
            continue
        text = (d.action.text or "").strip()
        target = world.get_character(d.action.target_id or "")
        if target is None or target.kind == "system" or not text or len(text) > MAX_DM_LEN:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        ok, _ = content_filter.check_text(text)
        if not ok:
            outcome.filtered += 1
            continue
        session.add(
            Message(id=new_id("m_"), from_id=cid, to_id=target.id, text=text,
                    tick=world.tick, day=world.day, read=False)
        )
        world.emit(
            make_event("dm_sent", world.tick, world.day, {"from_id": cid, "to_id": target.id},
                       actor_id=cid, target_id=target.id)
        )
        # 双方 observation(4)，visible=false
        mem_mod.add(session, character_id=cid, tick=world.tick, day=world.day, kind="observation",
                    text=f"我给{target.name}发了条私信", importance=4, visible=False)
        mem_mod.add(session, character_id=target.id, tick=world.tick, day=world.day, kind="observation",
                    text=f"{c.name}给我发了条私信", importance=4, visible=False)
        outcome.applied += 1

    # ── 7. attend ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "attend":
            continue
        ev = next((e for e in world.active_events if e.id == d.action.event_id), None)
        if ev is None:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        before = c.location_id
        if ev.location_id:
            c.location_id = ev.location_id
        c.activity = f"参加：{ev.title}"[:MAX_ACTIVITY_LEN]
        attended = list(c.attended_event_ids or [])
        if ev.id not in attended:
            attended.append(ev.id)
        c.attended_event_ids = attended
        outcome.moved[cid] = c.location_id
        world.emit(
            make_event("character_moved", world.tick, world.day,
                       {"character_id": cid, "from": before, "to": c.location_id, "activity": c.activity},
                       actor_id=cid, target_id=ev.id, location_id=c.location_id)
        )
        mem_mod.add(session, character_id=cid, tick=world.tick, day=world.day, kind="event",
                    text=f"我去参加了{ev.title}", importance=5, ref_id=ev.id,
                    extra_keywords=[ev.title])
        outcome.applied += 1

    # ── 8. do ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "do":
            continue
        activity = (d.action.text or "").strip()
        if not activity or len(activity) > MAX_ACTIVITY_LEN:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        ok, _ = content_filter.check_text(activity)
        if not ok:
            outcome.filtered += 1
            continue
        changed = activity != c.activity
        c.activity = activity
        world.emit(
            make_event("character_activity", world.tick, world.day,
                       {"character_id": cid, "activity": activity,
                        "mood": {"valence": c.mood_valence, "arousal": c.mood_arousal}},
                       actor_id=cid, location_id=c.location_id)
        )
        if changed:
            mem_mod.add(session, character_id=cid, tick=world.tick, day=world.day,
                        kind="observation", text=f"我在{activity}", importance=2,
                        extra_keywords=[world.location_name(c.location_id)])
        outcome.applied += 1

    # ── 9. search_zhihu ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.action.type != "search_zhihu":
            continue
        query = (d.action.query or "").strip()
        if not query or len(query) > MAX_QUERY_LEN:
            outcome.fallback += 1
            await _apply_schedule_fallback(session, world, c, d)
            continue
        await _do_search(session, world, c, query)
        outcome.applied += 1

    # ── 10. idle ──
    for cid, d in decisions.items():
        if chars[cid] and d.action.type == "idle":
            outcome.applied += 1

    # ── 落 mood_delta + decision.memory ──
    for cid, d in decisions.items():
        c = chars[cid]
        if d.mood_delta is not None:
            c.mood_valence = max(-1.0, min(1.0, c.mood_valence + d.mood_delta.valence))
            c.mood_arousal = max(-1.0, min(1.0, c.mood_arousal + d.mood_delta.arousal))
        await _write_decision_memory(session, world, c, d)

    return outcome


# ─────────────────────────── 校验 ───────────────────────────


def _validate_talk(world, c: Character, target: Character | None) -> tuple[bool, str]:
    if target is None:
        return False, "目标不存在"
    if target.id == c.id:
        return False, "不能和自己说话"
    if target.kind == "system":
        return False, "广播不会聊天"
    if target.is_asleep:
        return False, "对方在睡觉"
    if target.location_id != c.location_id:
        return False, "对方不在同一个地方"
    if target.dialogue_id:
        return False, "对方正在和别人说话"
    return True, ""


async def _comments_today(session: AsyncSession, author_id: str, post_id: str, day: int) -> int:
    rows = (
        await session.exec(
            select(Comment).where(
                col(Comment.author_id) == author_id,
                col(Comment.post_id) == post_id,
                col(Comment.day) == day,
                col(Comment.deleted) == False,  # noqa: E712
            )
        )
    ).all()
    return len(rows)


async def _get_post(session: AsyncSession, post_id: str | None) -> Post | None:
    if not post_id:
        return None
    return (await session.exec(select(Post).where(Post.id == post_id))).first()


async def _recent_search_source(session: AsyncSession, world, c: Character) -> tuple[str, str] | None:
    """最近 6 tick 内该角色有 search 记忆含 source → 带 source_*（04 §6）。"""
    from ..models import Memory

    rows = (
        await session.exec(
            select(Memory)
            .where(
                col(Memory.character_id) == c.id,
                col(Memory.kind) == "search",
                col(Memory.tick) >= world.tick - 6,
            )
            .order_by(col(Memory.tick).desc())
        )
    ).all()
    for m in rows:
        text = m.text or ""
        title = getattr(m, "ref_id", None)
        url = (m.keywords or [None])[0] if m.keywords else None
        # ref_id 存 url；文本首句为标题
        if url and str(url).startswith("http"):
            clean_url = content_filter.sanitize_url(str(url))
            if clean_url:
                return (text.split("：")[0][:40] or "知乎", clean_url)
    return None


async def _do_search(session: AsyncSession, world, c: Character, query: str) -> None:
    """`zhihu_search(count=3)` → 摘要写记忆（含 top1 Title/Url）。"""
    from ..zhihu.content import zhihu_search

    try:
        items = await zhihu_search(query, count=3)
    except Exception as exc:
        log.info("search_zhihu 失败 %s: %s", query, exc)
        mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                    kind="search", text=f"我查了「{query}」，没查到什么", importance=2,
                    extra_keywords=[query])
        return

    if not items:
        mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                    kind="search", text=f"我查了「{query}」，没什么结果", importance=2,
                    extra_keywords=[query])
        return

    top = items[0]
    summary = (top.get("content_text") or "")[:80].replace("\n", " ")
    text = f"{top.get('title', query)[:30]}：{summary}"
    url = content_filter.sanitize_url(top.get("url"))
    mem = mem_mod.add(
        session, character_id=c.id, tick=world.tick, day=world.day, kind="search",
        text=text[:200], importance=4, ref_id=url if url else None,
        extra_keywords=[query] + mem_mod.keywords_of(top.get("title", "")),
    )
    # 把 url 放进 keywords[0]（供 _recent_search_source 取源）
    if url:
        kws = list(mem.keywords or [])
        kws = [url] + [k for k in kws if k != url]
        mem.keywords = kws[:8]


# ─────────────────────────── 日程兜底 ───────────────────────────


async def _apply_schedule_fallback(
    session: AsyncSession, world, c: Character, d: Decision | None = None
) -> None:
    """校验失败 → 按日程行动（04 §3）。"""
    await follow_schedule(session, world, c)


async def follow_schedule(session: AsyncSession, world, c: Character) -> str:
    """返回应用的动作类型：move / do。"""
    schedule = world.schedule_of(c)
    if schedule is None:
        from ..seeds import default_schedule

        schedule = default_schedule(world.day)
        c.schedule = schedule.model_dump()
        c.schedule_day = world.day

    block: ScheduleBlock | None = schedule.block_at(world.minute)
    if block is None:
        c.activity = "发呆"
        return "do"

    # 天气修正：rainy 且块地点 outdoor → 70% 概率改 library/canteen
    target_loc = block.location_id
    activity = block.activity
    loc = world.locations.get(target_loc)
    if world.weather_kind == "rainy" and loc is not None and loc.outdoor:
        import random

        if random.random() < 0.7:
            target_loc = "library" if c.location_id != "library" else "canteen"
            activity = "躲雨"

    if c.location_id != target_loc:
        before = c.location_id
        c.location_id = target_loc
        c.activity = f"前往{world.location_name(target_loc)}"[:MAX_ACTIVITY_LEN]
        world.emit(
            make_event("character_moved", world.tick, world.day,
                       {"character_id": c.id, "from": before, "to": target_loc,
                        "activity": c.activity},
                       actor_id=c.id, location_id=target_loc)
        )
        return "move"

    if activity != c.activity:
        c.activity = activity[:MAX_ACTIVITY_LEN]
        world.emit(
            make_event("character_activity", world.tick, world.day,
                       {"character_id": c.id, "activity": c.activity,
                        "mood": {"valence": c.mood_valence, "arousal": c.mood_arousal}},
                       actor_id=c.id, location_id=c.location_id)
        )
    return "do"


async def follow_schedule_all(session: AsyncSession, world, characters: list[Character]) -> None:
    for c in characters:
        await follow_schedule(session, world, c)
        # 日程记忆（importance 1）——只在活动变化时写，避免噪声
        if c.activity:
            mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                        kind="schedule", text=f"我在{world.location_name(c.location_id)}{c.activity}",
                        importance=1, extra_keywords=[world.location_name(c.location_id)])


async def _write_decision_memory(
    session: AsyncSession, world, c: Character, d: Decision,
    default_text: str = "", importance: int | None = None,
) -> None:
    """写 `decision.memory`；若 LLM 未提供则用 default_text 兜底。"""
    draft = d.memory
    if draft is not None and draft.text.strip():
        ok, _ = content_filter.check_text(draft.text)
        if not ok:
            return
        mem_mod.add(
            session, character_id=c.id, tick=world.tick, day=world.day,
            kind="observation", text=draft.text, importance=draft.importance,
            extra_keywords=[world.location_name(c.location_id)],
        )
        return
    if default_text:
        mem_mod.add(
            session, character_id=c.id, tick=world.tick, day=world.day,
            kind="observation", text=default_text,
            importance=importance if importance is not None else 2,
            extra_keywords=[world.location_name(c.location_id)],
        )


__all__ = [
    "apply_all", "ActionOutcome", "follow_schedule", "follow_schedule_all",
    "MAX_POST_LEN", "MAX_COMMENT_LEN", "MAX_DM_LEN",
]
