"""知乎 OAuth（spec/06 §3）。

授权：`https://openapi.zhihu.com/authorize?redirect_uri=&app_id=&response_type=code&state=`
换 token：`POST https://openapi.zhihu.com/access_token`（form-urlencoded）
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from ..config import settings
from ..errors import TokenExchangeError

log = logging.getLogger("pc.zhihu.oauth")

AUTHORIZE_URL = "https://openapi.zhihu.com/authorize"
TOKEN_URL = "https://openapi.zhihu.com/access_token"
DEFAULT_EXPIRES_DAYS = 30

UID_KEYS = ("uid", "user_id", "open_id", "id")
URL_TOKEN_KEYS = ("url_token", "urlToken", "url_token_value")


@dataclass
class TokenResult:
    access_token: str
    expires_at: datetime | None = None
    zhihu_uid: str | None = None
    url_token: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


def authorize_url(state: str) -> str:
    params = {
        "redirect_uri": settings.zhihu_oauth_redirect_uri,
        "app_id": settings.zhihu_oauth_app_id,
        "response_type": "code",
        "state": state,
    }
    return f"{AUTHORIZE_URL}?{urlencode(params)}"


def _find(nested: Any, keys: tuple[str, ...], depth: int = 0) -> Any:
    """在可能嵌套的 dict 中找第一个命中的 key（两层）。"""
    if depth > 3:
        return None
    if isinstance(nested, dict):
        for k in keys:
            v = nested.get(k)
            if isinstance(v, (str, int)) and str(v):
                return v
        for v in nested.values():
            if isinstance(v, dict):
                found = _find(v, keys, depth + 1)
                if found:
                    return found
            elif isinstance(v, list):
                for item in v:
                    found = _find(item, keys, depth + 1)
                    if found:
                        return found
    elif isinstance(nested, list):
        for item in nested:
            found = _find(item, keys, depth + 1)
            if found:
                return found
    return None


async def exchange_code(code: str) -> TokenResult:
    """换 token。成功判定：响应 JSON 含非空 `access_token`（可能包在 `data` 里）。"""
    if not settings.zhihu_oauth_app_id or not settings.zhihu_oauth_app_key:
        raise TokenExchangeError("token_exchange_failed")

    form = {
        "app_id": settings.zhihu_oauth_app_id,
        "app_key": settings.zhihu_oauth_app_key,
        "grant_type": "authorization_code",
        "redirect_uri": settings.zhihu_oauth_redirect_uri,
        "code": code,
    }
    try:
        async with httpx.AsyncClient(timeout=15.0) as http:
            resp = await http.post(
                TOKEN_URL, data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
    except (httpx.TimeoutException, httpx.TransportError) as exc:
        log.warning("换 token 网络错误: %s", exc)
        raise TokenExchangeError("zhihu_unavailable") from exc

    if resp.status_code >= 400:
        log.warning("换 token HTTP %s: %s", resp.status_code, resp.text[:200])
        raise TokenExchangeError("token_exchange_failed")

    try:
        data = resp.json()
    except Exception as exc:
        log.warning("换 token 响应非 JSON: %s", resp.text[:200])
        raise TokenExchangeError("token_exchange_failed") from exc

    if not isinstance(data, dict):
        raise TokenExchangeError("token_exchange_failed")

    token = _find(data, ("access_token", "accessToken"))
    if not token:
        # code: 20000 不算失败，但仍需 access_token
        log.warning("换 token 响应无 access_token：%s", str(data)[:200])
        raise TokenExchangeError("token_exchange_failed")

    expires_in = _find(data, ("expires_in", "expiresIn"))
    expires_at = None
    try:
        if expires_in:
            expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
                seconds=int(expires_in)
            )
    except (TypeError, ValueError):
        expires_at = None
    if expires_at is None:
        expires_at = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(
            days=DEFAULT_EXPIRES_DAYS
        )

    uid = _find(data, UID_KEYS)
    url_token = _find(data, URL_TOKEN_KEYS)
    if uid and str(uid).startswith("pl_") or (uid and str(uid).startswith("u_")):
        uid = None      # 防误取

    return TokenResult(
        access_token=str(token),
        expires_at=expires_at,
        zhihu_uid=str(uid) if uid else None,
        url_token=str(url_token) if url_token else None,
        raw=data,
    )


def display_name_from(result: TokenResult) -> str:
    """优先 url_token；否则「知乎用户 + token sha1[:4]」。"""
    if result.url_token:
        return result.url_token[:24]
    for key in ("name", "nickname", "display_name"):
        v = _find(result.raw, (key,))
        if v:
            return str(v)[:24]
    digest = hashlib.sha1(result.access_token.encode()).hexdigest()[:4]
    return f"知乎用户 {digest}"


__all__ = ["authorize_url", "exchange_code", "TokenResult", "display_name_from", "AUTHORIZE_URL", "TOKEN_URL"]
