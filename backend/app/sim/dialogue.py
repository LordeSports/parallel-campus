"""对话生成与落地（spec/04 §6.2）。

配对 → 单次 LLM 生成 4..8 轮 → 关系更新 → 逐轮事件。
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..constants import decompose_tick, mood_label
from ..errors import LlmError, LlmOutputError
from ..llm.gateway import get_llm
from ..models import Character, Dialogue, Relationship, new_id
from ..schemas.domain import DialogueModel, DialogueSide, PersonaFile, ScheduleBlock
from ..schemas.events import make_event
from . import filter as content_filter
from . import memory as mem_mod

log = logging.getLogger("pc.dialogue")

MAX_DIALOGUES_PER_PAIR_PER_DAY = 3
FALLBACK_DELTA = 2


@dataclass
class PairJob:
    a: Character
    b: Character
    opener: str | None


async def run_all(
    session: AsyncSession,
    world,
    outcome,
) -> list[tuple[Character, str]]:
    """执行所有 talk 配对。返回 [(想聊但对方在忙的角色, 对方名)] 供调用方写记忆。"""
    jobs, busy_notes = _pair_up(session, world, outcome)
    if not jobs:
        return busy_notes

    async def _one(job: PairJob):
        try:
            await _run_pair(session, world, job)
        except Exception:
            log.exception("对话生成失败 %s ↔ %s", job.a.name, job.b.name)

    sem = asyncio.Semaphore(max(1, settings.max_concurrent_llm // 2))
    fast = world.state.speed_mode == "fast_forward"

    async def _guarded(job: PairJob):
        async with sem:
            await _one(job)
            if not fast:
                # 逐轮事件已在 _run_pair 内发出；这里仅让 online 模式有呼吸感
                pass

    await asyncio.gather(*(_guarded(j) for j in jobs))
    return busy_notes


def _pair_up(session, world, outcome) -> tuple[list[PairJob], list[tuple[Character, str]]]:
    """池中 (a→b)；若 b 也 talk(a) 合并；b 已在其他对话 → a 得记忆。(同步部分复用 outcome)"""
    raw: list[tuple[Character, Character, str | None]] = outcome.talk_pairs
    jobs: list[PairJob] = []
    busy: list[tuple[Character, str]] = []
    used: set[str] = set()
    claimed: set[tuple[str, str]] = set()

    for a, b, opener in raw:
        key = tuple(sorted((a.id, b.id)))
        if key in claimed:
            continue
        if a.id in used:
            busy.append((a, b.name))
            continue
        if b.id in used or b.dialogue_id:
            a.activity = "等人"[:30]
            busy.append((a, b.name))
            continue
        claimed.add(key)
        used.add(a.id)
        used.add(b.id)
        jobs.append(PairJob(a, b, opener))
    return jobs, busy


async def _run_pair(session: AsyncSession, world, job: PairJob) -> None:
    a, b = job.a, job.b

    if await _pair_dialogues_today(session, a.id, b.id, world.day) >= MAX_DIALOGUES_PER_PAIR_PER_DAY:
        return

    a_persona = _persona(a)
    b_persona = _persona(b)
    rel_ab = await mem_mod.get_relationship(session, a.id, b.id)
    rel_ba = await mem_mod.get_relationship(session, b.id, a.id)

    mems_a = await _related_memories(session, world, a, b)
    mems_b = await _related_memories(session, world, b, a)

    loc = world.locations.get(a.location_id)
    tier = "strong" if (a.kind == "player" or b.kind == "player") else "cheap"

    ctx = {
        "a": {"id": a.id, "name": a.name, "persona_brief": a_persona.brief(),
              "mood_label": mood_label(a.mood_valence, a.mood_arousal)},
        "b": {"id": b.id, "name": b.name, "persona_brief": b_persona.brief(),
              "mood_label": mood_label(b.mood_valence, b.mood_arousal)},
        "relation_ab": _rel_ctx(rel_ab),
        "relation_ba": _rel_ctx(rel_ba),
        "scene": {
            "time_label": world.time_label(),
            "location_name": world.location_name(a.location_id),
            "ambience": loc.ambience_text(world.minute, world.weather_kind) if loc else "",
            "weather_text": world.weather.get("text", ""),
        },
        "opener": job.opener,
        "memories_a": mems_a,
        "memories_b": mems_b,
        "events": [e.title for e in world.active_events[:2]],
        "max_turns": settings.dialogue_max_turns,
    }

    dlg: DialogueModel | None = None
    try:
        dlg = await get_llm().json(tier, "dialogue", ctx, DialogueModel,
                                   timeout=settings.llm_timeout + 10, max_tokens=1400)
    except (LlmError, LlmOutputError) as exc:
        log.warning("对话 LLM 失败 %s ↔ %s: %s", a.name, b.name, exc)
    except Exception:
        log.exception("对话 LLM 异常")

    if dlg is None:
        await _fallback_greeting(session, world, a, b, rel_ab, rel_ba)
        return

    # 清洗 turns：交替、≤60 字、4..8 轮
    turns = _normalize_turns(dlg, a, b)
    if len(turns) < 2:
        await _fallback_greeting(session, world, a, b, rel_ab, rel_ba)
        return

    dialogue_id = new_id("d_")
    is_player = a.kind == "player" or b.kind == "player"

    row = Dialogue(
        id=dialogue_id, tick=world.tick, day=world.day, location_id=a.location_id,
        a_id=a.id, b_id=b.id,
        turns=turns,
        a_to_b_delta=dlg.a_to_b.affinity_delta,
        b_to_a_delta=dlg.b_to_a.affinity_delta,
        ended_because=(dlg.ended_because or "")[:20],
        tier=tier, is_player_involved=is_player,
    )
    session.add(row)
    a.dialogue_id = dialogue_id
    b.dialogue_id = dialogue_id
    a.activity = f"和{b.name}聊天"[:30]
    b.activity = f"和{a.name}聊天"[:30]

    world.emit(
        make_event("dialogue_started", world.tick, world.day,
                   {"dialogue_id": dialogue_id, "a_id": a.id, "b_id": b.id,
                    "location_id": a.location_id},
                   actor_id=a.id, target_id=b.id, location_id=a.location_id)
    )

    await _emit_turns(world, dialogue_id, turns)

    world.emit(
        make_event("dialogue_ended", world.tick, world.day,
                   {"dialogue_id": dialogue_id, "a_id": a.id, "b_id": b.id,
                    "a_to_b_delta": dlg.a_to_b.affinity_delta,
                    "b_to_a_delta": dlg.b_to_a.affinity_delta,
                    "ended_because": row.ended_because},
                   actor_id=a.id, target_id=b.id, location_id=a.location_id)
    )

    # 关系更新
    await _apply_relationship(session, world, a, b, rel_ab, dlg.a_to_b)
    await _apply_relationship(session, world, b, a, rel_ba, dlg.b_to_a)

    # 记忆（含对方名字与话题关键词）
    _write_side_memory(session, world, a, b, dlg.a_to_b)
    _write_side_memory(session, world, b, a, dlg.b_to_a)

    # 心情
    a.mood_valence = _clamp(a.mood_valence + dlg.mood_a.valence)
    a.mood_arousal = _clamp(a.mood_arousal + dlg.mood_a.arousal)
    b.mood_valence = _clamp(b.mood_valence + dlg.mood_b.valence)
    b.mood_arousal = _clamp(b.mood_arousal + dlg.mood_b.arousal)


async def _emit_turns(world, dialogue_id: str, turns: list[dict]) -> None:
    """online 模式按 tick_seconds/(N+1) 间隔发；fast_forward 立即。"""
    fast = world.state.speed_mode == "fast_forward"
    n = len(turns)
    delay = 0.0 if fast else max(0.0, float(settings.tick_seconds_online) / (n + 1))
    for i, t in enumerate(turns):
        world.emit(
            make_event("dialogue_turn", world.tick, world.day,
                       {"dialogue_id": dialogue_id, "index": i,
                        "speaker_id": t["speaker_id"], "text": t["text"]},
                       actor_id=t["speaker_id"])
        )
        if delay > 0 and i < n - 1:
            await asyncio.sleep(min(delay, 3.0))


def _normalize_turns(dlg: DialogueModel, a: Character, b: Character) -> list[dict]:
    valid_ids = {a.id, b.id}
    raw = []
    # 兼容 LLM 的三种 speaker_id 写法：真实 id（规范）> 角色名 > 提示词里的 A/B 标签。
    label_to_id = {
        "a": a.id, "A": a.id, "甲": a.id,
        "b": b.id, "B": b.id, "乙": b.id,
    }
    for t in dlg.turns[: settings.dialogue_max_turns]:
        raw_sid = (t.speaker_id or "").strip()
        sid = raw_sid if raw_sid in valid_ids else None
        if sid is None and raw_sid == a.name:
            sid = a.id
        elif sid is None and raw_sid == b.name:
            sid = b.id
        elif sid is None:
            sid = label_to_id.get(raw_sid)
        text = (t.text or "").strip()
        if sid is None or not text:
            continue
        ok, _ = content_filter.check_text(text)
        if not ok:
            continue
        raw.append({"speaker_id": sid, "text": text[:60]})

    if len(raw) < 2:
        return raw

    # 强制交替：连续同发言人合并（保留后者）
    out: list[dict] = []
    for t in raw:
        if out and out[-1]["speaker_id"] == t["speaker_id"]:
            out[-1]["text"] = (out[-1]["text"] + " " + t["text"])[:60]
        else:
            out.append(t)
    # 至少 4 轮：不足则补一轮对方的话
    while len(out) < 4:
        last_speaker = out[-1]["speaker_id"] if out else a.id
        other = b if last_speaker == a.id else a
        filler = random.choice(["嗯，也是。", "……你继续说。", "我想想。", "对，我也是这么想的。"])
        out.append({"speaker_id": other.id, "text": filler})
    return out[: settings.dialogue_max_turns]


async def _apply_relationship(
    session: AsyncSession, world, frm: Character, to: Character,
    rel: Relationship | None, side: DialogueSide,
) -> None:
    if rel is None:
        rel = await mem_mod.ensure_relationship(session, frm.id, to.id)
    mem_mod.apply_affinity(rel, side.affinity_delta)
    mem_mod.bump_familiarity(rel, 0.15)
    rel.last_interaction_tick = world.tick
    rel.dialogue_count += 1
    if side.tags:
        tags = list(dict.fromkeys(list(rel.tags or []) + list(side.tags)))[:5]
        rel.tags = tags
    session.add(rel)


def _write_side_memory(
    session: AsyncSession, world, me: Character, other: Character, side: DialogueSide
) -> None:
    text = (side.memory or "").strip()
    if not text or other.name not in text:
        text = f"我和{other.name}聊了一会儿"
    ok, _ = content_filter.check_text(text)
    if not ok:
        text = f"我和{other.name}聊了一会儿"
    mem_mod.add(
        session, character_id=me.id, tick=world.tick, day=world.day,
        kind="dialogue", text=text[:60], importance=6,
        extra_keywords=[other.name, world.location_name(me.location_id)] + list(side.tags or []),
    )


async def _fallback_greeting(session, world, a, b, rel_ab, rel_ba) -> None:
    """LLM 失败 → 记忆「和 X 简单打了招呼」（3），affinity +2，无 turns（04 §6.2）。"""
    for me, other, rel in ((a, b, rel_ab), (b, a, rel_ba)):
        if rel is None:
            rel = await mem_mod.ensure_relationship(session, me.id, other.id)
        mem_mod.apply_affinity(rel, FALLBACK_DELTA)
        mem_mod.bump_familiarity(rel, 0.15)
        rel.last_interaction_tick = world.tick
        rel.dialogue_count += 1
        session.add(rel)
        mem_mod.add(session, character_id=me.id, tick=world.tick, day=world.day,
                    kind="dialogue", text=f"我和{other.name}简单打了招呼", importance=3,
                    extra_keywords=[other.name])


async def _pair_dialogues_today(session: AsyncSession, a_id: str, b_id: str, day: int) -> int:
    rows = (
        await session.exec(
            select(Dialogue).where(
                col(Dialogue.day) == day,
                col(Dialogue.a_id).in_([a_id, b_id]),
                col(Dialogue.b_id).in_([a_id, b_id]),
            )
        )
    ).all()
    return len(rows)


async def _related_memories(session: AsyncSession, world, me: Character, other: Character) -> list[str]:
    rows = await mem_mod.retrieve(
        session, me.id,
        mem_mod.keywords_of(other.name) + [world.location_name(me.location_id)],
        now_tick=world.tick, k=3,
    )
    return mem_mod.format_for_prompt(rows, decompose_tick)


def _rel_ctx(rel: Relationship | None) -> dict:
    if rel is None:
        return {"affinity": 0, "familiarity_label": "刚认识", "tags": [], "last_topic": None}
    fam = rel.familiarity
    label = "刚认识" if fam < 0.3 else ("有点熟" if fam < 0.7 else "老朋友")
    return {
        "affinity": rel.affinity,
        "familiarity_label": label,
        "tags": list(rel.tags or []),
        "last_topic": None,
    }


def _persona(c: Character) -> PersonaFile:
    try:
        return PersonaFile.model_validate(c.persona)
    except Exception:
        return PersonaFile(
            display_name=c.name, archetype="同学",
            mbti_like={"E_I": 0, "S_N": 0, "T_F": 0, "J_P": 0},
            big_five={"O": 0.5, "C": 0.5, "E": 0.5, "A": 0.5, "N": 0.5},
            interests=[
                {"topic": "校园生活", "weight": 0.6, "evidence": []},
                {"topic": "校园生活", "weight": 0.5, "evidence": []},
                {"topic": "校园生活", "weight": 0.4, "evidence": []},
            ],
            summary="一位普通的同学。",
        )


def _clamp(v: float) -> float:
    return max(-1.0, min(1.0, v))


__all__ = ["run_all", "PairJob"]
