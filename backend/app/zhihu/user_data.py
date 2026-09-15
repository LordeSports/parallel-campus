"""用户数据拉取与证据包（spec/06 §4）。

限速：7 个请求背靠背会触发知乎的 30001（频率限制），因此
① 相邻请求之间强制至少 `zhihu_user_data_gap` 秒；
② 命中 30001 时按 4 倍间隔退避并**重试一次**（spec「不重试」针对盲目重试，
   这里是限流退避，属于调用方自行降级的范畴）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..errors import ZhihuError
from ..zhihu.client import ZhihuClientBase

log = logging.getLogger("pc.zhihu.user_data")

RATE_LIMITED_CODE = 30001

EVIDENCE_MAX_CHARS = 6000
# 超限截断配额：C 50% / S 25% / F 15% / L 10%
QUOTA_C = 0.50
QUOTA_S = 0.25
QUOTA_F = 0.15
QUOTA_L = 0.10

CONTENTS_LIMIT = 50
FOLLOWEES_LIMIT = 50
FAVLISTS_LIMIT = 20
COLLECTIONS_LIMIT = 30
FAVLIST_CONTENTS_LIMIT = 20

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(raw: str | None, limit: int | None = None) -> str:
    """剥 HTML 标签，换行压成空格。"""
    if not raw:
        return ""
    text = _HTML_TAG_RE.sub(" ", str(raw))
    text = _WS_RE.sub(" ", text).strip()
    if limit is not None:
        return text[:limit]
    return text


@dataclass
class Record:
    prefix: str        # C / F / L / S
    index: int
    line: str


@dataclass
class EvidencePack:
    text: str = ""
    stats: dict[str, Any] = field(default_factory=dict)
    thin: bool = False
    failed: list[str] = field(default_factory=list)


async def pull_user_data(
    client: ZhihuClientBase, oauth_token: str
) -> tuple[dict[str, list[dict[str, Any]]], list[str]]:
    """按 §4.1 计划顺序执行，任一失败记录到 failed[] 并继续。"""
    out: dict[str, list[dict[str, Any]]] = {
        "contents": [], "followees": [], "favlists": [], "collections": [],
        "favlist_contents": [],
    }
    failed: list[str] = []
    gap = max(0.0, float(settings.zhihu_user_data_gap))
    backoff = gap * 4.0
    # 相邻请求的最小间隔：每次发请求前把"下次允许发送的时刻"往后推 gap
    next_ok = 0.0

    async def _throttle(extra: float = 0.0) -> None:
        nonlocal next_ok
        loop = asyncio.get_running_loop()
        now = loop.time()
        wait = max(next_ok, now + extra) - now
        if wait > 0:
            await asyncio.sleep(wait)
            now = loop.time()
        next_ok = now + gap

    async def _try(name: str, path: str, params: dict[str, Any]) -> dict[str, Any] | None:
        for attempt in range(2):
            await _throttle(extra=0.0 if attempt == 0 else backoff)
            try:
                return await client.get("user_data", path, params, oauth_token=oauth_token)
            except ZhihuError as exc:
                if exc.zhihu_code == RATE_LIMITED_CODE and attempt == 0:
                    log.info("用户数据 %s 触发频率限制，%.1f 秒后重试一次", name, backoff)
                    continue
                code = exc.zhihu_code if exc.zhihu_code is not None else "http"
                failed.append(f"{name}:{code}")
                log.info("用户数据拉取失败 %s: %s", name, exc)
                return None
            except Exception as exc:
                failed.append(f"{name}:{type(exc).__name__.lower()}")
                log.info("用户数据拉取异常 %s: %s", name, exc)
                return None
        return None

    # 1. contents
    data = await _try("contents", "/api/v1/user/contents",
                      {"ContentType": "all", "SortField": "like_count",
                       "SortOrder": "desc", "Limit": CONTENTS_LIMIT})
    if data:
        out["contents"] = _items(data)

    # 2-3. followees（翻页；NextOffset 是 String）
    offset = 0
    for page in range(2):
        if page == 0:
            data = await _try("followees", "/api/v1/user/followees",
                              {"Limit": FOLLOWEES_LIMIT, "Offset": 0})
        else:
            if offset <= 0:
                break
            data = await _try("followees", "/api/v1/user/followees",
                              {"Limit": FOLLOWEES_LIMIT, "Offset": offset})
        if not data:
            break
        out["followees"].extend(_items(data))
        paging = _dig(data, "Paging") or {}
        is_end = paging.get("IsEnd", True)
        next_offset_raw = paging.get("NextOffset", "")
        try:
            offset = int(str(next_offset_raw)) if next_offset_raw != "" else 0
        except (TypeError, ValueError):
            offset = 0
            failed.append("followees:bad_offset")
        if is_end or offset <= 0:
            break

    # 4. favlists
    data = await _try("favlists", "/api/v1/user/favlists", {"Limit": FAVLISTS_LIMIT})
    if data:
        out["favlists"] = _items(data)

    # 5. collections
    data = await _try("collections", "/api/v1/user/collections", {"Limit": COLLECTIONS_LIMIT})
    if data:
        out["collections"] = _items(data)

    # 6-7. favlist_contents（前 2 个 IsPublic=true）
    public = [f for f in out["favlists"] if f.get("IsPublic") is True][:2]
    for fav in public:
        token = str(fav.get("UrlToken") or fav.get("Id") or "")
        if not token:
            continue
        data = await _try("favlist_contents", "/api/v1/user/favlist_contents",
                          {"UrlToken": token, "Limit": FAVLIST_CONTENTS_LIMIT})
        if data:
            out["favlist_contents"].extend(_items(data))

    return out, failed


def build_evidence(data: dict[str, list[dict[str, Any]]], failed: list[str]) -> EvidencePack:
    """组装证据包（§4.2），总长上限 6000 字，按 C/S/F/L 配额截断。"""
    c_records: list[Record] = []
    for i, it in enumerate(data.get("contents", [])[:CONTENTS_LIMIT], start=1):
        ctype = str(it.get("ContentType") or it.get("Type") or "回答")
        like = int(it.get("LikeCount") or it.get("VoteUpCount") or 0)
        comment = int(it.get("CommentCount") or 0)
        title = clean_text(it.get("Title") or it.get("QuestionTitle") or "", 60)
        digest = clean_text(it.get("Excerpt") or it.get("ContentText") or it.get("Summary") or "", 120)
        c_records.append(Record("C", i, f"C{i} [{ctype}·赞{like}·评{comment}] {title} — {digest}"))

    f_records: list[Record] = []
    for i, it in enumerate(data.get("followees", [])[:FOLLOWEES_LIMIT], start=1):
        name = clean_text(it.get("Name") or it.get("Fullname") or "", 24)
        headline = clean_text(it.get("Headline") or it.get("Description") or "", 60)
        f_records.append(Record("F", i, f"F{i} {name} — {headline}"))

    l_records: list[Record] = []
    for i, it in enumerate(data.get("favlists", [])[:FAVLISTS_LIMIT], start=1):
        title = clean_text(it.get("Title") or "", 40)
        count = int(it.get("ItemCount") or it.get("Count") or 0)
        desc = clean_text(it.get("Description") or "", 60)
        l_records.append(Record("L", i, f"L{i} {title}（{count} 条）— {desc}"))

    s_records: list[Record] = []
    idx = 0
    for it in data.get("collections", [])[:COLLECTIONS_LIMIT]:
        idx += 1
        ctype = str(it.get("ContentType") or it.get("Type") or "回答")
        title = clean_text(it.get("Title") or it.get("QuestionTitle") or "", 60)
        digest = clean_text(it.get("Excerpt") or it.get("ContentText") or "", 100)
        s_records.append(Record("S", idx, f"S{idx} [{ctype}] {title} — {digest}"))
    for it in data.get("favlist_contents", [])[:FAVLIST_CONTENTS_LIMIT]:
        idx += 1
        ctype = str(it.get("ContentType") or it.get("Type") or "回答")
        title = clean_text(it.get("Title") or it.get("QuestionTitle") or "", 60)
        digest = clean_text(it.get("Excerpt") or it.get("ContentText") or "", 100)
        s_records.append(Record("S", idx, f"S{idx} [{ctype}] {title} — {digest}"))

    header_c = f"【创作 {len(c_records)} 条】"
    header_f = f"【关注 {len(f_records)} 人（Headline 摘录）】"
    header_l = f"【收藏夹 {len(l_records)} 个】"
    header_s = f"【收藏内容 {len(s_records)} 条】"

    sections = {
        "C": (header_c, [r.line for r in c_records]),
        "S": (header_s, [r.line for r in s_records]),
        "F": (header_f, [r.line for r in f_records]),
        "L": (header_l, [r.line for r in l_records]),
    }
    quota = {"C": QUOTA_C, "S": QUOTA_S, "F": QUOTA_F, "L": QUOTA_L}

    def _render(limits: dict[str, int]) -> str:
        parts: list[str] = []
        for key in ("C", "F", "L", "S"):
            head, lines = sections[key]
            if not lines:
                continue
            body: list[str] = []
            used = 0
            for line in lines:
                if used + len(line) + 1 > limits[key]:
                    break
                body.append(line)
                used += len(line) + 1
            if body:
                parts.append(head + "\n" + "\n".join(body))
        return "\n".join(parts)

    full_limits = {"C": 10**9, "S": 10**9, "F": 10**9, "L": 10**9}
    text = _render(full_limits)
    if len(text) > EVIDENCE_MAX_CHARS:
        # 按 C50/S25/F15/L10 截断
        limits = {k: max(60, int(EVIDENCE_MAX_CHARS * v)) for k, v in quota.items()}
        text = _render(limits)
        # 仍超限 → 全局硬截断
        if len(text) > EVIDENCE_MAX_CHARS:
            text = text[:EVIDENCE_MAX_CHARS] + "…"

    contents_n = len(c_records)
    saved_n = len(s_records)
    followees_n = len(f_records)
    favlists_n = len(l_records)
    thin = (contents_n + saved_n + followees_n) < 5

    return EvidencePack(
        text=text,
        stats={
            "contents": contents_n,
            "followees": followees_n,
            "favlists": favlists_n,
            "saved_items": saved_n,
            "failed": list(failed),
        },
        thin=thin,
        failed=list(failed),
    )


def _items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = _dig(data, "Items") or _dig(data, "items") or []
    return [i for i in items if isinstance(i, dict)]


def _dig(data: dict[str, Any], key: str) -> Any:
    if key in data:
        return data[key]
    for container_key in ("Data", "data"):
        container = data.get(container_key)
        if isinstance(container, dict) and key in container:
            return container[key]
    return None


__all__ = ["pull_user_data", "build_evidence", "EvidencePack", "clean_text", "EVIDENCE_MAX_CHARS"]
