"""知乎内容接口（spec/06 §5）。

```python
async def hot_list(limit=30) -> list[HotItem]              # {title, url, summary, thumbnail_url}
async def zhihu_search(query, count=3) -> list[SearchItem] # {title, content_text[:200], url, author_name, vote_up_count}
async def zhida(question: str) -> str
```
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any

import httpx
from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..errors import ZhihuError
from ..zhihu.client import ZhihuClient, ZhihuClientBase
from .mock import MockZhihuClient

log = logging.getLogger("pc.zhihu.content")

HOT_PATH = "/api/v1/hot_list"
SEARCH_PATH = "/api/v1/search"
ZHIDA_PATH = "/v1/chat/completions"
ZHIDA_MODEL = "zhida-fast-1p5"

DEFAULT_SEARCH_COUNT = 3
ZHIDA_MAX_CHARS = 200

_http: httpx.AsyncClient | None = None


def _client(session: AsyncSession) -> ZhihuClientBase:
    if settings.zhihu_enabled:
        global _http
        if _http is None:
            _http = httpx.AsyncClient(timeout=15.0)
        return ZhihuClient(_http, session)
    return MockZhihuClient(session)


async def aclose() -> None:
    global _http
    if _http is not None:
        await _http.aclose()
        _http = None


# ─────────────────────────── hot_list ───────────────────────────


async def hot_list(limit: int = 30, *, session: AsyncSession | None = None) -> list[dict[str, Any]]:
    if session is None:
        from ..db import session_scope

        async with session_scope() as s:
            return await hot_list(limit, session=s)

    client = _client(session)
    try:
        data = await client.get("hot_list", HOT_PATH, {"Limit": limit})
    except ZhihuError:
        raise
    items = _dig(data, "Items") or _dig(data, "items") or []
    out: list[dict[str, Any]] = []
    for it in items[:limit]:
        out.append({
            "title": str(it.get("Title") or it.get("title") or ""),
            "url": str(it.get("Url") or it.get("url") or ""),
            "summary": str(it.get("Summary") or it.get("Excerpt") or it.get("summary") or ""),
            "thumbnail_url": str(it.get("ThumbnailUrl") or it.get("thumbnail_url") or ""),
        })
    return out


# ─────────────────────────── zhihu_search ───────────────────────────


async def zhihu_search(
    query: str, count: int = DEFAULT_SEARCH_COUNT, *, session: AsyncSession | None = None
) -> list[dict[str, Any]]:
    if session is None:
        from ..db import session_scope

        async with session_scope() as s:
            return await zhihu_search(query, count, session=s)

    client = _client(session)
    data = await client.get("zhihu_search", SEARCH_PATH, {"Query": query, "Limit": count})
    items = _dig(data, "Items") or _dig(data, "items") or []
    out: list[dict[str, Any]] = []
    for it in items[:count]:
        out.append({
            "title": str(it.get("Title") or it.get("title") or ""),
            "content_text": str(
                it.get("ContentText") or it.get("Excerpt") or it.get("content_text") or ""
            )[:200],
            "url": str(it.get("Url") or it.get("url") or ""),
            "author_name": str(it.get("AuthorName") or it.get("author_name") or ""),
            "vote_up_count": int(it.get("VoteUpCount") or it.get("vote_up_count") or 0),
        })
    return out


# ─────────────────────────── zhida ───────────────────────────


async def zhida(question: str, *, session: AsyncSession | None = None) -> str:
    if session is None:
        from ..db import session_scope

        async with session_scope() as s:
            return await zhida(question, session=s)

    client = _client(session)
    body = {
        "model": ZHIDA_MODEL,
        "messages": [{"role": "user", "content": question}],
        "stream": False,
    }
    data = await client.post("zhida", ZHIDA_PATH, body)
    # Mock 直接给 choices；真实客户端也走同一路径
    content = ""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = str(msg.get("content") or "")
    if not content:
        err = data.get("error")
        if err:
            code = err.get("code") if isinstance(err, dict) else None
            raise ZhihuError("知乎直答返回错误", zhihu_code=code)
    answer = content.strip()[:ZHIDA_MAX_CHARS]
    if not answer:
        return "这个问题我暂时没有好的答案。"
    return f"{answer}\n—— 来源：知乎直答"


# ─────────────────────────── 助手 ───────────────────────────


def _dig(data: dict[str, Any], key: str) -> Any:
    """兼容 `Data.Items` / `data.Items` / 顶层。"""
    if key in data:
        return data[key]
    for container_key in ("Data", "data"):
        container = data.get(container_key)
        if isinstance(container, dict) and key in container:
            return container[key]
    return None


__all__ = ["hot_list", "zhihu_search", "zhida", "aclose", "ZHIDA_MODEL", "_client"]
