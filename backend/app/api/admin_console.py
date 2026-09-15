"""管理员控制台：账号、总览、NPC、时间天气、场景与 API 配置。"""

from __future__ import annotations

import hmac
import time
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Request, Response
from sqlalchemy import func
from sqlmodel import select

from ..admin_settings import api_changes, public_settings, reload_clients, save_runtime_settings
from .. import campus_map
from ..config import settings
from ..db import session_scope, write_lock, write_session
from ..errors import Forbidden, NotFound, RateLimited, Unauthorized, ValidationError, Conflict
from ..models import Character, Dialogue, LlmUsage, Memory, Post, Relationship, WorldEvent, WorldState, new_id
from ..schemas.admin import (
    AdminLoginRequest, AdminSessionView, AdminOverviewView, AdminWeatherRequest,
    ApiSettingsRequest, ApiSettingsView, ClockRequest, NpcRequest, NpcView,
    SceneRequest, SimulationRequest, UsageGroupView, UsageItemView,
)
from ..schemas.events import make_event
from ..schemas.map import CampusMapView, MapSaveRequest
from ..schemas.views import ActiveEventView, LocationView, ModeResponse, WorldStateView
from ..security import (
    ADMIN_COOKIE,
    ADMIN_SESSION_MAX_AGE,
    redact,
    sign_admin_session,
    verify_admin_session,
)
from ..seeds import avatars, default_schedule
from ..sim.world import get_world
from .admin import status
from .deps import AdminGuard, SessionDep, check_admin_origin
from .world import active_event_view, character_summary_view, world_locations, world_state

router = APIRouter(prefix="/admin", tags=["admin"])
_login_failures: dict[str, list[float]] = {}


@router.get("/session", response_model=AdminSessionView)
async def admin_session(request: Request) -> AdminSessionView:
    username = verify_admin_session(request.cookies.get(ADMIN_COOKIE))
    return AdminSessionView(enabled=bool(settings.admin_password), authenticated=bool(username), username=username)


@router.post("/login", response_model=AdminSessionView)
async def admin_login(payload: AdminLoginRequest, request: Request, response: Response) -> AdminSessionView:
    check_admin_origin(request)
    if not settings.admin_password:
        raise Forbidden("管理员登录未启用，请先配置 ADMIN_PASSWORD")
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    attempts = [stamp for stamp in _login_failures.get(ip, []) if now - stamp < 60]
    if len(attempts) >= 5:
        raise RateLimited("登录失败次数过多，请稍后重试", 60)
    valid_name = hmac.compare_digest(payload.username.encode(), settings.admin_username.encode())
    valid_password = hmac.compare_digest(payload.password.get_secret_value().encode(), settings.admin_password.encode())
    if not (valid_name and valid_password):
        if len(_login_failures) >= 1024 and ip not in _login_failures:
            _login_failures.pop(next(iter(_login_failures)))
        _login_failures[ip] = attempts + [now]
        raise Unauthorized("管理员用户名或密码不正确")
    _login_failures.pop(ip, None)
    response.set_cookie(ADMIN_COOKIE, sign_admin_session(settings.admin_username),
                        max_age=ADMIN_SESSION_MAX_AGE, httponly=True, samesite="strict",
                        secure=settings.cookie_secure, path="/api/admin")
    return AdminSessionView(enabled=True, authenticated=True, username=settings.admin_username)


@router.post("/logout", status_code=204)
async def admin_logout(request: Request, response: Response) -> Response:
    check_admin_origin(request)
    response.delete_cookie(ADMIN_COOKIE, path="/api/admin")
    response.status_code = 204
    return response


@router.get("/overview", response_model=AdminOverviewView)
async def overview(_: AdminGuard, session: SessionDep) -> AdminOverviewView:
    world = await get_world()
    start = datetime.now(timezone(timedelta(hours=8))).replace(hour=0, minute=0, second=0, microsecond=0)
    start = start.astimezone(timezone.utc).replace(tzinfo=None)
    usage = (await session.exec(select(LlmUsage).where(LlmUsage.at >= start))).all()
    groups: dict[str, UsageGroupView] = {}
    for row in usage:
        group = groups.setdefault(row.model, UsageGroupView(model=row.model, calls=0, prompt_tokens=0, completion_tokens=0))
        group.calls += 1
        group.prompt_tokens += row.prompt_tokens
        group.completion_tokens += row.completion_tokens
    recent = (await session.exec(select(LlmUsage).order_by(LlmUsage.at.desc()).limit(50))).all()
    chars = list(world.characters.values())
    counts = {
        "agents": sum(c.is_active and c.kind != "system" for c in chars),
        "npcs": sum(c.is_active and c.kind == "npc" for c in chars),
        "players": sum(c.is_active and c.kind == "player" for c in chars),
        "inactive_npcs": sum(not c.is_active and c.kind == "npc" for c in chars),
        "awake": len(world.awake_characters()),
    }
    for key, model in (("posts", Post), ("memories", Memory), ("dialogues", Dialogue)):
        counts[key] = (await session.exec(select(func.count()).select_from(model))).one()
    scenes = (await session.exec(select(WorldEvent).where(WorldEvent.status != "ended")
                                 .order_by(WorldEvent.start_tick.desc()).limit(100))).all()
    return AdminOverviewView(
        world=await world_state(session, None), status=await status(None, session),
        control_mode=world.state.admin_override or "idle", counts=counts,
        usage_by_model=list(groups.values()),
        recent_usage=[UsageItemView(id=r.id, at=r.at.isoformat() + "Z", model=r.model, tier=r.tier,
                                   template=r.template, prompt_tokens=r.prompt_tokens,
                                   completion_tokens=r.completion_tokens, latency_ms=r.latency_ms, ok=r.ok,
                                   error=redact(r.error) if r.error else None)
                      for r in recent], scenes=[active_event_view(row) for row in scenes],
    )


def _notify(world) -> None:
    world.emit(make_event("world_changed", world.tick, world.day, {"tick": world.tick, "day": world.day}))


@router.put("/simulation", response_model=ModeResponse)
async def simulation(payload: SimulationRequest, _: AdminGuard) -> ModeResponse:
    from ..sim.ticker import ticker

    mode = await ticker.configure(payload.mode, payload.ticks, {
        "tick_seconds_online": payload.tick_seconds_online, "tick_seconds_idle": payload.tick_seconds_idle,
    })
    return ModeResponse(mode=mode)


@router.put("/clock", response_model=WorldStateView)
async def clock(payload: ClockRequest, _: AdminGuard) -> WorldStateView:
    from ..sim.ticker import ticker

    async with write_lock:
        world = await get_world()
        delta = (payload.day - world.day) * 1440 + payload.minute_of_day - world.minute
        if delta < 0:
            raise Conflict("时间不能倒退；请选择当前或未来时刻")
        state = WorldState(**world.state.model_dump())
        state.day = payload.day
        state.minute_of_day = payload.minute_of_day
        state.weekday = (payload.day - 1) % 7 + 1
        state.tick += delta // 30
        state.speed_mode = state.admin_override = "paused"
        state.remaining_ticks = 0
        day_changed = world.day != payload.day
        changed_chars = {}
        async with write_session() as session:
            if day_changed:
                state.hot_pull_count_today = 0
            state = await session.merge(state)
            for old in world.active_characters():
                char = Character(**old.model_dump())
                char.is_asleep = payload.minute_of_day < 420 or payload.minute_of_day >= 1410
                char.dialogue_id = None
                if day_changed:
                    char.energy = 100
                    char.schedule = default_schedule(payload.day).model_dump()
                    char.schedule_day = payload.day
                    char.attended_event_ids = []
                changed_chars[char.id] = await session.merge(char)
            if day_changed:
                for relation in (await session.exec(select(Relationship))).all():
                    relation.affinity_delta_today = 0
                    session.add(relation)
            rows = (await session.exec(select(WorldEvent).where(WorldEvent.status != "ended"))).all()
            for row in rows:
                if row.end_tick <= state.tick:
                    row.status = "ended"
                elif row.start_tick <= state.tick:
                    row.status = "active"
                session.add(row)
        world.state = state
        world.characters.update(changed_chars)
        await world.reload_active_events()
        ticker.wake()
        _notify(world)
        async with session_scope() as session:
            return await world_state(session, None)


@router.put("/weather", response_model=WorldStateView)
async def weather(payload: AdminWeatherRequest, _: AdminGuard) -> WorldStateView:
    async with write_lock:
        world = await get_world()
        state = WorldState(**world.state.model_dump())
        state.weather = payload.model_dump()
        async with write_session() as session:
            state = await session.merge(state)
        world.state = state
        _notify(world)
        async with session_scope() as session:
            return await world_state(session, None)


@router.get("/locations", response_model=list[LocationView])
async def locations(_: AdminGuard, session: SessionDep) -> list[LocationView]:
    return await world_locations(session, None)


def _npc_view(world, char: Character) -> NpcView:
    return NpcView(**character_summary_view(world, char).model_dump(), is_active=char.is_active, persona=char.persona)


@router.get("/npcs", response_model=list[NpcView])
async def npcs(_: AdminGuard) -> list[NpcView]:
    world = await get_world()
    return [_npc_view(world, char) for char in world.characters.values() if char.kind == "npc"]


async def _save_npc(payload: NpcRequest, character_id: str | None = None) -> NpcView:
    if payload.avatar_key not in {item["key"] for item in avatars()}:
        raise ValidationError("请选择有效头像")
    async with write_lock:
        world = await get_world()
        async with write_session() as session:
            if character_id:
                char = await session.get(Character, character_id)
                if char is None or char.kind != "npc":
                    raise NotFound("NPC 不存在")
            else:
                char = Character(id=new_id("npc_"), name=payload.name, kind="npc")
            data = payload.model_dump()
            data["persona"]["display_name"] = payload.name
            for name, value in data.items():
                setattr(char, name, value)
            char.dialogue_id = None
            char.schedule = default_schedule(world.day).model_dump()
            char.schedule_day = world.day
            session.add(char)
        world.characters[char.id] = char
        _notify(world)
        return _npc_view(world, char)


@router.post("/npcs", response_model=NpcView, status_code=201)
async def create_npc(payload: NpcRequest, _: AdminGuard) -> NpcView:
    return await _save_npc(payload)


@router.put("/npcs/{character_id}", response_model=NpcView)
async def update_npc(character_id: str, payload: NpcRequest, _: AdminGuard) -> NpcView:
    return await _save_npc(payload, character_id)


@router.get("/scenes", response_model=list[ActiveEventView])
async def scenes(_: AdminGuard, session: SessionDep) -> list[ActiveEventView]:
    rows = (await session.exec(select(WorldEvent).order_by(WorldEvent.start_tick.desc()).limit(100))).all()
    return [active_event_view(row) for row in rows]


@router.post("/scenes", response_model=ActiveEventView, status_code=201)
async def create_scene(payload: SceneRequest, _: AdminGuard) -> ActiveEventView:
    async with write_lock:
        world = await get_world()
        # `LocationId` 刻意放宽为 str（允许管理员自定义地点），所以这里必须
        # 显式校验地点真实存在——否则活动会挂在空气上、角色永远触发不到。
        if payload.location_id not in world.locations:
            raise ValidationError(f"地点不存在：{payload.location_id}")
        row = WorldEvent(id=new_id("e_"), kind="adhoc", title=payload.title, description=payload.description,
                         location_id=payload.location_id, start_tick=world.tick,
                         end_tick=world.tick + payload.duration_ticks, tags=payload.tags, status="active")
        async with write_session() as session:
            session.add(row)
        await world.reload_active_events()
        _notify(world)
        return active_event_view(row)


@router.post("/scenes/{scene_id}/end", response_model=ActiveEventView)
async def end_scene(scene_id: str, _: AdminGuard) -> ActiveEventView:
    async with write_lock:
        world = await get_world()
        async with write_session() as session:
            row = await session.get(WorldEvent, scene_id)
            if row is None:
                raise NotFound("场景不存在")
            row.status = "ended"
            row.end_tick = min(row.end_tick, world.tick)
            session.add(row)
        await world.reload_active_events()
        _notify(world)
        return active_event_view(row)


@router.get("/map", response_model=CampusMapView)
async def get_campus_map(_: AdminGuard, session: SessionDep) -> CampusMapView:
    """读取可编辑校园地图（与玩家端同一份数据）。"""
    return CampusMapView(**await campus_map.load_map(session))


@router.put("/map", response_model=CampusMapView)
async def save_campus_map(
    payload: MapSaveRequest, request: Request, _: AdminGuard
) -> CampusMapView:
    """整图保存。保存后广播 `map_updated`，在线玩家端自动重新拉取。"""
    updated_by = verify_admin_session(request.cookies.get(ADMIN_COOKIE)) or "admin-token"
    async with write_lock:
        version = await campus_map.save_map(
            [obj.model_dump() for obj in payload.objects], updated_by, payload.title
        )
        world = await get_world()
        world.emit(
            make_event(
                "map_updated", world.tick, world.day,
                {"version": version, "objects": len(payload.objects)},
            )
        )
    async with session_scope() as session:
        return CampusMapView(**await campus_map.load_map(session))


@router.get("/settings", response_model=ApiSettingsView)
async def get_api_settings(_: AdminGuard) -> ApiSettingsView:
    return public_settings()

@router.put("/settings", response_model=ApiSettingsView)
async def set_api_settings(payload: ApiSettingsRequest, _: AdminGuard) -> ApiSettingsView:
    async with write_lock:
        changes = api_changes(payload)
        save_runtime_settings(changes)
        await reload_clients()
        return public_settings()
