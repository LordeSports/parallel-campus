"""认证路由（spec/03 §2）。"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import col, select

from ..config import settings
from ..errors import Forbidden, NotFound, Unauthorized
from ..models import Character, Persona, User, new_id, now_utc
from ..schemas.views import DevLoginRequest, JudgeLoginRequest, UserView
from ..security import (
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_MAX_AGE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    encrypt_token,
    sign_oauth_state,
    sign_session,
    verify_oauth_state,
)
from ..zhihu.oauth import authorize_url, exchange_code
from .deps import CurrentUser, SessionDep, WriteSessionDep, OptionalUser

log = logging.getLogger("pc.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session(response: Response, uid: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, sign_session(uid),
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax", secure=settings.cookie_secure,
        path="/",
    )


async def _user_view(session: SessionDep, user: User) -> UserView:
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()
    char = (
        await session.exec(
            select(Character).where(
                col(Character.user_id) == user.id, col(Character.is_active) == True  # noqa: E712
            )
        )
    ).first()
    zhihu_url = (
        f"https://www.zhihu.com/people/{user.zhihu_url_token}"
        if user.zhihu_url_token else None
    )
    return UserView(
        id=user.id, display_name=user.display_name, avatar_key=user.avatar_key,
        auth_kind=user.auth_kind, is_judge=user.is_judge,
        has_persona=persona is not None,
        character_id=char.id if char else None,
        zhihu_url=zhihu_url,
    )


@router.get("/zhihu/login", include_in_schema=True)
async def zhihu_login() -> RedirectResponse:
    """302 → openapi.zhihu.com/authorize；Set-Cookie pc_oauth_state（10min）。"""
    state = sign_oauth_state()
    resp = RedirectResponse(url=authorize_url(state), status_code=302)
    resp.set_cookie(
        OAUTH_STATE_COOKIE, state, max_age=OAUTH_STATE_MAX_AGE,
        httponly=True, samesite="lax", secure=settings.cookie_secure, path="/",
    )
    return resp


@router.get("/zhihu/callback")
async def zhihu_callback(
    request: Request,
    session: WriteSessionDep,
    authorization_code: str | None = None,
    code: str | None = None,
    state: str | None = None,
) -> RedirectResponse:
    """回调：解析 code（兼容 `authorization_code`）→ 换 token → 建/复用 user → 302。"""
    cookie_state = request.cookies.get(OAUTH_STATE_COOKIE)

    if not authorization_code and not code:
        return RedirectResponse("/login?error=oauth_failed&reason=missing_code", status_code=302)
    if not verify_oauth_state(cookie_state, state):
        return RedirectResponse("/login?error=oauth_failed&reason=state_mismatch", status_code=302)

    the_code = authorization_code or code or ""
    try:
        result = await exchange_code(the_code)
    except Exception as exc:
        log.warning("token 交换失败: %s", exc)
        reason = "zhihu_unavailable" if "unavailable" in str(exc).lower() else "token_exchange_failed"
        return RedirectResponse(f"/login?error=oauth_failed&reason={reason}", status_code=302)

    # 用户标识复用
    user: User | None = None
    if result.zhihu_uid:
        user = (await session.exec(select(User).where(User.zhihu_uid == result.zhihu_uid))).first()
    if user is None and result.url_token:
        user = (
            await session.exec(select(User).where(User.zhihu_url_token == result.url_token))
        ).first()

    display_name = (result.url_token or result.raw.get("name") or "")[:24]
    if not display_name:
        import hashlib

        display_name = "知乎用户 " + hashlib.sha1(result.access_token.encode()).hexdigest()[:4]

    if user is None:
        user = User(
            id=new_id("u_"), display_name=display_name, avatar_key="av_01",
            auth_kind="zhihu", zhihu_uid=result.zhihu_uid,
            zhihu_url_token=result.url_token,
        )
        session.add(user)
    else:
        user.display_name = user.display_name or display_name
        if result.url_token:
            user.zhihu_url_token = result.url_token

    user.zhihu_token_enc = encrypt_token(result.access_token)
    user.token_expires_at = result.expires_at
    user.last_login_at = now_utc()
    session.add(user)
    await session.commit()

    view = await _user_view(session, user)
    target = "/campus" if (view.has_persona and view.character_id) else "/persona"
    resp = RedirectResponse(target, status_code=302)
    _set_session(resp, user.id)
    resp.delete_cookie(OAUTH_STATE_COOKIE, path="/")
    return resp


@router.post("/dev-login", response_model=UserView)
async def dev_login(payload: DevLoginRequest, session: SessionDep, response: Response) -> UserView:
    """仅 DEV_MODE。"""
    if not settings.dev_mode:
        raise NotFound("开发登录未启用")

    name = payload.name.strip()[:24]
    user = (
        await session.exec(select(User).where(col(User.display_name) == name, col(User.auth_kind) == "dev"))
    ).first()
    if user is None:
        user = User(id=new_id("u_"), display_name=name, avatar_key="av_09",
                    auth_kind="dev", last_login_at=now_utc())
        session.add(user)
    user.last_login_at = now_utc()
    session.add(user)
    await session.commit()

    _set_session(response, user.id)
    return await _user_view(session, user)


@router.post("/judge-login", response_model=UserView)
async def judge_login(payload: JudgeLoginRequest, session: SessionDep, response: Response) -> UserView:
    """评委账号（env JUDGE_ACCOUNTS）。"""
    accounts = settings.judge_account_map
    expected = accounts.get(payload.username)
    if not expected or expected != payload.password:
        raise Unauthorized("用户名或密码不正确")

    user = (
        await session.exec(select(User).where(User.judge_username == payload.username))
    ).first()
    if user is None:
        # 启动预置失败时兜底创建
        from ..seed_runtime import _ensure_judges

        from ..sim.world import get_world

        # 预置使用独立连接；先释放当前事务，避免与自己的写锁互等。
        await session.rollback()
        await _ensure_judges(await get_world())
        user = (
            await session.exec(select(User).where(User.judge_username == payload.username))
        ).first()
    if user is None:
        raise Forbidden("评委账号未预置，请检查 judges.json")

    user.last_login_at = now_utc()
    session.add(user)
    await session.commit()

    _set_session(response, user.id)
    return await _user_view(session, user)


@router.get("/me", response_model=UserView)
async def me(session: SessionDep, user: OptionalUser) -> UserView:
    if user is None:
        raise Unauthorized("请先登录")
    return await _user_view(session, user)


@router.post("/logout", status_code=204)
async def logout(response: Response) -> Response:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


@router.delete("/me", status_code=204)
async def delete_me(session: SessionDep, user: CurrentUser, response: Response) -> Response:
    """级联删除（US-14）：角色、人格、记忆、关系、报告、耳语、私信、token。"""
    from sqlalchemy import delete, or_

    from ..models import (
        Dialogue, Memory, Message, Persona, Relationship, Report, Whisper,
    )

    char_ids = [
        c.id for c in (
            await session.exec(select(Character).where(col(Character.user_id) == user.id))
        ).all()
    ]
    if char_ids:
        await session.execute(delete(Memory).where(col(Memory.character_id).in_(char_ids)))
        await session.execute(
            delete(Relationship).where(
                or_(col(Relationship.from_id).in_(char_ids), col(Relationship.to_id).in_(char_ids))
            )
        )
        await session.execute(delete(Report).where(col(Report.character_id).in_(char_ids)))
        await session.execute(delete(Whisper).where(col(Whisper.character_id).in_(char_ids)))
        await session.execute(
            delete(Message).where(
                or_(col(Message.from_id).in_(char_ids), col(Message.to_id).in_(char_ids))
            )
        )
        await session.execute(
            delete(Dialogue).where(
                or_(col(Dialogue.a_id).in_(char_ids), col(Dialogue.b_id).in_(char_ids))
            )
        )
    await session.execute(delete(Persona).where(col(Persona.user_id) == user.id))
    await session.execute(delete(Character).where(col(Character.user_id) == user.id))
    await session.delete(user)
    await session.commit()

    from ..sim.world import get_world

    world = await get_world()
    await world.reload_characters()

    response.delete_cookie(SESSION_COOKIE, path="/")
    response.status_code = 204
    return response


__all__ = ["router"]
