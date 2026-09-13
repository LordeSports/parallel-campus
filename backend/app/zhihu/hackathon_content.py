"""黑客松内容接口（spec/06 §6，选做）。仅用于 NPC 背景素材脚本，不进运行时关键路径。"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

log = logging.getLogger("pc.zhihu.hackathon")

BASE = "https://api.zhihu.com/km-indep-home/hackathon/v2"
WORK_ID_RE = re.compile(r"^[0-9]{6,32}$")
VALID_KINDS = ("story", "knowledge")


async def list_works(kind: str, *, limit: int = 20) -> list[dict[str, Any]]:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind 必须是 {VALID_KINDS}")
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(f"{BASE}/{kind}/list", params={"Limit": limit})
        resp.raise_for_status()
        data = resp.json()
    items = data.get("data") or data.get("Data") or []
    return [i for i in items if isinstance(i, dict)]


async def get_work(kind: str, work_id: str) -> dict[str, Any]:
    if kind not in VALID_KINDS:
        raise ValueError(f"kind 必须是 {VALID_KINDS}")
    if not WORK_ID_RE.match(work_id):
        raise ValueError("work_id 格式非法")
    async with httpx.AsyncClient(timeout=15.0) as http:
        resp = await http.get(f"{BASE}/{kind}/{work_id}")
        resp.raise_for_status()
        data = resp.json()
    return data.get("data") or data.get("Data") or data


__all__ = ["list_works", "get_work", "BASE"]
