"""启动时的世界预置：seeds → NPC → 评委账号 → warmup。"""

from __future__ import annotations

import logging

from sqlmodel import col, select

from .constants import WAKE_MINUTE
from .db import session_scope
from .models import Character, Persona, User, WorldState, new_id, now_utc
from .schemas.domain import PersonaFile
from .security import encrypt_token
from .seeds import location_map, system_character, npcs
from .sim.world import get_world, reset_world

log = logging.getLogger("pc.bootstrap")


async def bootstrap_world() -> None:
    """幂等预置。多次调用安全。"""
    await _ensure_world_state()
    world = await get_world()
    await world.reload_characters()
    # 可编辑校园地图：首次启动写入默认布局（已有则跳过）
    from . import campus_map

    await campus_map.ensure_default_map()
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
