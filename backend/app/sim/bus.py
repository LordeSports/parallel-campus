"""进程内事件总线（spec/03 §7、spec/04 §1）。

职责：
- 收集一个 tick 内产生的所有事件（`emit` / `extend`）
- 落库（tick 末一次事务，由 world.py 调用 `drain_persist`）
- 扇出给所有 SSE 订阅者（`subscribe` → `asyncio.Queue`）
- 统计观众数（`subscriber_count`），Ticker 据此决定速率
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from ..schemas.events import PERSISTED_EVENT_TYPES, SseEvent

log = logging.getLogger("pc.bus")

QUEUE_MAX = 512


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[SseEvent]] = set()
        self._pending: list[SseEvent] = []
        self._lock = asyncio.Lock()

    # ── 观众 ──

    def subscriber_count(self) -> int:
        return len(self._subscribers)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[SseEvent]]:
        queue: asyncio.Queue[SseEvent] = asyncio.Queue(maxsize=QUEUE_MAX)
        self._subscribers.add(queue)
        log.debug("bus subscribe: observers=%d", len(self._subscribers))
        try:
            yield queue
        finally:
            self._subscribers.discard(queue)
            log.debug("bus unsubscribe: observers=%d", len(self._subscribers))

    # ── 生产 ──

    def emit(self, event: SseEvent, *, broadcast: bool = True) -> None:
        self._pending.append(event)
        if broadcast:
            self._fanout(event)

    def extend(self, events: list[SseEvent], *, broadcast: bool = True) -> None:
        for e in events:
            self.emit(e, broadcast=broadcast)

    def _fanout(self, event: SseEvent) -> None:
        dead: list[asyncio.Queue[SseEvent]] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # 慢消费者：丢弃队列头部的旧事件，保持实时性
                try:
                    q.get_nowait()
                    q.put_nowait(event)
                except Exception:
                    dead.append(q)
            except Exception:
                dead.append(q)
        for q in dead:
            self._subscribers.discard(q)

    # ── 消费 ──

    def take_pending(self) -> list[SseEvent]:
        """取出本 tick 待落库事件（清空）。"""
        out = [e for e in self._pending if e.type in PERSISTED_EVENT_TYPES]
        self._pending.clear()
        return out

    def pending_count(self) -> int:
        return len(self._pending)

    def clear(self) -> None:
        self._pending.clear()


# 全局单例
bus = EventBus()

__all__ = ["EventBus", "bus", "QUEUE_MAX"]
