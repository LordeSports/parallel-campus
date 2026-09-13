"""SSE 流（spec/03 §7）。"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from ..sim.bus import bus
from ..sim.world import get_world
from .deps import CurrentUser, SessionDep

log = logging.getLogger("pc.api.stream")

router = APIRouter(tags=["stream"])

HEARTBEAT_SECONDS = 15.0


@router.get("/stream")
async def stream(request: Request, session: SessionDep, user: CurrentUser) -> StreamingResponse:
    """`Accept: text/event-stream`；连接建立先发 hello，之后每条实时事件 + 15s heartbeat。"""
    user_id = user.id
    # SSE 可能持续数小时，鉴权后立即释放事务与连接，避免长期保留读快照。
    await session.close()
    world = await get_world()

    async def event_generator():
        # 建立连接即计入观众数 → Ticker 提速
        async with bus.subscribe() as queue:
            hello = {
                "tick": world.tick,
                "server_time": datetime.now(timezone.utc).isoformat(),
                "speed_mode": world.state.speed_mode,
            }
            yield f"event: hello\ndata: {json.dumps(hello, ensure_ascii=False)}\n\n"

            try:
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                    except asyncio.TimeoutError:
                        yield "event: heartbeat\ndata: {}\n\n"
                        continue
                    yield ev.frame()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("SSE 连接异常")
            finally:
                log.debug("SSE 连接关闭 uid=%s", user_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["router"]
