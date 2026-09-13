"""Mock 知乎客户端（spec/06 §7）。

与真实客户端同接口，从 `seeds/mock_zhihu/*.json` 夹具返回，模拟 200ms 延迟，
也走 quota 计数（便于测上限）。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from ..errors import QuotaExceeded, ZhihuError
from .client import ApiName, ZhihuClientBase, bj_date, cap_for, quota_bump, quota_count

log = logging.getLogger("pc.zhihu.mock")

FIXTURE_DIR = Path(__file__).resolve().parent.parent / "seeds" / "mock_zhihu"
MOCK_LATENCY = 0.2


def _load(name: str) -> Any:
    path = FIXTURE_DIR / name
    if not path.exists():
        log.warning("mock 夹具缺失: %s", name)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


class MockZhihuClient(ZhihuClientBase):
    """离线知乎客户端：读 seeds 夹具，但配额计数**照常落库**。

    `session` 允许为 `None`。若为 `None`，每次调用自建一个短会话提交配额；
    显式传入的会话**不会被提交**——调用方可能正处于一个跨 tick 的长事务里
    （例如 Ticker），在事务中途 commit 会破坏「一 tick 一提交」的语义，
    也会在 SQLite 上引发锁竞争。
    """

    def __init__(self, session: AsyncSession | None = None, *, latency: float = MOCK_LATENCY) -> None:
        self.session = session
        self.latency = latency
        self._fixtures: dict[str, Any] = {}

    def _fixture(self, name: str) -> Any:
        if name not in self._fixtures:
            self._fixtures[name] = _load(name)
        return self._fixtures[name]

    @asynccontextmanager
    async def _own_session(self) -> AsyncIterator[AsyncSession]:
        """自建短会话；调用方已提供会话时直接借用（不自建、不提交）。"""
        if self.session is not None:
            yield self.session
            return
        from ..db import session_scope

        async with session_scope() as s:
            yield s

    async def _gate(self, api: ApiName, cap: int | None) -> None:
        effective = cap if cap is not None else cap_for(api)
        if effective is None:
            return
        async with self._own_session() as session:
            used = await quota_count(session, api, bj_date())
            if used >= effective:
                raise QuotaExceeded(api)
            await quota_bump(session, api, bj_date())
            # 只有自建会话才提交；借用调用方会话时交给它自己提交
            if self.session is None:
                await session.commit()

    async def get(self, api, path, params, *, oauth_token=None, ttl=None, cap=None):
        if self.latency:
            await asyncio.sleep(self.latency)
        await self._gate(api, cap)
        return self._route(api, path, params, oauth_token)

    async def post(self, api, path, body, *, oauth_token=None, ttl=None, cap=None):
        if self.latency:
            await asyncio.sleep(self.latency)
        await self._gate(api, cap)
        if api == "zhida":
            question = ""
            msgs = (body or {}).get("messages") or []
            if msgs and isinstance(msgs, list):
                question = str(msgs[-1].get("content", ""))
            return self._zhida_response(question)
        return self._route(api, path, {}, oauth_token)

    # ── 路由 ──

    def _route(self, api: ApiName, path: str, params: dict[str, Any], oauth_token: str | None) -> dict:
        if api == "hot_list":
            return {"Code": 0, "Data": {"Items": self._fixture("hot_list.json") or []}}

        if api == "zhihu_search":
            return {"Code": 0, "Data": {"Items": self._search(params)}}

        if api == "user_data":
            return self._user_data(path, params)

        return {"Code": 0, "Data": {}}

    def _search(self, params: dict[str, Any]) -> list[dict]:
        table = self._fixture("zhihu_search.json") or {}
        query = str(params.get("Query") or params.get("query") or params.get("q") or "").strip()
        if query and query in table:
            return table[query]
        for key, items in table.items():
            if key != "_default" and key and key in query:
                return items
        return table.get("_default", [])

    def _user_data(self, path: str, params: dict[str, Any]) -> dict:
        if path.endswith("/user/contents"):
            return {"Code": 0, "Data": {"Items": self._fixture("contents.json") or []}}
        if path.endswith("/user/followees"):
            items = self._fixture("followees.json") or []
            offset = int(params.get("Offset") or 0)
            limit = int(params.get("Limit") or 50)
            chunk = items[offset : offset + limit]
            is_end = offset + limit >= len(items)
            return {
                "Code": 0,
                "Data": {
                    "Items": chunk,
                    "Paging": {"IsEnd": is_end, "NextOffset": "" if is_end else str(offset + limit)},
                },
            }
        if path.endswith("/user/favlists"):
            return {"Code": 0, "Data": {"Items": self._fixture("favlists.json") or []}}
        if path.endswith("/user/collections"):
            return {"Code": 0, "Data": {"Items": self._fixture("collections.json") or []}}
        if path.endswith("/user/favlist_contents"):
            grouped = self._fixture("favlist_contents.json") or {}
            token = str(params.get("UrlToken") or next(iter(grouped), "default"))
            return {"Code": 0, "Data": {"Items": grouped.get(token, [])}}
        return {"Code": 0, "Data": {"Items": []}}

    def _zhida_response(self, question: str) -> dict:
        table = self._fixture("zhida.json") or {}
        digest = hashlib.sha1(question.encode()).hexdigest()
        answer = table.get(digest) or table.get("_default") or "这个问题我暂时没有好的答案。"
        return {
            "id": "mock-zhida",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 80},
        }


__all__ = ["MockZhihuClient", "FIXTURE_DIR"]
