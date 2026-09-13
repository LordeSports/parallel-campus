"""领域枚举与常量（spec/02 §1–§2）。"""

from __future__ import annotations

from typing import Literal

# ── 枚举 ──
CharacterKind = Literal["player", "npc", "system"]
LocationId = Literal[
    "teaching_a", "library", "canteen", "field", "dorm", "milktea", "club_room", "lakeside"
]
Board = Literal["wall", "tree_hole", "notice"]
ActionType = Literal[
    "move", "talk", "post", "comment", "like", "dm", "attend", "do", "search_zhihu", "idle"
]
MemoryKind = Literal[
    "observation", "dialogue", "reflection", "whisper", "event", "search", "schedule"
]
WeatherKind = Literal["sunny", "cloudy", "rainy", "foggy", "windy"]
SpeedMode = Literal["paused", "idle", "online", "fast_forward"]
EventKind = Literal["hot", "calendar", "weather", "adhoc"]
LlmTier = Literal["strong", "cheap"]

SseEventType = Literal[
    "hello", "heartbeat", "tick", "weather", "event_started", "event_ended",
    "character_moved", "character_activity", "dialogue_started", "dialogue_turn",
    "dialogue_ended", "post_created", "comment_created", "like_created", "dm_sent",
    "whisper_response", "reflection", "briefing", "report_ready", "degraded", "world_changed",
]

# ── ID 前缀 ──
ID_PREFIX = {
    "user": "u_",
    "character": "pl_",
    "npc": "npc_",
    "system": "sys_",
    "post": "p_",
    "comment": "c_",
    "message": "m_",
    "dialogue": "d_",
    "event": "e_",
    "world_event": "e_",
    "report": "r_",
    "whisper": "w_",
    "memory": "mem_",
    "like": "lk_",
}

# ── 时间模型（02 §2）──
TICKS_PER_DAY = 48
MINUTES_PER_TICK = 30
DAY_START_MINUTE = 360      # 06:00 新一天
WAKE_MINUTE = 420           # 07:00 醒来
REFLECT_MINUTE = 1380       # 23:00 反思
SLEEP_MINUTE = 1410         # 23:30 简报/报告/睡眠
MAX_MINUTE_OF_DAY = 1410

WEEKDAY_LABELS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]

# ── 事件保留 ──
EVENT_RETENTION = 5000

# ── 默认 importance（04 §7.1）──
DEFAULT_IMPORTANCE: dict[str, int] = {
    "schedule": 1,
    "observation": 2,
    "search": 4,
    "event": 5,
    "dialogue": 6,
    "reflection": 8,
    "whisper": 9,
}

# ── 心情标签映射（05 §3 P3）──
MOOD_LABELS: list[tuple[float, float, str]] = [
    # (valence_min, arousal_min, label) —— 从上往下匹配第一个满足的
    (0.4, 0.6, "兴奋"),
    (0.4, -2.0, "开心"),
    (-0.1, 0.6, "烦躁"),
    (-2.0, 0.6, "烦躁"),
    (-0.1, -2.0, "平静"),
    (-0.4, -2.0, "低落"),
    (-2.0, -2.0, "疲惫"),
]


def mood_label(valence: float, arousal: float) -> str:
    if valence > 0.4:
        return "兴奋" if arousal > 0.6 else "开心"
    if valence > -0.1:
        return "烦躁" if arousal > 0.6 else "平静"
    if valence > -0.4:
        return "烦躁" if arousal > 0.6 else "低落"
    return "低落"


def energy_label(energy: int) -> str:
    if energy >= 70:
        return "精力充沛"
    if energy >= 40:
        return "还行"
    if energy >= 20:
        return "有点累"
    return "很累"


def time_label(day: int, minute_of_day: int) -> str:
    """`第3天 周三 09:30`"""
    weekday = (day - 1) % 7 + 1
    hh, mm = divmod(minute_of_day, 60)
    return f"第{day}天 {WEEKDAY_LABELS[weekday - 1]} {hh:02d}:{mm:02d}"


def tick_of(day: int, minute_of_day: int) -> int:
    return (day - 1) * TICKS_PER_DAY + minute_of_day // MINUTES_PER_TICK


def decompose_tick(tick: int) -> tuple[int, int]:
    """tick → (day, minute_of_day)"""
    day = tick // TICKS_PER_DAY + 1
    minute = (tick % TICKS_PER_DAY) * MINUTES_PER_TICK
    return day, minute


__all__ = [
    "CharacterKind", "LocationId", "Board", "ActionType", "MemoryKind", "WeatherKind",
    "SpeedMode", "EventKind", "LlmTier", "SseEventType", "ID_PREFIX",
    "TICKS_PER_DAY", "MINUTES_PER_TICK", "DAY_START_MINUTE", "WAKE_MINUTE",
    "REFLECT_MINUTE", "SLEEP_MINUTE", "MAX_MINUTE_OF_DAY", "WEEKDAY_LABELS",
    "EVENT_RETENTION", "DEFAULT_IMPORTANCE",
    "mood_label", "energy_label", "time_label", "tick_of", "decompose_tick",
]
