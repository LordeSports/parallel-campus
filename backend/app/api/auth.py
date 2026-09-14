"""认证路由（spec/03 §2）。"""

from __future__ import annotations

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse
from sqlmodel import col, select

from ..admin_settings import overridden_fields
from ..config import settings
from ..errors import NotFound, Unauthorized
from ..models import Character, Persona, User, new_id, now_utc
from ..oauth_log import oauth_log
from ..schemas.views import DevLoginRequest, UserView
from ..security import (
    OAUTH_STATE_COOKIE,
    OAUTH_STATE_MAX_AGE,
    SESSION_COOKIE,
    SESSION_MAX_AGE,
    diagnose_oauth_state,
    encrypt_token,
    sign_oauth_state,
    sign_session,
    verify_oauth_state,
)
from ..zhihu.oauth import authorize_url, exchange_code
from ..version import build_fingerprint
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
        auth_kind=user.auth_kind,
        has_persona=persona is not None,
        character_id=char.id if char else None,
        zhihu_url=zhihu_url,
    )


@router.get("/oauth-log")
async def oauth_debug_log() -> dict[str, object]:
    """仅 DEV_MODE：返回最近的 OAuth 调试日志（登录页会展示，便于自查）。

    顺带回显生效中的回调配置——「登录状态已过期」九成是这里的 host/协议对不上。
    另附 `build` 指纹与每个凭证的**来源**（`.env` 还是后台加密配置）：
    后台保存的值优先于 `.env` 且存在数据卷里，重建容器不会清掉，
    是「改了配置却没生效」的常见原因。
    """
    if not settings.dev_mode:
        raise NotFound("OAuth 调试日志仅在 DEV_MODE 下可用")

    overridden = overridden_fields()

    def source_of(field: str) -> str:
        return "后台配置" if field in overridden else ".env"

    return {
        "dev_mode": True,
        "build": build_fingerprint(),
        "public_base_url": settings.public_base_url,
        "redirect_uri": settings.zhihu_oauth_redirect_uri,
        "cookie_secure": settings.cookie_secure,
        "app_id": settings.zhihu_oauth_app_id,
        "app_id_configured": bool(settings.zhihu_oauth_app_id),
        "app_id_source": source_of("zhihu_oauth_app_id"),
        "app_key_configured": bool(settings.zhihu_oauth_app_key),
        "app_key_source": source_of("zhihu_oauth_app_key"),
        "access_secret_configured": bool(settings.zhihu_access_secret),
        "access_secret_source": source_of("zhihu_access_secret"),
        "overridden_fields": sorted(overridden),
        "entries": oauth_log.recent(40),
    }


@router.get("/zhihu/login", include_in_schema=True)
async def zhihu_login(request: Request) -> RedirectResponse:
    """302 → openapi.zhihu.com/authorize；Set-Cookie pc_oauth_state（10min）。"""
    # 凭证不全就别带着空 app_id 跳知乎（那边不会发授权码，回来还会是 missing_code）
    if not settings.zhihu_oauth_app_id or not settings.zhihu_oauth_app_key:
        oauth_log.record(
            "authorize_blocked",
            reason="未配置 ZHIHU_OAUTH_APP_ID / ZHIHU_OAUTH_APP_KEY",
            app_id="有" if settings.zhihu_oauth_app_id else "无",
            app_key="有" if settings.zhihu_oauth_app_key else "无",
        )
        log.warning("拒绝发起知乎授权：OAuth 凭证未配置完整")
        return RedirectResponse(
            "/login?error=oauth_failed&reason=oauth_not_configured", status_code=302
        )

    state = sign_oauth_state()
    oauth_log.record(
        "authorize",
        redirect_uri=settings.zhihu_oauth_redirect_uri,
        cookie_secure=settings.cookie_secure,
        host=request.headers.get("host"),
        referer=request.headers.get("referer"),
    )
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
        oauth_log.record(
            "callback_missing_code",
            query=dict(request.query_params),
            host=request.headers.get("host"),
        )
        log.warning("OAuth 回调缺少授权码：query=%s", dict(request.query_params))
        return RedirectResponse("/login?error=oauth_failed&reason=missing_code", status_code=302)
    if not verify_oauth_state(cookie_state, state):
        diag = diagnose_oauth_state(cookie_state, state)
        # 签名验不过但 cookie 明明很新鲜 → 签发与校验用的不是同一个 SESSION_SECRET
        # （多实例/多 worker 各自随机生成，或容器混跑新旧两份配置）。
        why = {
            "no_cookie": "没有收到 state cookie（回调 host 与发起 host 不一致 / Secure cookie 走了 http / 浏览器拦截）",
            "no_query_state": "回调没带 state 参数",
            "cookie_signature_invalid_or_expired": "state cookie 签名无效或已过期（超过 10 分钟，或 SESSION_SECRET 被改过）",
            "cookie_query_mismatch": "cookie 与回调 state 值不一致（可能是同一浏览器提交了两次登录，或回显被改写）",
        }.get(diag["reason"], "state 校验失败")
        oauth_log.record(
            "callback_state_mismatch",
            why=why,
            reason=diag["reason"],
            cookie_state="有" if cookie_state else "无",
            query_state="有" if state else "无",
            cookie_signature_ok=diag["cookie_signature_ok"],
            cookie_age_seconds=diag["cookie_age_seconds"],
            same_raw=diag["same_raw"],
            host=request.headers.get("host"),
            referer=request.headers.get("referer"),
        )
        log.warning(
            "OAuth state 校验失败：%s | reason=%s cookie=%s query=%s 签名=%s 已签发=%ss",
            why, diag["reason"], "有" if cookie_state else "无",
            "有" if state else "无", "ok" if diag["cookie_signature_ok"] else "fail",
            diag["cookie_age_seconds"],
        )
        return RedirectResponse("/login?error=oauth_failed&reason=state_mismatch", status_code=302)

    the_code = authorization_code or code or ""
    try:
        result = await exchange_code(the_code)
    except Exception as exc:
        log.warning("token 交换失败: %s", exc)
        reason = "zhihu_unavailable" if "unavailable" in str(exc).lower() else "token_exchange_failed"
        oauth_log.record(
            "token_exchange_failed",
            reason=reason,
            detail=str(exc)[:200],
            app_id="有" if settings.zhihu_oauth_app_id else "无",
            app_key="有" if settings.zhihu_oauth_app_key else "无",
        )
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
