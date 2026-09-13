"""人格路由（spec/03 §3）。"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter
from sqlmodel import col, select

from ..config import settings
from ..errors import Conflict, NotFound, RateLimited
from ..models import Character, Persona, User, new_id, now_utc
from ..persona.pipeline import generate_persona
from ..schemas.domain import PersonaFile
from ..schemas.views import (
    DeployRequest,
    PersonaResponse,
    PersonaUpdateRequest,
    SourceStats,
)
from ..seeds import get_avatar, location_map
from ..sim.world import get_world
from .deps import CurrentUser, SessionDep
from .world import character_detail_view

log = logging.getLogger("pc.api.persona")

router = APIRouter(prefix="/persona", tags=["persona"])

GENERATE_DAILY_LIMIT = 3


def _to_view(persona: Persona) -> PersonaResponse:
    stats = persona.source_stats or {}
    try:
        file = PersonaFile.model_validate(persona.file)
    except Exception:
        file = _neutral_persona("未命名")
    left = max(0, GENERATE_DAILY_LIMIT - _count_today(persona))
    return PersonaResponse(
        file=file,
        thin=persona.thin,
        version=persona.version,
        source_stats=SourceStats(
            contents=int(stats.get("contents", 0)),
            followees=int(stats.get("followees", 0)),
            favlists=int(stats.get("favlists", 0)),
            saved_items=int(stats.get("saved_items", 0)),
            failed=list(stats.get("failed", [])),
        ),
        confirmed_at=persona.confirmed_at.isoformat() if persona.confirmed_at else None,
        generated_left_today=left,
    )


def _count_today(persona: Persona) -> int:
    if persona.generated_on == date.today():
        return persona.generated_count_today
    return 0


def _neutral_persona(name: str) -> PersonaFile:
    return PersonaFile(
        display_name=name or "未命名",
        archetype="还在认识自己的同学",
        mbti_like={"E_I": 0.0, "S_N": 0.0, "T_F": 0.0, "J_P": 0.0},
        big_five={"O": 0.5, "C": 0.5, "E": 0.5, "A": 0.5, "N": 0.5},
        interests=[
            {"topic": "校园生活", "weight": 0.6, "evidence": []},
            {"topic": "知识分享", "weight": 0.5, "evidence": []},
            {"topic": "影视", "weight": 0.4, "evidence": []},  # 会被归一化
        ],
        stances=[],
        speaking_style={"tone": "自然", "emoji": False, "length": "中", "catchphrases": []},
        values=["真诚"],
        social={"initiative": 0.5, "group_pref": "小圈子", "avoid_topics": ["个人隐私"]},
        campus_identity={"major": "未定", "grade": "大二", "club": None},
        appearance="穿得简单，走路不急",
        summary="这位同学的公开资料比较少，画像只能给出一个中性的起点。你可以直接修改它，或者稍后重新生成。",
    )


@router.post("/generate", response_model=PersonaResponse)
async def generate(
    session: SessionDep, user: CurrentUser, force: bool = False
) -> PersonaResponse:
    """同步生成人格（服务端 60s 超时）。已有且非 force → 直接返回。"""
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()

    if persona is not None and not force:
        return _to_view(persona)

    today = date.today()
    used = _count_today(persona) if persona is not None else 0
    if persona is not None and used >= GENERATE_DAILY_LIMIT:
        raise RateLimited("今天的生成次数已用完，明天再来", retry_after_seconds=3600)

    try:
        result = await generate_persona(session, user, force=force)
    except Exception as exc:
        log.warning("人格生成失败 %s: %s", user.display_name, exc)
        from ..errors import AppError, ZhihuError

        if isinstance(exc, AppError):
            raise
        raise ZhihuError("人格生成失败，请重试或稍后再试") from exc

    if persona is None:
        persona = Persona(id=new_id("pe_"), user_id=user.id)
        session.add(persona)

    persona.file = result.file.model_dump()
    persona.thin = result.thin
    persona.source_stats = result.source_stats
    persona.version = (persona.version or 0) + 1
    persona.generated_count_today = (used + 1) if persona.generated_on == today else 1
    persona.generated_on = today
    session.add(persona)
    await session.commit()
    await session.refresh(persona)
    return _to_view(persona)


@router.get("", response_model=PersonaResponse)
async def get_persona(session: SessionDep, user: CurrentUser) -> PersonaResponse:
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()
    if persona is None:
        raise NotFound("还没有人格文件，请先生成")
    return _to_view(persona)


@router.put("", response_model=PersonaResponse)
async def put_persona(
    payload: PersonaUpdateRequest, session: SessionDep, user: CurrentUser
) -> PersonaResponse:
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()
    if persona is None:
        raise NotFound("还没有人格文件，请先生成")

    from ..sim.filter import check_text

    for text in (
        payload.file.archetype,
        payload.file.summary,
        payload.file.appearance,
        *[i.topic for i in payload.file.interests],
        *[s.text for s in payload.file.stances],
        *payload.file.values,
    ):
        ok, reason = check_text(text)
        if not ok:
            raise Conflict(f"内容未通过审核（{reason}）")

    persona.file = payload.file.model_dump()
    persona.version = (persona.version or 0) + 1
    session.add(persona)
    await session.commit()
    await session.refresh(persona)
    return _to_view(persona)


@router.post("/deploy", response_model=dict, status_code=201)
async def deploy(
    payload: DeployRequest, session: SessionDep, user: CurrentUser, redeploy: bool = False
) -> dict:
    """投放到校园（US-05）。已投放且非 redeploy → 409。"""
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()
    if persona is None:
        raise NotFound("还没有人格文件，请先生成")

    existing = (
        await session.exec(select(Character).where(col(Character.user_id) == user.id))
    ).first()
    if existing is not None and existing.is_active and not redeploy:
        raise Conflict("你已经把分身投放到校园了")

    try:
        file = PersonaFile.model_validate(persona.file)
    except Exception as exc:
        raise Conflict("人格文件不完整，请回到编辑页检查") from exc

    # 用投放表单覆盖可编辑字段
    file.display_name = payload.display_name
    file.appearance = payload.appearance or file.appearance
    file.campus_identity.major = payload.major or file.campus_identity.major
    file.campus_identity.grade = payload.grade
    file.campus_identity.club = payload.club or None

    world = await get_world()
    avatar = get_avatar(payload.avatar_key)

    if existing is not None:
        char = existing
        char.is_active = True
        char.name = file.display_name
        char.avatar_key = avatar["key"]
        char.persona = file.model_dump()
        char.is_asleep = False
        char.energy = 100
        char.deployed_at_tick = world.tick
        char.schedule_day = 0          # 下一 tick 由 new_day 重新排
    else:
        char = Character(
            id=new_id("pl_"),
            kind="player",
            user_id=user.id,
            name=file.display_name,
            avatar_key=avatar["key"],
            persona=file.model_dump(),
            location_id="library",
            activity="刚被投放到校园",
            energy=100,
            is_asleep=False,
            deployed_at_tick=world.tick,
            schedule_day=0,
        )
        session.add(char)

    persona.file = file.model_dump()
    persona.confirmed_at = now_utc()
    session.add(persona)
    avatar_key = avatar["key"]
    session.add(char)
    await session.commit()

    await world.reload_characters()
    world.state.speed_mode = world.state.speed_mode

    return character_detail_view(world, char, me_user_id=user.id, session=session)


__all__ = ["router", "_to_view", "_neutral_persona"]
