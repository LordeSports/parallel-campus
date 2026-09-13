"""API 依赖：会话、当前用户、当前角色、admin 校验。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..db import get_session, get_write_session
from ..errors import Forbidden, Unauthorized
from ..models import Character, Persona, User
from ..security import ADMIN_COOKIE, SESSION_COOKIE, check_admin_token, verify_admin_session, verify_session

SessionDep = Annotated[AsyncSession, Depends(get_session)]
WriteSessionDep = Annotated[AsyncSession, Depends(get_write_session)]


async def current_user_optional(request: Request, session: SessionDep) -> User | None:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    uid = verify_session(token)
    if not uid:
        return None
    user = (await session.exec(select(User).where(User.id == uid))).first()
    return user


async def current_user(
    user: Annotated[User | None, Depends(current_user_optional)],
) -> User:
    if user is None:
        raise Unauthorized("请先登录")
    return user


async def current_character(user: Annotated[User, Depends(current_user)], session: SessionDep) -> Character:
    char = (
        await session.exec(
            select(Character).where(
                col(Character.user_id) == user.id, col(Character.is_active) == True  # noqa: E712
            )
        )
    ).first()
    if char is None:
        raise Forbidden("你还没有把分身投放到校园")
    return char


async def current_persona(user: Annotated[User, Depends(current_user)], session: SessionDep) -> Persona:
    persona = (
        await session.exec(select(Persona).where(col(Persona.user_id) == user.id))
    ).first()
    if persona is None:
        from ..errors import NotFound

        raise NotFound("还没有人格文件，请先生成")
    return persona


def check_admin_origin(request: Request) -> None:
    """Cookie 写请求只允许浏览器同源操作；header token 客户端不受此限制。"""
    from urllib.parse import urlsplit

    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise Forbidden("管理员操作必须来自同源页面")
    origin = request.headers.get("origin")
    if origin:
        from ..config import settings

        allowed = {str(request.base_url).rstrip("/"), settings.public_base_url.rstrip("/")}
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or origin.rstrip("/") not in allowed:
            raise Forbidden("管理员操作必须来自同源页面")


async def require_admin(
    request: Request,
    x_admin_token: Annotated[str | None, Header()] = None,
) -> None:
    if check_admin_token(x_admin_token):
        return
    if not verify_admin_session(request.cookies.get(ADMIN_COOKIE)):
        raise Unauthorized("请先登录管理员账户")
    check_admin_origin(request)


CurrentUser = Annotated[User, Depends(current_user)]
OptionalUser = Annotated[User | None, Depends(current_user_optional)]
CurrentCharacter = Annotated[Character, Depends(current_character)]
CurrentPersona = Annotated[Persona, Depends(current_persona)]
AdminGuard = Annotated[None, Depends(require_admin)]


__all__ = [
    "SessionDep", "WriteSessionDep", "CurrentUser", "OptionalUser", "CurrentCharacter", "CurrentPersona",
    "AdminGuard", "current_user", "current_user_optional", "current_character",
    "current_persona", "require_admin",
]
