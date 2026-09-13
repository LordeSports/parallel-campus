"""刺激计算（spec/04 §4）。

每角色最多保留 salience 最高的 3 条刺激。
"""

from __future__ import annotations

import logging

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..models import Character, Message, Post, Whisper
from ..schemas.domain import Stimulus
from ..seeds import normalize_topic

log = logging.getLogger("pc.stimuli")

MAX_STIMULI = 3
NEW_FACE_RECENT_TICKS = 6


async def compute(
    session: AsyncSession, world, awake: list[Character]
) -> dict[str, list[Stimulus]]:
    """返回 {character_id: [Stimulus, ...]}（每个最多 3 条，按 salience 降序）。"""
    if not awake:
        return {}

    awake_ids = {c.id for c in awake}

    # ── 批量预取 ──
    whispers = {
        c.id: c.pending_whisper_id for c in awake if c.pending_whisper_id
    }
    whisper_rows: dict[str, Whisper] = {}
    if whispers:
        rows = (
            await session.exec(
                select(Whisper).where(col(Whisper.id).in_(list(whispers.values())))
            )
        ).all()
        whisper_rows = {w.id: w for w in rows}

    unread = (
        await session.exec(
            select(Message).where(
                col(Message.to_id).in_(list(awake_ids)), col(Message.read) == False  # noqa: E712
            )
        )
    ).all()
    unread_by_to: dict[str, list[Message]] = {}
    for m in unread:
        unread_by_to.setdefault(m.to_id, []).append(m)

    # 上一 tick 及之后的新帖
    recent_posts = world.posts_since(world.tick - 1)
    recent_comments: list[tuple[str, str, str]] = []  # (post_id, author_id, text)
    from ..models import Comment

    if recent_posts or world.tick > 0:
        try:
            crows = (
                await session.exec(
                    select(Comment)
                    .where(col(Comment.tick) >= world.tick - 1, col(Comment.deleted) == False)  # noqa: E712
                    .limit(200)
                )
            ).all()
            recent_comments = [(c.post_id, c.author_id or "", c.text) for c in crows]
        except Exception:
            log.exception("读取最近评论失败")

    active_events = list(world.active_events)

    # 同地分组
    by_location: dict[str, list[Character]] = {}
    for c in awake:
        by_location.setdefault(c.location_id, []).append(c)

    out: dict[str, list[Stimulus]] = {}

    for c in awake:
        stims: list[Stimulus] = []
        persona = c.persona or {}
        interests = persona.get("interests") or []
        my_topics = [normalize_topic(i.get("topic", "")) for i in interests[:4]]
        my_name = c.name

        # whisper（10）
        wid = c.pending_whisper_id
        if wid:
            w = whisper_rows.get(wid)
            stims.append(
                Stimulus(
                    kind="whisper",
                    ref_id=wid,
                    text=(w.text if w else "主人给你留了一句话")[:60],
                    salience=10,
                )
            )

        # dm_unread（8）
        msgs = unread_by_to.get(c.id) or []
        if msgs:
            sender = world.display_name(msgs[-1].from_id)
            stims.append(
                Stimulus(
                    kind="dm_unread",
                    ref_id=msgs[-1].id,
                    text=f"{sender}给你发了私信，你还没看",
                    salience=8,
                )
            )

        # mention（8）—— 上一 tick 新帖/评论文本含 @{name}
        token = f"@{my_name}"
        mention_ref: str | None = None
        for p in recent_posts:
            if token in (p.text or ""):
                mention_ref = p.id
                break
        if mention_ref is None:
            for post_id, _author, text in recent_comments:
                if token in (text or ""):
                    mention_ref = post_id
                    break
        if mention_ref:
            stims.append(
                Stimulus(
                    kind="mention",
                    ref_id=mention_ref,
                    text=f"有人@了你，在{'树洞' if mention_ref.startswith('p_') else '校园墙'}提到你的名字",
                    salience=8,
                )
            )

        # new_face（6，affinity≥40 → 7）
        for other in by_location.get(c.location_id, []):
            if other.id == c.id:
                continue
            rel = await _rel(session, c.id, other.id)
            familiarity = rel.familiarity if rel else 0.0
            affinity = rel.affinity if rel else 0
            last_tick = rel.last_interaction_tick if rel else None
            fresh = familiarity < 0.3 or affinity >= 20
            quiet = last_tick is None or (world.tick - last_tick) >= NEW_FACE_RECENT_TICKS
            if fresh and quiet:
                sal = 7 if affinity >= 40 else 6
                stims.append(
                    Stimulus(
                        kind="new_face",
                        ref_id=other.id,
                        text=(
                            f"{other.name}就在附近，你们只见过一两次"
                            if familiarity < 0.3
                            else f"{other.name}也在这里，你们挺聊得来"
                        )[:60],
                        salience=sal,
                    )
                )

        # event_here（6）
        for ev in active_events:
            if ev.location_id == c.location_id and ev.start_tick >= world.tick - 2:
                stims.append(
                    Stimulus(
                        kind="event_here",
                        ref_id=ev.id,
                        text=f"这里正在发生：{ev.title}"[:60],
                        salience=6,
                    )
                )
                break

        # event_interest（5）
        attended = set(c.attended_event_ids or [])
        for ev in active_events:
            if ev.id in attended:
                continue
            tags = {normalize_topic(t) for t in (ev.tags or [])}
            if tags & set(my_topics):
                stims.append(
                    Stimulus(
                        kind="event_interest",
                        ref_id=ev.id,
                        text=f"你可能会关心：{ev.title}（在{world.location_name(ev.location_id)}）"[:60],
                        salience=5,
                    )
                )
                break

        # post_relevant（4）
        my_topic_set = set(my_topics)
        for p in recent_posts:
            if p.author_id == c.id:
                continue
            kws = {normalize_topic(k) for k in _post_keywords(p)}
            if my_topic_set & kws:
                who = p.author_label or world.display_name(p.author_id or "")
                stims.append(
                    Stimulus(
                        kind="post_relevant",
                        ref_id=p.id,
                        text=f"{who}发了一条你可能感兴趣的帖：{(p.text or '')[:24]}"[:60],
                        salience=4,
                    )
                )
                break

        # crowd（2）
        loc = world.locations.get(c.location_id)
        if loc and len(world.occupants(c.location_id)) > loc.capacity:
            stims.append(
                Stimulus(
                    kind="crowd",
                    ref_id=c.location_id,
                    text=f"{loc.name}太挤了，人多得转不开身",
                    salience=2,
                )
            )

        stims.sort(key=lambda s: s.salience, reverse=True)
        out[c.id] = stims[:MAX_STIMULI]

    return out


def _post_keywords(post: Post) -> list[str]:
    text = f"{post.text or ''} {post.source_title or ''}"
    return [t for t in _split_simple(text) if t]


def _split_simple(text: str) -> list[str]:
    import re

    return re.findall(r"[\u4e00-\u9fff]{2,}", text or "")


_rel_cache: dict[tuple[str, str], object] = {}


async def _rel(session: AsyncSession, from_id: str, to_id: str):
    from ..models import Relationship

    key = (from_id, to_id)
    if key in _rel_cache:
        return _rel_cache[key]
    row = (
        await session.exec(
            select(Relationship).where(
                col(Relationship.from_id) == from_id, col(Relationship.to_id) == to_id
            )
        )
    ).first()
    _rel_cache[key] = row
    return row


def clear_cache() -> None:
    _rel_cache.clear()


def top_salience(stims: list[Stimulus]) -> int:
    return max((s.salience for s in stims), default=0)


__all__ = ["compute", "top_salience", "clear_cache", "MAX_STIMULI"]
