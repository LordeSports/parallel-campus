"""世界路由（spec/03 §4）。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Query
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .. import campus_map
from ..constants import decompose_tick, mood_label, time_label as fmt_time_label
from ..errors import NotFound
from ..models import Character, Dialogue, Event, Memory, Relationship, User
from ..schemas.domain import PersonaFile
from ..schemas.map import CampusMapView
from ..schemas.views import (
    ActiveEventView,
    BriefingView,
    CharacterDetailView,
    CharacterSummaryView,
    DialogueTurnView,
    DialogueView,
    EventView,
    IdentityView,
    LocationView,
    MemoryItemView,
    MoodView,
    RelationshipItemView,
    WeatherView,
    WorldStateView,
)
from ..sim.bus import bus
from ..sim.world import get_world
from .deps import CurrentUser, OptionalUser, SessionDep

log = logging.getLogger("pc.api.world")

router = APIRouter(prefix="/world", tags=["world"])

RECENT_MEMORY_LIMIT = 8
TOP_RELATION_LIMIT = 5


# ─────────────────────────── 视图构造 ───────────────────────────


def character_summary_view(
    world, char: Character, me_user_id: str | None = None
) -> CharacterSummaryView:
    return CharacterSummaryView(
        id=char.id,
        kind=char.kind,
        name=char.name,
        avatar_key=char.avatar_key,
        location_id=char.location_id,
        activity=char.activity or "",
        mood=MoodView(valence=char.mood_valence, arousal=char.mood_arousal),
        is_asleep=char.is_asleep,
        is_me=bool(me_user_id and char.user_id == me_user_id),
        dialogue_id=char.dialogue_id,
        energy=char.energy,
    )


def character_detail_view(
    world, char: Character, me_user_id: str | None, session: AsyncSession
) -> dict[str, Any]:
    summary = character_summary_view(world, char, me_user_id)
    try:
        persona = PersonaFile.model_validate(char.persona)
        identity = IdentityView(
            major=persona.campus_identity.major,
            grade=persona.campus_identity.grade,
            club=persona.campus_identity.club,
        )
        archetype, appearance, psummary = persona.archetype, persona.appearance, persona.summary
    except Exception:
        identity = IdentityView()
        archetype = appearance = psummary = ""

    return {
        **summary.model_dump(),
        "identity": identity.model_dump(),
        "appearance": appearance,
        "archetype": archetype,
        "summary": psummary,
        "recent_memories": [],
        "top_relationships": [],
    }


async def character_detail_full(
    world, char: Character, me_user_id: str | None, session: AsyncSession
) -> dict[str, Any]:
    """含 recent_memories / top_relationships（03 §4）。"""
    data = character_detail_view(world, char, me_user_id, session)
    is_me = bool(me_user_id and char.user_id == me_user_id)

    stmt = (
        select(Memory)
        .where(col(Memory.character_id) == char.id)
        .order_by(col(Memory.tick).desc())
        .limit(RECENT_MEMORY_LIMIT * 2)
    )
    rows = list((await session.exec(stmt)).all())
    if not is_me:
        rows = [m for m in rows if m.visible]
    data["recent_memories"] = [
        {"tick": m.tick, "kind": m.kind, "text": m.text, "importance": m.importance}
        for m in rows[:RECENT_MEMORY_LIMIT]
    ]

    rels = (
        await session.exec(
            select(Relationship)
            .where(col(Relationship.from_id) == char.id)
            .order_by(col(Relationship.affinity).desc())
            .limit(TOP_RELATION_LIMIT)
        )
    ).all()
    out = []
    for r in rels:
        other = world.get_character(r.to_id)
        if other is None or (r.affinity == 0 and not r.tags):
            continue
        out.append({
            "character_id": other.id, "name": other.name,
            "affinity": r.affinity, "tags": list(r.tags or []),
        })
    data["top_relationships"] = out
    return data


def event_view(row: Event) -> EventView:
    day, minute = decompose_tick(row.tick)
    return EventView(
        id=row.id, tick=row.tick, day=row.day, type=row.type,
        actor_id=row.actor_id, target_id=row.target_id, location_id=row.location_id,
        payload=row.payload or {}, time_label=fmt_time_label(day, minute),
    )


def active_event_view(ev) -> ActiveEventView:
    return ActiveEventView(
        id=ev.id, kind=ev.kind, title=ev.title, description=ev.description or "",
        location_id=ev.location_id, start_tick=ev.start_tick, end_tick=ev.end_tick,
        tags=list(ev.tags or []), source_title=ev.source_title,
        source_url=ev.source_url, status=ev.status,
    )


# ─────────────────────────── 路由 ───────────────────────────


@router.get("/state", response_model=WorldStateView)
async def world_state(session: SessionDep, user: OptionalUser) -> WorldStateView:
    world = await get_world()
    from ..sim.ticker import tick_period

    weather = world.weather
    briefing = None
    if world.state.last_briefing:
        briefing = BriefingView(
            day=int(world.state.last_briefing.get("day", 0)),
            text=world.state.last_briefing.get("text", ""),
        )

    return WorldStateView(
        day=world.day,
        minute_of_day=world.minute,
        weekday=world.weekday,
        tick=world.tick,
        time_label=world.time_label(),
        weather=WeatherView(
            kind=weather.get("kind", "sunny"),
            temp_c=int(weather.get("temp_c", 22)),
            text=weather.get("text", ""),
        ),
        speed_mode=world.state.speed_mode,
        tick_seconds=tick_period(
            world.state.speed_mode,
            bus.subscriber_count() if world.state.admin_override is None else None,
        ),
        observers=bus.subscriber_count(),
        degraded=bool(world.state.degraded),
        active_events=[active_event_view(e) for e in world.active_events],
        briefing=briefing,
    )


@router.get("/locations", response_model=list[LocationView])
async def world_locations(session: SessionDep, user: CurrentUser) -> list[LocationView]:
    world = await get_world()
    out = []
    for loc in world.locations.values():
        out.append(
            LocationView(
                id=loc.id, name=loc.name, emoji=loc.emoji,
                x=loc.x, y=loc.y, w=loc.w, h=loc.h, outdoor=loc.outdoor,
                description=loc.description, affordances=list(loc.affordances),
                ambience=dict(loc.ambience), capacity=loc.capacity,
                # 以内存角色当前位置为准，避免缓存的地点快照在移动后短暂重复。
                occupants=list(dict.fromkeys(c.id for c in world.occupants(loc.id))),
            )
        )
    return out


@router.get("/map", response_model=CampusMapView)
async def world_map(session: SessionDep, user: CurrentUser) -> CampusMapView:
    """可编辑校园地图（等距手绘）。管理员的改动通过 `map_updated` 事件通知。"""
    data = await campus_map.load_map(session)
    return CampusMapView(**data)


@router.get("/characters", response_model=list[CharacterSummaryView])
async def world_characters(
    session: SessionDep, user: CurrentUser, include_system: bool = False
) -> list[CharacterSummaryView]:
    world = await get_world()
    out = []
    for c in world.characters.values():
        if not c.is_active:
            continue
        if c.kind == "system" and not include_system:
            continue
        out.append(character_summary_view(world, c, me_user_id=user.id))
    out.sort(key=lambda x: (not x.is_me, x.location_id, x.name))
    return out


@router.get("/characters/{character_id}", response_model=CharacterDetailView)
async def world_character_detail(
    character_id: str, session: SessionDep, user: CurrentUser
) -> CharacterDetailView:
    world = await get_world()
    char = world.get_character(character_id)
    if char is None or not char.is_active:
        raise NotFound("角色不存在")
    data = await character_detail_full(world, char, user.id, session)
    return CharacterDetailView.model_validate(data)


@router.get("/events", response_model=list[EventView])
async def world_events(
    session: SessionDep,
    user: CurrentUser,
    since_tick: int | None = Query(default=None),
    limit: int = Query(default=200, le=200),
) -> list[EventView]:
    stmt = select(Event).order_by(col(Event.tick).asc())
    if since_tick is not None:
        stmt = stmt.where(col(Event.tick) >= since_tick)
    rows = (await session.exec(stmt.limit(limit))).all()
    return [event_view(e) for e in rows]


@router.get("/dialogues/{dialogue_id}", response_model=DialogueView)
async def world_dialogue(
    dialogue_id: str, session: SessionDep, user: CurrentUser
) -> DialogueView:
    row = (await session.exec(select(Dialogue).where(Dialogue.id == dialogue_id))).first()
    if row is None:
        raise NotFound("对话不存在")
    day, minute = decompose_tick(row.tick)
    return DialogueView(
        id=row.id, tick=row.tick, time_label=fmt_time_label(day, minute),
        location_id=row.location_id, a_id=row.a_id, b_id=row.b_id,
        turns=[DialogueTurnView(speaker_id=t.get("speaker_id", ""), text=t.get("text", ""))
               for t in (row.turns or [])],
        a_to_b_delta=row.a_to_b_delta, b_to_a_delta=row.b_to_a_delta,
        ended_because=row.ended_because, is_player_involved=row.is_player_involved,
    )


__all__ = [
    "router", "character_summary_view", "character_detail_view",
    "character_detail_full", "event_view", "active_event_view",
]
