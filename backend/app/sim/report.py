"""匹配报告生成（spec/04 §9）。23:30 对每个当日有对话的 player 生成一份。"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..errors import LlmError, LlmOutputError
from ..llm.gateway import get_llm
from ..models import Character, Memory, Relationship, Report, User, new_id
from ..schemas.domain import FriendEntry, MatchReport, PersonaFile
from ..schemas.events import make_event
from . import filter as content_filter
from . import memory as mem_mod

log = logging.getLogger("pc.report")

TOP_CANDIDATES = 5
MAX_MEMORIES_PER_CANDIDATE = 3


async def generate_all(session: AsyncSession, world) -> int:
    """对所有 is_active player 生成报告。返回生成份数。"""
    created = 0
    for c in world.player_characters():
        try:
            if await _generate_one(session, world, c):
                created += 1
        except Exception:
            log.exception("报告生成失败 %s", c.name)
    return created


async def _generate_one(session: AsyncSession, world, c: Character) -> bool:
    day = world.day
    rels = (
        await session.exec(
            select(Relationship)
            .where(col(Relationship.from_id) == c.id)
            .order_by(col(Relationship.affinity_delta_today).desc())
            .limit(TOP_CANDIDATES)
        )
    ).all()

    # 当日 dialogue_count>0 才生成
    if not any(r.dialogue_count > 0 and (r.affinity_delta_today != 0) for r in rels):
        return False

    candidates: list[dict[str, Any]] = []
    for r in rels:
        other = world.get_character(r.to_id)
        if other is None or (r.affinity_delta_today == 0 and r.dialogue_count == 0):
            continue
        try:
            arche = PersonaFile.model_validate(other.persona).archetype
        except Exception:
            arche = "同学"
        mems = await _related_memories(session, world, c, other)
        candidates.append({
            "character_id": other.id,
            "name": other.name,
            "archetype": arche,
            "affinity": r.affinity,
            "affinity_delta": r.affinity_delta_today,
            "tags": [str(t) for t in (r.tags or [])][:3],
            "memories": [str(m) for m in (mems or [])],
        })

    if not candidates:
        return False

    try:
        persona = PersonaFile.model_validate(c.persona)
        brief = persona.brief()
    except Exception:
        brief = f"{c.name}：一位同学。"

    report: MatchReport | None = None
    llm = get_llm()
    if not llm.offline:
        ctx = {
            "me": {"id": c.id, "name": c.name, "persona_brief": brief},
            "day_label": world.time_label(),
            "candidates": [
                {**cd, "memories": list(cd["memories"])[:3]} for cd in candidates
            ],
        }
        try:
            report = await llm.json("strong", "match_report", ctx, MatchReport, max_tokens=1200)
        except (LlmError, LlmOutputError) as exc:
            log.warning("报告 LLM 失败 %s: %s", c.name, exc)
        except Exception:
            log.exception("报告 LLM 异常")

    if report is None:
        report = _fallback_report(world, c, candidates)

    # 后处理：character_id 不在候选内 → 丢弃；全部丢弃 → 不生成
    valid_ids = {x["character_id"] for x in candidates}
    kept = [f for f in report.top_friends if f.character_id in valid_ids]
    if not kept:
        return False

    summary = report.day_summary
    ok, _ = content_filter.check_text(summary)
    if not ok:
        summary = _fallback_summary(world, c, candidates)

    payload = {
        "day_summary": summary[:200],
        "top_friends": [
            {
                "character_id": f.character_id,
                "story": (f.story or "")[:160],
                "shared_topics": list(f.shared_topics or [])[:5],
                "affinity": f.affinity,
                "affinity_delta": f.affinity_delta,
            }
            for f in kept[:3]
        ],
    }

    existing = (
        await session.exec(
            select(Report).where(col(Report.character_id) == c.id, col(Report.day) == day)
        )
    ).first()
    if existing is not None:
        existing.content = payload
        existing.generated_tick = world.tick
        session.add(existing)
    else:
        session.add(
            Report(id=new_id("r_"), character_id=c.id, day=day,
                   content=payload, generated_tick=world.tick)
        )

    world.emit(
        make_event("report_ready", world.tick, world.day, {"character_id": c.id, "day": day},
                   actor_id=c.id)
    )
    return True


async def _related_memories(session: AsyncSession, world, me: Character, other: Character) -> list[str]:
    """与对方相关的当日 dialogue/reflection 记忆，每人 ≤3 条。"""
    rows = (
        await session.exec(
            select(Memory)
            .where(
                col(Memory.character_id) == me.id,
                col(Memory.day) == world.day,
                col(Memory.kind).in_(["dialogue", "reflection"]),
            )
            .order_by(col(Memory.importance).desc())
            .limit(20)
        )
    ).all()
    out = [m.text for m in rows if other.name in (m.text or "")]
    return out[:MAX_MEMORIES_PER_CANDIDATE]


def _fallback_report(world, c: Character, candidates: list[dict]) -> MatchReport:
    top = [x for x in candidates if x["affinity_delta"] > 0][:3] or candidates[:1]
    return MatchReport(
        day_summary=_fallback_summary(world, c, candidates),
        top_friends=[
            FriendEntry(
                character_id=x["character_id"],
                story=(x["memories"][0] if x["memories"] else f"今天和{x['name']}聊了一会儿")[:160],
                shared_topics=x["tags"],
                affinity=x["affinity"],
                affinity_delta=x["affinity_delta"],
            )
            for x in top
        ],
    )


def _fallback_summary(world, c: Character, candidates: list[dict]) -> str:
    names = "、".join(x["name"] for x in candidates[:3])
    return f"你的分身今天认识了{names}，聊得还不错。"[:200]


async def get_report_view(
    session: AsyncSession, world, character: Character, day: int | None
) -> dict[str, Any] | None:
    """组装 `ReportView`（03 §6），含 is_human / zhihu_url。"""
    stmt = select(Report).where(col(Report.character_id) == character.id)
    if day is not None:
        stmt = stmt.where(col(Report.day) == day)
        row = (await session.exec(stmt)).first()
    else:
        row = (
            await session.exec(stmt.order_by(col(Report.day).desc()).limit(1))
        ).first()
    if row is None:
        return None

    content = row.content or {}
    friends: list[dict[str, Any]] = []
    for f in content.get("top_friends", []):
        other = world.get_character(f["character_id"])
        if other is None:
            continue
        is_human = other.kind == "player"
        zhihu_url = None
        if is_human and other.user_id:
            user = (
                await session.exec(select(User).where(User.id == other.user_id))
            ).first()
            if user and user.zhihu_url_token:
                zhihu_url = f"https://www.zhihu.com/people/{user.zhihu_url_token}"
        try:
            arche = PersonaFile.model_validate(other.persona).archetype
        except Exception:
            arche = ""
        friends.append({
            "character": {
                "id": other.id, "name": other.name, "avatar_key": other.avatar_key,
                "kind": other.kind, "archetype": arche,
            },
            "story": f.get("story", ""),
            "shared_topics": list(f.get("shared_topics", [])),
            "affinity": int(f.get("affinity", 0)),
            "affinity_delta": int(f.get("affinity_delta", 0)),
            "is_human": is_human,
            "zhihu_url": zhihu_url,
        })

    return {
        "day": row.day,
        "generated_tick": row.generated_tick,
        "summary": content.get("day_summary", ""),
        "top_friends": friends,
    }


__all__ = ["generate_all", "get_report_view"]
