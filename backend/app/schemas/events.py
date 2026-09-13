"""SSE payload 类型与事件信封（spec/03 §7、spec/02 §3.10）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..constants import SseEventType

# 必须在前端监听的事件名（与 03 §7 表逐行对应）
SSE_EVENT_TYPES: tuple[str, ...] = (
    "hello", "heartbeat", "tick", "weather", "event_started", "event_ended",
    "character_moved", "character_activity", "dialogue_started", "dialogue_turn",
    "dialogue_ended", "post_created", "comment_created", "like_created", "dm_sent",
    "whisper_response", "reflection", "briefing", "report_ready", "degraded",
)

# 持久化到 events 表的事件类型（hello/heartbeat 不落库）
PERSISTED_EVENT_TYPES: frozenset[str] = frozenset(
    t for t in SSE_EVENT_TYPES if t not in ("hello", "heartbeat")
)


class SseEvent(BaseModel):
    """一条待发送/已落库的事件。`id` 用 events 表主键或递增序号。"""

    model_config = ConfigDict(extra="allow")

    id: str | None = None
    type: SseEventType
    tick: int
    day: int
    actor_id: str | None = None
    target_id: str | None = None
    location_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    def frame(self) -> str:
        """序列化为 SSE 帧：`id: …\\nevent: …\\ndata: …\\n\\n`"""
        import json

        lines = []
        if self.id:
            lines.append(f"id: {self.id}")
        lines.append(f"event: {self.type}")
        lines.append(f"data: {json.dumps(self.payload, ensure_ascii=False, separators=(',', ':'))}")
        return "\n".join(lines) + "\n\n"


def make_event(
    type_: SseEventType,
    tick: int,
    day: int,
    payload: dict[str, Any] | None = None,
    *,
    actor_id: str | None = None,
    target_id: str | None = None,
    location_id: str | None = None,
) -> SseEvent:
    return SseEvent(
        type=type_,
        tick=tick,
        day=day,
        actor_id=actor_id,
        target_id=target_id,
        location_id=location_id,
        payload=payload or {},
    )


__all__ = ["SSE_EVENT_TYPES", "PERSISTED_EVENT_TYPES", "SseEvent", "make_event"]
