"""启动时的世界预置：seeds → NPC → 评委账号 → warmup。"""

from __future__ import annotations

import logging

from sqlmodel import col, select

from .constants import WAKE_MINUTE
from .db import session_scope
from .models import Character, Persona, User, WorldState, new_id, now_utc
from .schemas.domain import PersonaFile
from .security import encrypt_token
from .seeds import judge_by_username, judges, location_map, system_character, npcs
from .sim.world import get_world, reset_world

log = logging.getLogger("pc.bootstrap")


async def bootstrap_world() -> None:
    """幂等预置。多次调用安全。"""
    await _ensure_world_state()
    world = await get_world()
    await _ensure_judges(world)
    await world.reload_characters()
    log.info("世界预置完成：%d 个角色", len(world.characters))


async def _ensure_world_state() -> None:
    from .models import WorldState as WS

    async with session_scope() as session:
        state = (await session.exec(select(WS).where(WS.id == 1))).first()
        if state is None:
            session.add(
                WS(id=1, day=1, minute_of_day=WAKE_MINUTE, weekday=1, tick=0,
                   weather={"kind": "sunny", "temp_c": 23, "text": "开学第一周，天气还不错"},
                   speed_mode="idle")
            )
            await session.commit()
            log.info("已初始化 world_state")


async def _ensure_judges(world) -> None:
    """启动时若对应 user 不存在则创建 user + persona + player 角色（08 §5）。"""
    from .config import settings

    accounts = settings.judge_account_map
    if not accounts:
        return

    async with session_scope() as session:
        for username, _pw in accounts.items():
            seed = judge_by_username(username)
            if seed is None:
                log.warning("judges.json 缺少账号 %s", username)
                continue
            user_id = f"u_judge_{username}"
            existing = (
                await session.exec(select(User).where(User.judge_username == username))
            ).first()
            if existing is not None:
                continue

            try:
                persona_file = PersonaFile.model_validate(seed["persona"])
            except Exception as exc:
                log.error("评委 %s 人格非法: %s", username, exc)
                continue

            user = User(
                id=user_id,
                display_name=seed.get("display_name", username),
                avatar_key=seed.get("avatar_key", "av_01"),
                auth_kind="judge",
                is_judge=True,
                judge_username=username,
            )
            session.add(user)
            session.add(
                Persona(id=new_id("pe_"), user_id=user_id, file=persona_file.model_dump(),
                        thin=False, version=1, confirmed_at=now_utc(),
                        source_stats={"contents": 0, "followees": 0, "favlists": 0,
                                      "saved_items": 0, "failed": ["judge-preset"]})
            )
            char_id = f"pl_{username}"
            session.add(
                Character(
                    id=char_id, kind="player", user_id=user_id, name=seed["display_name"],
                    avatar_key=seed.get("avatar_key", "av_01"),
                    persona=persona_file.model_dump(),
                    location_id="library", activity="刚被投放到校园",
                    is_asleep=False, deployed_at_tick=0,
                    schedule_day=0,
                )
            )
            log.info("已预置评委 %s → %s", username, char_id)
        await session.commit()


async def reseed() -> None:
    """清库重载 seeds（仅 DEV）。"""
    from sqlalchemy import delete

    from .models import (
        Comment, Dialogue, Event, Like, LlmUsage, Memory, Message,
        Post, Relationship, Report, Whisper, WorldEvent, ZhihuCache,
    )

    async with session_scope() as session:
        for model in (
            Comment, Like, Message, Dialogue, Whisper, Report, Memory,
            Relationship, Post, WorldEvent, Event, LlmUsage, ZhihuCache,
        ):
            await session.execute(delete(model))
        chars = (await session.exec(select(Character))).all()
        for c in chars:
            await session.delete(c)
        state = (await session.exec(select(WorldState).where(WorldState.id == 1))).first()
        if state is not None:
            state.day = 1
            state.minute_of_day = WAKE_MINUTE
            state.weekday = 1
            state.tick = 0
            state.degraded = False
            state.llm_fail_streak = 0
            state.admin_override = None
            state.remaining_ticks = 0
            state.last_briefing = None
            state.hot_pull_count_today = 0
            session.add(state)
        await session.commit()

    from .seeds import reload_all as reload_seeds

    reload_seeds()
    await reset_world()
    await bootstrap_world()
    log.info("reseed 完成")


__all__ = ["bootstrap_world", "reseed"]
