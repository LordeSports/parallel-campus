"""单角色决策 `decide()`（spec/04 §5、spec/05 §3 P3）。

这就是「日程驱动 + LLM 中断决策」里的中断点：
- 组装 persona 摘要 / 时间天气地点 / 在场角色 / 日程 / 刺激 / 检索记忆 / 耳语
- 调 LLM 拿 `Decision`
- 失败/超时 → 返回 None（由调用方 fallback 到 follow_schedule）
"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from ..constants import energy_label, mood_label
from ..errors import LlmError, LlmOutputError
from ..llm.gateway import ACTIONS_DOC, get_llm
from ..models import Character, Memory
from ..schemas.domain import Decision, PersonaFile, Stimulus
from . import memory as mem_mod

log = logging.getLogger("pc.char_agent")

PRESENT_LIMIT = 8
MEMORY_LIMIT = 12
POST_LIMIT = 3
EVENT_LIMIT = 3


async def decide(
    session: AsyncSession,
    world,
    character: Character,
    stims: list[Stimulus],
    *,
    timeout: float | None = None,
) -> Decision | None:
    """返回 Decision；LLM 失败/输出非法时返回 None（调用方走日程兜底）。"""
    llm = get_llm()
    if llm.offline:
        return None

    persona = PersonaFile.model_validate(character.persona)

    schedule = world.schedule_of(character)
    now_block = schedule.block_at(world.minute) if schedule else None
    next_block = schedule.next_block(world.minute) if schedule else None

    present_lines = await _present_lines(session, world, character)
    memories = await _memory_lines(session, world, character, stims)

    whisper_ctx = None
    if character.pending_whisper_id:
        from sqlmodel import select

        from ..models import Whisper

        w = (
            await session.exec(select(Whisper).where(Whisper.id == character.pending_whisper_id))
        ).first()
        if w is not None:
            whisper_ctx = {"id": w.id, "text": w.text}

    loc = world.locations.get(character.location_id)
    crowd = len(world.occupants(character.location_id))
    crowd_label = "很拥挤" if loc and crowd > loc.capacity else ("有点热闹" if crowd > 4 else "没什么人")

    ctx: dict[str, Any] = {
        "me": {
            "id": character.id,
            "name": character.name,
            "persona_brief": persona.brief(),
            "identity": (
                f"{persona.campus_identity.major} {persona.campus_identity.grade}"
                + (f" · {persona.campus_identity.club}" if persona.campus_identity.club else "")
            ),
            "mood_label": mood_label(character.mood_valence, character.mood_arousal),
            "energy_label": energy_label(character.energy),
        },
        "now": {
            "time_label": world.time_label(),
            "weather_text": world.weather.get("text", ""),
            "location": {
                "name": world.location_name(character.location_id),
                "ambience": loc.ambience_text(world.minute, world.weather_kind) if loc else "",
                "crowd_label": crowd_label,
            },
            "weekday_label": f"周{world.weekday}",
        },
        "present": present_lines,
        "schedule_now": _block_text(now_block),
        "schedule_next": _block_text(next_block),
        "stimuli": [s.text for s in stims[:3]],
        "memories": memories,
        "active_events": [
            f"{e.title} @{world.location_name(e.location_id)}"
            for e in world.active_events[:EVENT_LIMIT]
        ],
        "recent_posts": _recent_posts(world, character)[:POST_LIMIT],
        "whisper": whisper_ctx,
        "actions_doc": ACTIONS_DOC,
        "locations": [{"id": lid, "name": l.name} for lid, l in world.locations.items()],
    }

    tier = "strong" if character.kind == "player" else "cheap"
    try:
        decision = await llm.json(tier, "decide", ctx, Decision, timeout=timeout, max_tokens=900)
    except (LlmError, LlmOutputError) as exc:
        log.warning("decide 失败 %s: %s", character.name, exc)
        return None
    except Exception:
        log.exception("decide 未知异常 %s", character.name)
        return None

    # 有耳语刺激但输出缺 whisper_response → accepted=false（04 §5）
    if character.pending_whisper_id and decision.whisper_response is None:
        from ..schemas.domain import WhisperResponse

        decision.whisper_response = WhisperResponse(accepted=False, reason="刚才没注意到")
    return decision


async def _present_lines(session: AsyncSession, world, character: Character) -> list[str]:
    """在场角色，格式里**必须带 id**：talk/dm 要填 target_id（04 §5）。"""
    out: list[str] = []
    for other in world.occupants(character.location_id):
        if other.id == character.id:
            continue
        rel = await mem_mod.get_relationship(session, character.id, other.id)
        try:
            other_persona = PersonaFile.model_validate(other.persona)
            arche = other_persona.archetype
        except Exception:
            arche = "同学"
        if rel and rel.tags:
            tail = "、".join(rel.tags[:3])
        else:
            tail = "还不熟"
        affinity = rel.affinity if rel else 0
        out.append(f"{other.name}（id={other.id}；{arche}；你对TA好感{affinity}，{tail}）")
        if len(out) >= PRESENT_LIMIT:
            break
    return out


async def _memory_lines(
    session: AsyncSession, world, character: Character, stims: list[Stimulus]
) -> list[str]:
    from ..constants import decompose_tick

    query: list[str] = [world.location_name(character.location_id)]
    for o in world.occupants(character.location_id):
        if o.id != character.id:
            query.append(o.name)
    for s in stims:
        query.extend(mem_mod.keywords_of(s.text))
    schedule = world.schedule_of(character)
    block = schedule.block_at(world.minute) if schedule else None
    if block:
        query.extend(mem_mod.keywords_of(block.activity))

    from ..config import settings

    rows = await mem_mod.retrieve(
        session, character.id, query, now_tick=world.tick, k=settings.memory_retrieve_k
    )
    return mem_mod.format_for_prompt(rows, decompose_tick)


def _recent_posts(world, character: Character) -> list[str]:
    out: list[str] = []
    for p in reversed(world.posts_since(world.tick - 1)):
        if p.author_id == character.id:
            continue
        author = p.author_label or world.display_name(p.author_id or "")
        head = (p.text or "")[:60].replace("\n", " ")
        out.append(f"{p.id}｜{author}｜{head}")
    return out


def _block_text(block) -> str | None:
    if block is None:
        return None
    return f"{block.start}-{block.end} 在{block.location_id} {block.activity}"


__all__ = ["decide"]
