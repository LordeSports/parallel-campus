"""一次性诊断：核对知乎开放平台的真实端点是否可用。

用法（secret 只从环境变量读，不会打印）：
    ZHIHU_TEST_SECRET=xxx python scripts/diag_zhihu_api.py

只发 2 个请求（搜索 1 + 热榜 1），远低于官方频率限制。
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

BASE = "https://developer.zhihu.com"
SECRET = os.environ.get("ZHIHU_TEST_SECRET", "").strip()

CASES = [
    ("zhihu_search", "GET", "/api/v1/content/zhihu_search", {"Query": "平行校园", "Count": 2}),
    ("hot_list", "GET", "/api/v1/content/hot_list", {"Limit": 3}),
]


async def main() -> int:
    if not SECRET:
        print("缺少 ZHIHU_TEST_SECRET")
        return 2

    proxy = os.environ.get("PC_TEST_PROXY", "").strip()
    kwargs = {"timeout": 20.0}
    if proxy:
        kwargs["proxy"] = proxy
        print(f"用代理 {proxy}")

    headers = {
        "Authorization": f"Bearer {SECRET}",
        "X-Request-Timestamp": str(int(time.time())),
        "Content-Type": "application/json",
    }

    ok = 0
    async with httpx.AsyncClient(**kwargs) as http:
        for name, method, path, params in CASES:
            try:
                resp = await http.request(method, BASE + path, params=params, headers=headers)
            except Exception as exc:  # 网络层
                print(f"✗ {name:14s} {path}  网络失败: {type(exc).__name__}: {exc}")
                continue

            body: object
            try:
                body = resp.json()
            except Exception:
                body = resp.text[:160]

            code = body.get("Code") if isinstance(body, dict) else None
            message = body.get("Message") if isinstance(body, dict) else None
            mark = "✓" if resp.status_code == 200 and code == 0 else "✗"
            if mark == "✓":
                ok += 1
            print(f"{mark} {name:14s} {path}")
            print(f"   HTTP={resp.status_code} Code={code} Message={message}")

            data = body.get("Data") if isinstance(body, dict) else None
            items = data.get("Items") if isinstance(data, dict) else None
            if isinstance(items, list):
                print(f"   Items={len(items)}")
                if items and isinstance(items[0], dict):
                    print(f"   首个 item 字段: {sorted(items[0].keys())[:12]}")
                    first = items[0]
                    for key in ("Title", "ContentText", "Url", "AuthorName", "VoteUpCount", "Summary"):
                        if key in first:
                            print(f"     {key} = {str(first[key])[:70]!r}")
            elif isinstance(body, dict):
                print(f"   顶层键: {sorted(body.keys())}")
            print()

    print(f"成功 {ok}/{len(CASES)}")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
