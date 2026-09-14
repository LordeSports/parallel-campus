"""世界状态与快照（spec/04 §1、§2）。

`World` 是内存中的单例视图，持有：
- `state`: WorldState 行（时间、天气、速率、degraded）
- `characters`: id → Character
- `locations`: seeds
- 本 tick 的中间产物（decisions / dialogues / 新建帖）

所有落库在 tick 末由 `persist()` 一次事务提交。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..constants import (
    DAY_START_MINUTE,
    MAX_MINUTE_OF_DAY,
    MINUTES_PER_TICK,
    REFLECT_MINUTE,
    SLEEP_MINUTE,
    TICKS_PER_DAY,
    WAKE_MINUTE,
    time_label as fmt_time_label,
    tick_of,
)
from ..db import get_engine, session_scope
from ..models import (
    CampusLocation,
    Character,
    Event,
    Post,
    Relationship,
    WorldEvent,
    WorldState,
    new_id,
    now_utc,
)
from ..schemas.domain import DailySchedule, Location
from ..schemas.events import SseEvent
from ..seeds import get_location, location_map, locations as seed_locations
from .bus import bus

log = logging.getLogger("pc.world")

DEFAULT_WEATHER = {"kind": "sunny", "temp_c": 22, "text": "晴朗，风里有桂花的味道"}


class World:
    """内存世界视图。每进程一个（`get_world()`），由 Ticker 独占驱动。"""

    def __init__(self, state: WorldState) -> None:
        self.state = state
        self.characters: dict[str, Character] = {}
        self.locations: dict[str, Location] = location_map()
        self.active_events: list[WorldEvent] = []
        # 本 tick 中间产物
        self._new_posts: list[Post] = []
        self._new_relationships: dict[tuple[str, str], Relationship] = {}

    # ─────────────── 载入 / 初始化 ───────────────

    @classmethod
    async def load_or_seed(cls) -> World:
        async with session_scope() as session:
            state = (await session.exec(select(WorldState).where(WorldState.id == 1))).first()
            if state is None:
                state = WorldState(
                    id=1,
                    day=1,
                    minute_of_day=WAKE_MINUTE,
                    weekday=1,
                    tick=tick_of(1, WAKE_MINUTE),
                    weather=dict(DEFAULT_WEATHER),
                    speed_mode="idle",
                )
                session.add(state)
                await session.commit()
                await session.refresh(state)

        world = cls(state)
        await world.reload_locations()
        await world.reload_characters()
        await world.reload_active_events()

        if not any(c.kind == "npc" for c in world.characters.values()):
            await world.seed_npcs()
        await world.seed_events_for_day()
        return world

    async def reload_characters(self) -> None:
        async with session_scope() as session:
            rows = (await session.exec(select(Character))).all()
        self.characters = {c.id: c for c in rows}

    async def reload_locations(self, session: AsyncSession | None = None) -> None:
        """加载管理员地点覆盖；没有覆盖的地点沿用种子布局。"""
        if session is None:
            async with session_scope() as s:
                rows = (await s.exec(select(CampusLocation).where(CampusLocation.is_active == True))).all()  # noqa: E712
        else:
            rows = (await session.exec(select(CampusLocation).where(CampusLocation.is_active == True))).all()
        merged = location_map()
        for row in rows:
            try:
                merged[row.id] = Location.model_validate({
                    "id": row.id, "name": row.name, "emoji": row.emoji,
                    "x": row.x, "y": row.y, "w": row.w, "h": row.h,
                    "outdoor": row.outdoor, "description": row.description,
                    "affordances": row.affordances or [], "ambience": row.ambience or {},
                    "capacity": row.capacity,
                })
            except Exception:
                log.warning("跳过非法管理员地点 %s", row.id)
        self.locations = merged

    async def reload_active_events(self, session: AsyncSession | None = None) -> None:
        """刷新内存中的进行中事件。

        传入 `session` 时复用它（调用方正处于一个跨 tick 的长事务里，
        另开连接会在 SQLite 上争锁）。不传则自建短会话。
        """
        if session is not None:
            rows = (
                await session.exec(
                    select(WorldEvent).where(col(WorldEvent.status) == "active")
                )
            ).all()
        else:
            async with session_scope() as s:
                rows = (
                    await s.exec(
                        select(WorldEvent).where(col(WorldEvent.status) == "active")
                    )
                ).all()
        self.active_events = list(rows)

    # ─────────────── seeds ───────────────

    async def seed_npcs(self) -> None:
        """启动时若 characters 无 NPC 则加载（08 §2）。"""
        from ..seeds import npcs, system_character

        created = 0
        async with session_scope() as session:
            existing = {c.id for c in (await session.exec(select(Character))).all()}
            # npcs() 可能已含 sys_broadcast；用 seen 去重，避免同批内重复 INSERT
            seen = set(existing)
            for entry in list(npcs()) + [system_character()]:
                if entry["id"] in seen:
                    continue
                seen.add(entry["id"])
                is_sys = entry["id"].startswith("sys_")
                ch = Character(
                    id=entry["id"],
                    kind="system" if is_sys else "npc",
                    name=entry["name"],
                    avatar_key=entry["avatar_key"],
                    persona=entry["persona"],
                    location_id=entry["start_location"],
                    activity="刚刚开始一天",
                    energy=100,
                    is_asleep=True,
                    deployed_at_tick=0,
                    schedule_day=0,
                )
                session.add(ch)
                created += 1
            if created:
                await session.commit()
        if created:
            log.info("已加载 %d 个 NPC/系统角色", created)
            await self.reload_characters()

    async def seed_events_for_day(self, session: AsyncSession | None = None) -> None:
        """把 calendar.json 中当天的 campus_events 落成 WorldEvent（幂等）。

        传入 `session` 时复用调用方事务；`Ticker.tick()` 必须这么做，
        否则会在自己持有的写事务之外再开一条写连接，SQLite 直接报锁。
        """
        from ..seeds import events_for_day

        owned = session is None
        ctx_session = session
        if owned:
            ctx = session_scope()
            ctx_session = await ctx.__aenter__()
        assert ctx_session is not None
        s = ctx_session

        try:
            day = self.state.day
            items = events_for_day(day)
            if not items:
                return
            existing = {
                e.title
                for e in (
                    await s.exec(
                        select(WorldEvent).where(col(WorldEvent.kind) == "calendar")
                    )
                ).all()
                if e.start_tick // TICKS_PER_DAY + 1 == day
            }
            added = 0
            for item in items:
                if item["title"] in existing:
                    continue
                start_min = _parse_hhmm(item["start"])
                start_tick = tick_of(day, start_min)
                s.add(
                    WorldEvent(
                        id=new_id("e_"),
                        kind="calendar",
                        title=item["title"][:30],
                        description=f"{item['title']}，地点：{self.location_name(item['location_id'])}",
                        location_id=item["location_id"],
                        start_tick=start_tick,
                        end_tick=start_tick + int(item.get("duration_ticks", 4)),
                        tags=list(item.get("tags", []))[:5],
                        status="scheduled",
                    )
                )
                added += 1
            if added and owned:
                await s.commit()
        finally:
            if owned:
                await ctx.__aexit__(None, None, None)

        await self.reload_active_events(session)
        if added:
            log.info("第%d天 载入 %d 个日历事件", day, added)

    # ─────────────── 时间 ───────────────

    @property
    def tick(self) -> int:
        return self.state.tick

    @property
    def day(self) -> int:
        return self.state.day

    @property
    def minute(self) -> int:
        return self.state.minute_of_day

    @property
    def weekday(self) -> int:
        return self.state.weekday

    def time_label(self) -> str:
        return fmt_time_label(self.day, self.minute)

    def hhmm(self) -> str:
        h, m = divmod(self.minute, 60)
        return f"{h:02d}:{m:02d}"

    @property
    def weather_kind(self) -> str:
        return (self.state.weather or {}).get("kind", "sunny")

    @property
    def weather(self) -> dict[str, Any]:
        return self.state.weather or dict(DEFAULT_WEATHER)

    def advance(self) -> bool:
        """推进 30 分钟。返回是否跨日。"""
        self.state.minute_of_day += MINUTES_PER_TICK
        self.state.tick += 1
        crossed = False
        if self.state.minute_of_day > MAX_MINUTE_OF_DAY:
            self.state.minute_of_day = DAY_START_MINUTE  # 06:00 新一天
            self.state.day += 1
            self.state.weekday = (self.state.day - 1) % 7 + 1
            crossed = True
        self.state.updated_at = now_utc()
        return crossed

    def is_new_day(self) -> bool:
        return self.minute == DAY_START_MINUTE

    def is_wake_time(self) -> bool:
        return self.minute == WAKE_MINUTE

    def is_reflect_time(self) -> bool:
        return self.minute == REFLECT_MINUTE

    def is_sleep_time(self) -> bool:
        return self.minute == SLEEP_MINUTE

    # ─────────────── 角色查询 ───────────────

    def active_characters(self) -> list[Character]:
        """参与模拟的角色（排除 system 与已注销）。"""
        return [c for c in self.characters.values() if c.is_active and c.kind != "system"]

    def awake_characters(self) -> list[Character]:
        return [
            c
            for c in self.characters.values()
            if c.is_active and c.kind != "system" and not c.is_asleep
        ]

    def occupants(self, location_id: str) -> list[Character]:
        return [
            c
            for c in self.characters.values()
            if c.is_active and c.location_id == location_id and c.kind != "system"
        ]

    def player_characters(self) -> list[Character]:
        return [c for c in self.characters.values() if c.kind == "player" and c.is_active]

    def get_character(self, cid: str) -> Character | None:
        return self.characters.get(cid)

    def display_name(self, cid: str) -> str:
        c = self.characters.get(cid)
        return c.name if c else cid

    def location_name(self, location_id: str | None) -> str:
        if not location_id:
            return "未知地点"
        loc = self.locations.get(location_id) or get_location(location_id)
        return loc.name if loc else location_id

    def location_of(self, cid: str) -> Location | None:
        c = self.characters.get(cid)
        if not c:
            return None
        return self.locations.get(c.location_id)

    def schedule_of(self, c: Character) -> DailySchedule | None:
        if not c.schedule or c.schedule_day != self.day:
            return None
        try:
            return DailySchedule.model_validate(c.schedule)
        except Exception:
            return None

    # ─────────────── 事件 ───────────────

    def emit(self, event: SseEvent) -> None:
        bus.emit(event)

    def emit_many(self, events: list[SseEvent]) -> None:
        bus.extend(events)

    def tick_payload(self, tick_seconds: float) -> dict[str, Any]:
        return {
            "tick": self.tick,
            "day": self.day,
            "minute_of_day": self.minute,
            "time_label": self.time_label(),
            "speed_mode": self.state.speed_mode,
            "tick_seconds": tick_seconds,
        }

    # ─────────────── 新帖缓存（供 stimuli 使用） ───────────────

    def note_new_post(self, post: Post) -> None:
        self._new_posts.append(post)

    def posts_since(self, tick: int) -> list[Post]:
        return [p for p in self._new_posts if p.tick > tick]

    def clear_tick_scratch(self) -> None:
        self._new_posts.clear()

    # ─────────────── 落库 ───────────────

    async def persist(self, session: AsyncSession, events: list[SseEvent]) -> None:
        """tick 末一次事务提交：世界状态 + 事件 + 角色快照。"""
        self.state.updated_at = now_utc()
        self.state.observer_count = bus.subscriber_count()
        session.add(self.state)

        for ev in events:
            session.add(
                Event(
                    id=ev.id or new_id("ev_"),
                    tick=ev.tick,
                    day=ev.day,
                    type=ev.type,
                    actor_id=ev.actor_id,
                    target_id=ev.target_id,
                    location_id=ev.location_id,
                    payload=ev.payload,
                )
            )

        for ch in self.characters.values():
            session.add(ch)

        await session.commit()
        await self.trim_events(session)

    async def trim_events(self, session: AsyncSession) -> None:
        """仅保留最近 5000 条（02 §3.10）。"""
        from sqlalchemy import delete, func

        try:
            total = (await session.exec(select(func.count()).select_from(Event))).one()
            total = int(total[0] if isinstance(total, tuple) else total)
            if total <= 5000:
                return
            cutoff_row = (
                await session.exec(
                    select(Event.tick).order_by(col(Event.tick).desc()).offset(4999).limit(1)
                )
            ).first()
            if cutoff_row is None:
                return
            cutoff = int(cutoff_row[0] if isinstance(cutoff_row, tuple) else cutoff_row)
            await session.execute(delete(Event).where(col(Event.tick) < cutoff))
            await session.commit()
        except Exception:
            log.exception("events 表清理失败（不影响主流程）")

    async def persist_reports_and_posts(self, session: AsyncSession) -> None:
        await session.commit()


def _parse_hhmm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


# ─────────────── 单例 ───────────────

_world: World | None = None


async def get_world() -> World:
    global _world
    if _world is None:
        _world = await World.load_or_seed()
    return _world


def peek_world() -> World | None:
    return _world


async def reset_world() -> World:
    global _world
    _world = await World.load_or_seed()
    return _world


def set_world(world: World | None) -> None:
    global _world
    _world = world


__all__ = [
    "World", "get_world", "peek_world", "reset_world", "set_world",
    "DEFAULT_WEATHER",
]
