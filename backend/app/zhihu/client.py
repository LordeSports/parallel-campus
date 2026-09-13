"""知乎适配层基类与错误归一化（spec/06 §2）。

`ApiName = Literal["hot_list","zhihu_search","zhida","user_data"]`
TTL：hot_list 3600s · zhihu_search 86400s · zhida 86400s · user_data 7d
日上限：hot_list 24 · zhihu_search 200 · zhida 50 · user_data 无
"""

from __future__ import annotations

import abc
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import httpx
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..errors import QuotaExceeded, ZhihuError
from ..models import ZhihuCache, new_id, now_utc

log = logging.getLogger("pc.zhihu")

ApiName = Literal["hot_list", "zhihu_search", "zhida", "user_data"]

TTL: dict[str, int] = {
    "hot_list": 3600,
    "zhihu_search": 86400,
    "zhida": 86400,
    "user_data": 7 * 86400,
}

DAILY_CAP: dict[str, int | None] = {
    "hot_list": None,          # 运行时读 settings.hot_daily_cap
    "zhihu_search": None,      # settings.search_daily_cap
    "zhida": None,             # settings.zhida_daily_cap
    "user_data": None,         # 无硬限
}

REQUEST_TIMEOUT = 10.0
BJ = timezone(timedelta(hours=8))

# 知乎错误码归一化（06 §2）
ZHIHU_CODE_MEANING = {
    10001: "参数错误",
    20001: "鉴权失败",
    30001: "请求频率超限",
    30002: "配额已用尽",
    90001: "知乎内部错误",
}


def bj_date() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d")


def cap_for(api: ApiName) -> int | None:
    if api == "hot_list":
        return settings.hot_daily_cap
    if api == "zhihu_search":
        return settings.search_daily_cap
    if api == "zhida":
        return settings.zhida_daily_cap
    return None


def cache_key(api: str, path: str, params: dict[str, Any], oauth_token: str | None) -> str:
    """`{api}:{sha1(path + sorted params + oauth前缀)}`"""
    payload = path + json.dumps(params, sort_keys=True, ensure_ascii=False)
    if oauth_token:
        payload += oauth_token[:8]
    digest = hashlib.sha1(payload.encode()).hexdigest()
    return f"{api}:{digest}"


class CacheStore:
    """`zhihu_cache` 表读写。"""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, key: str) -> Any | None:
        row = (
            await self.session.exec(select(ZhihuCache).where(ZhihuCache.key == key))
        ).first()
        if row is None:
            return None
        if row.expires_at and row.expires_at < now_utc():
            await self.session.delete(row)
            return None
        return row.value

    async def set(self, key: str, api: str, value: Any, ttl: int) -> None:
        expires = now_utc() + timedelta(seconds=ttl)
        row = (
            await self.session.exec(select(ZhihuCache).where(ZhihuCache.key == key))
        ).first()
        if row is None:
            row = ZhihuCache(key=key, api=api, value=value, expires_at=expires)
        else:
            row.value = value
            row.expires_at = expires
            row.api = api
        self.session.add(row)

    async def delete(self, key: str) -> None:
        row = (
            await self.session.exec(select(ZhihuCache).where(ZhihuCache.key == key))
        ).first()
        if row is not None:
            await self.session.delete(row)


async def quota_count(session: AsyncSession, api: str, date: str) -> int:
    from ..models import QuotaLog

    row = (
        await session.exec(
            select(QuotaLog).where(col(QuotaLog.api) == api, col(QuotaLog.date) == date)
        )
    ).first()
    return row.count if row else 0


async def quota_bump(session: AsyncSession, api: str, date: str) -> int:
    from ..models import QuotaLog

    row = (
        await session.exec(
            select(QuotaLog).where(col(QuotaLog.api) == api, col(QuotaLog.date) == date)
        )
    ).first()
    if row is None:
        row = QuotaLog(id=new_id("q_"), api=api, date=date, count=1)
    else:
        row.count += 1
    session.add(row)
    return row.count


async def quota_force_cap(session: AsyncSession, api: str, date: str) -> None:
    """收到 30002 时把当日计数直接置为 cap（本地封顶）。"""
    from ..models import QuotaLog

    cap = cap_for(api)  # type: ignore[arg-type]
    if cap is None:
        return
    row = (
        await session.exec(
            select(QuotaLog).where(col(QuotaLog.api) == api, col(QuotaLog.date) == date)
        )
    ).first()
    if row is None:
        row = QuotaLog(id=new_id("q_"), api=api, date=date, count=cap)
    else:
        row.count = cap
    session.add(row)


class ZhihuClientBase(abc.ABC):
    """真实客户端与 Mock 的共同接口（spec/06 §2）。"""

    @abc.abstractmethod
    async def get(
        self,
        api: ApiName,
        path: str,
        params: dict[str, Any],
        *,
        oauth_token: str | None = None,
        ttl: int | None = None,
        cap: int | None = None,
    ) -> dict[str, Any]:
        ...

    @abc.abstractmethod
    async def post(
        self,
        api: ApiName,
        path: str,
        body: dict[str, Any],
        *,
        oauth_token: str | None = None,
        ttl: int | None = None,
        cap: int | None = None,
    ) -> dict[str, Any]:
        ...


class ZhihuClient(ZhihuClientBase):
    """真实客户端。缓存 → 配额 → 请求 → 归一化 → 写缓存 → quota+1；**不重试**。"""

    def __init__(
        self,
        http: httpx.AsyncClient,
        session: AsyncSession,
        *,
        base_url: str | None = None,
        access_secret: str | None = None,
    ) -> None:
        self.http = http
        self.session = session
        self.cache = CacheStore(session)
        self.base_url = (base_url or settings.zhihu_api_base).rstrip("/")
        self.access_secret = access_secret if access_secret is not None else settings.zhihu_access_secret

    # ── 公共流程 ──

    async def _call(
        self,
        method: str,
        api: ApiName,
        path: str,
        params: dict[str, Any],
        *,
        body: dict[str, Any] | None = None,
        oauth_token: str | None = None,
        ttl: int | None = None,
        cap: int | None = None,
    ) -> dict[str, Any]:
        key = cache_key(api, path, params, oauth_token)
        cached = await self.cache.get(key)
        if cached is not None:
            log.info('{"event":"zhihu_call","api":"%s","path":"%s","cache_hit":true}', api, path)
            return cached

        today = bj_date()
        effective_cap = cap if cap is not None else cap_for(api)
        if effective_cap is not None:
            used = await quota_count(self.session, api, today)
            if used >= effective_cap:
                log.info('{"event":"zhihu_call","api":"%s","path":"%s","cache_hit":false,"quota":"exceeded"}',
                         api, path)
                raise QuotaExceeded(api)

        started = time.monotonic()
        status = 0
        zhihu_code: int | None = None
        try:
            data = await self._request(method, path, params, body, oauth_token)
            status = 200
            zhihu_code = _extract_code(data)
            if zhihu_code not in (None, 0):
                raise ZhihuError(
                    f"知乎接口返回错误：{ZHIHU_CODE_MEANING.get(zhihu_code, '未知错误')}",
                    status=200, zhihu_code=zhihu_code,
                )
        except ZhihuError as exc:
            zhihu_code = exc.zhihu_code if isinstance(exc.zhihu_code, int) else None
            if zhihu_code == 30002:
                await quota_force_cap(self.session, api, today)
                await self.session.commit()
            log.warning(
                '{"event":"zhihu_call","api":"%s","path":"%s","cache_hit":false,"status":%s,"zhihu_code":%s,"latency_ms":%d,"error":true}',
                api, path, status, zhihu_code, int((time.monotonic() - started) * 1000),
            )
            raise
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning('{"event":"zhihu_call","api":"%s","path":"%s","status":0,"latency_ms":%d,"error":"%s"}',
                        api, path, int((time.monotonic() - started) * 1000), type(exc).__name__)
            raise ZhihuError("知乎接口暂时不可用", status=0, zhihu_code=None) from exc
        except httpx.HTTPStatusError as exc:
            log.warning('{"event":"zhihu_call","api":"%s","path":"%s","status":%d,"error":true}',
                        api, path, exc.response.status_code)
            raise ZhihuError("知乎接口返回异常状态", status=exc.response.status_code) from exc

        effective_ttl = ttl if ttl is not None else TTL.get(api, 3600)
        await self.cache.set(key, api, data, effective_ttl)
        if effective_cap is not None:
            await quota_bump(self.session, api, today)
        await self.session.commit()

        log.info(
            '{"event":"zhihu_call","api":"%s","path":"%s","cache_hit":false,"status":%d,"latency_ms":%d,"oauth":%s}',
            api, path, status, int((time.monotonic() - started) * 1000), bool(oauth_token),
        )
        return data

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        body: dict[str, Any] | None,
        oauth_token: str | None,
    ) -> dict[str, Any]:
        from ..security import redact

        headers = {
            "Authorization": f"Bearer {self.access_secret}",
            "X-Request-Timestamp": str(int(time.time())),
            "Content-Type": "application/json",
        }
        if oauth_token:
            headers["X-OAuth-Token"] = oauth_token
        url = f"{self.base_url}{path}"
        log.debug("zhihu 请求 %s %s (secret=%s oauth=%s)", method, path,
                  redact(self.access_secret), redact(oauth_token))
        if method.upper() == "GET":
            resp = await self.http.get(url, params=params, headers=headers, timeout=REQUEST_TIMEOUT)
        else:
            resp = await self.http.post(url, params=params, json=body or {}, headers=headers,
                                        timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return {"data": data}
        return data

    async def get(self, api, path, params, *, oauth_token=None, ttl=None, cap=None):
        return await self._call("GET", api, path, params, oauth_token=oauth_token, ttl=ttl, cap=cap)

    async def post(self, api, path, body, *, oauth_token=None, ttl=None, cap=None):
        return await self._call("POST", api, path, {}, body=body,
                                oauth_token=oauth_token, ttl=ttl, cap=cap)


def _extract_code(data: dict[str, Any]) -> int | None:
    """兼容 `Code` / `code` / `data.Code`。"""
    for container in (data, data.get("data") if isinstance(data.get("data"), dict) else {}):
        for key in ("Code", "code"):
            if key in container:
                try:
                    return int(container[key])
                except (TypeError, ValueError):
                    return None
    return None


__all__ = [
    "ApiName", "ZhihuClientBase", "ZhihuClient", "CacheStore",
    "TTL", "DAILY_CAP", "REQUEST_TIMEOUT", "cache_key", "cap_for",
    "quota_count", "quota_bump", "quota_force_cap", "bj_date",
    "ZHIHU_CODE_MEANING",
]
