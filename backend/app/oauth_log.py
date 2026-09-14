"""OAuth 登录调试日志（仅 DEV_MODE 使用）。

把 authorize / callback 的关键节点记进内存环形缓冲，供
`GET /api/auth/oauth-log` 在开发模式下直接展示——定位「登录状态已过期」
「知乎没有返回授权码」这类问题时，不必再去翻容器日志。

刻意放在内存：只在开发期看，重启即清空，不落库、不污染事件流。
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any

MAX_ENTRIES = 60


class OAuthLog:
    def __init__(self, maxlen: int = MAX_ENTRIES) -> None:
        self._items: deque[dict[str, Any]] = deque(maxlen=maxlen)

    def record(self, event: str, **detail: Any) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds") + "Z",
            "event": event,
        }
        entry.update({k: v for k, v in detail.items() if v is not None})
        self._items.append(entry)
        return entry

    def recent(self, limit: int = 40) -> list[dict[str, Any]]:
        """最新在前。"""
        return list(reversed(list(self._items)[-limit:]))

    def clear(self) -> None:
        self._items.clear()


oauth_log = OAuthLog()

__all__ = ["OAuthLog", "oauth_log", "MAX_ENTRIES"]
