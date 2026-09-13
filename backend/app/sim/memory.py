"""记忆系统（spec/04 §7）。

写入：`text` 第一人称 ≤200；`keywords` = jieba 分词 → 去停用词 → 去重 ≤8（含在场角色名与地点名）。
检索：`score = 0.5*recency + 0.3*importance + 0.2*Jaccard(relevance)`，半衰期 1 虚拟日。
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..constants import DEFAULT_IMPORTANCE, TICKS_PER_DAY
from ..models import Character, Memory, Relationship, new_id
from ..schemas.domain import Reflection
from ..schemas.events import make_event

log = logging.getLogger("pc.memory")

MAX_KEYWORDS = 8
CANDIDATE_LIMIT = 300

# 停用词（高频无信息量词 + 常见虚词）
STOPWORDS: frozenset[str] = frozenset(
    """
的 了 是 在 和 与 也 都 就 而 及 或 一个 一些 这个 那个 这些 那些 我 你 他 她 它 我们 你们 他们
自己 什么 怎么 这样 那样 这 那 有 没有 不 很 太 更 最 还 又 再 已经 正在 会 能 要 想 说 做 去 来
一下子 一会 一点 一直 一起 之后 之前 因为 所以 但是 可是 如果 虽然 然后 就是 好像 觉得 好像 可能
啊 吧 呢 吗 呀 哦 嗯 哈哈 233 然后 其实 真的 有点 比较 非常 特别 于是 还是 只是 不过 等等
""".split()
)

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}")
_jieba = None


def _tokenize(text: str) -> list[str]:
    """jieba 分词（懒加载）；失败退回正则。"""
    global _jieba
    if _jieba is None:
        try:
            import jieba

            jieba.setLogLevel(logging.WARNING)
            _jieba = jieba
        except Exception:
            log.warning("jieba 不可用，退回正则分词")
            _jieba = False
    if _jieba:
        tokens = _jieba.lcut(text)
    else:
        tokens = _TOKEN_RE.findall(text)
    out: list[str] = []
    for t in tokens:
        t = t.strip()
        if len(t) < 2 or t in STOPWORDS:
            continue
        out.append(t)
    return out


def keywords_of(text: str, extra: Iterable[str] = ()) -> list[str]:
    """分词 → 去停用词 → 去重 ≤8；`extra` 优先（在场角色名/地点名）。"""
    out: list[str] = []
    for e in extra:
        if e and e not in out:
            out.append(e[:8])
    for t in _tokenize(text):
        if t not in out:
            out.append(t[:8])
        if len(out) >= MAX_KEYWORDS:
            break
    return out[:MAX_KEYWORDS]


# ─────────────────────────── 写入 ───────────────────────────


def build(
    *,
    character_id: str,
    tick: int,
    day: int,
    kind: str,
    text: str,
    importance: int | None = None,
    ref_id: str | None = None,
    extra_keywords: Iterable[str] = (),
    visible: bool = True,
    consumed: bool = False,
) -> Memory:
    imp = importance if importance is not None else DEFAULT_IMPORTANCE.get(kind, 3)
    return Memory(
        id=new_id("mem_"),
        character_id=character_id,
        tick=tick,
        day=day,
        kind=kind,
        text=text[:200],
        importance=max(1, min(10, imp)),
        keywords=keywords_of(text, extra_keywords),
        ref_id=ref_id,
        consumed=consumed,
        visible=visible,
    )


def add(session: AsyncSession, **kwargs: Any) -> Memory:
    mem = build(**kwargs)
    session.add(mem)
    return mem


# ─────────────────────────── 检索 ───────────────────────────


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def score(mem: Memory, now_tick: int, query: set[str]) -> float:
    recency = 0.5 ** ((now_tick - mem.tick) / TICKS_PER_DAY)
    importance = mem.importance / 10.0
    relevance = _jaccard(set(mem.keywords or []), query)
    return 0.5 * recency + 0.3 * importance + 0.2 * relevance


async def retrieve(
    session: AsyncSession,
    character_id: str,
    query_keywords: Iterable[str],
    *,
    now_tick: int,
    k: int = 8,
    include_invisible: bool = False,
) -> list[Memory]:
    """候选最近 300 条 → top-k ∪ 最近 3 条 ∪ 未消费 whisper（去重 ≤12）。"""
    stmt = (
        select(Memory)
        .where(col(Memory.character_id) == character_id)
        .order_by(col(Memory.tick).desc())
        .limit(CANDIDATE_LIMIT)
    )
    rows = list((await session.exec(stmt)).all())
    if not include_invisible:
        rows = [m for m in rows if m.visible]

    query = {kw for kw in query_keywords if kw}
    ranked = sorted(rows, key=lambda m: score(m, now_tick, query), reverse=True)

    picked: list[Memory] = []
    seen: set[str] = set()

    def _push(m: Memory) -> None:
        if m.id not in seen and len(picked) < 12:
            seen.add(m.id)
            picked.append(m)

    for m in ranked[:k]:
        _push(m)
    for m in rows[:3]:
        _push(m)
    for m in rows:
        if m.kind == "whisper" and not m.consumed:
            _push(m)
    return picked


def format_for_prompt(memories: list[Memory], day_of) -> list[str]:
    """`[第2天 20:30] 和周野聊了《三体》… (重要度6)`"""
    out: list[str] = []
    for m in memories:
        try:
            day, minute = day_of(m.tick)
            hh, mm = divmod(minute, 60)
            stamp = f"[第{day}天 {hh:02d}:{mm:02d}]"
        except Exception:
            stamp = f"[tick{m.tick}]"
        out.append(f"{stamp} {m.text} (重要度{m.importance})")
    return out


# ─────────────────────────── 观察写入（§7.3）───────────────────────────


def observation_key(world, character: Character) -> str:
    names = sorted(c.name for c in world.occupants(character.location_id) if c.id != character.id)
    return f"{character.location_id}|{','.join(names)}"


def write_observations(session: AsyncSession, world) -> int:
    """地点变化或在场角色集合变化 → 一条 observation(2)。同地点连续 tick 不重复。"""
    written = 0
    for c in world.awake_characters():
        key = observation_key(world, c)
        if key == c.last_observation_key:
            continue
        c.last_observation_key = key
        others = [
            o.name for o in world.occupants(c.location_id) if o.id != c.id
        ]
        loc_name = world.location_name(c.location_id)
        if others:
            text = f"我在{loc_name}，看见{'、'.join(others)}"
            extra = others + [loc_name]
        else:
            text = f"我在{loc_name}，只有我一个人"
            extra = [loc_name]
        add(
            session,
            character_id=c.id,
            tick=world.tick,
            day=world.day,
            kind="observation",
            text=text,
            importance=2,
            extra_keywords=extra,
        )
        written += 1
    return written


# ─────────────────────────── 关系辅助（§3.4）───────────────────────────


async def get_relationship(
    session: AsyncSession, from_id: str, to_id: str
) -> Relationship | None:
    stmt = select(Relationship).where(
        col(Relationship.from_id) == from_id, col(Relationship.to_id) == to_id
    )
    return (await session.exec(stmt)).first()


async def ensure_relationship(
    session: AsyncSession, from_id: str, to_id: str
) -> Relationship:
    rel = await get_relationship(session, from_id, to_id)
    if rel is None:
        rel = Relationship(id=new_id("rel_"), from_id=from_id, to_id=to_id)
        session.add(rel)
    return rel


def apply_affinity(rel: Relationship, delta: int) -> int:
    """clamp −100..100；同时累计当日 delta。"""
    before = rel.affinity
    rel.affinity = max(-100, min(100, rel.affinity + delta))
    rel.affinity_delta_today += rel.affinity - before
    return rel.affinity


def bump_familiarity(rel: Relationship, amount: float = 0.15) -> None:
    rel.familiarity = min(1.0, rel.familiarity + amount)


# ─────────────────────────── 反思（§7.4）───────────────────────────


def day_memories_for_reflection(memories: list[Memory], day: int) -> list[Memory]:
    """当日新增记忆 ≥3（不含 schedule / observation importance≤2）。"""
    pool = [
        m
        for m in memories
        if m.day == day
        and not (m.kind == "schedule" or (m.kind == "observation" and m.importance <= 2))
        and m.kind != "reflection"
    ]
    return sorted(pool, key=lambda m: m.importance, reverse=True)[:40]


def should_reflect(memories: list[Memory], day: int) -> bool:
    return len(day_memories_for_reflection(memories, day)) >= 3


__all__ = [
    "keywords_of", "build", "add", "retrieve", "score", "format_for_prompt",
    "write_observations", "get_relationship", "ensure_relationship",
    "apply_affinity", "bump_familiarity", "day_memories_for_reflection",
    "should_reflect", "observation_key", "STOPWORDS",
    "Reflection",
]
