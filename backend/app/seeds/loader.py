"""seeds 加载与校验（spec/08）。"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import SEEDS_DIR
from ..schemas.domain import DailySchedule, Location, PersonaFile

log = logging.getLogger("pc.seeds")


def _read_json(name: str) -> Any:
    path = SEEDS_DIR / name
    if not path.exists():
        log.error("seeds 文件缺失: %s", path)
        return None
    return json.loads(path.read_text(encoding="utf-8"))


# ─────────────────────────── 地点 ───────────────────────────


@lru_cache
def locations() -> tuple[Location, ...]:
    raw = _read_json("locations.json") or []
    out: list[Location] = []
    for item in raw:
        try:
            out.append(Location.model_validate(item))
        except Exception as exc:
            log.error("地点 seed 非法 %s: %s", item.get("id"), exc)
    return tuple(out)


def location_map() -> dict[str, Location]:
    return {loc.id: loc for loc in locations()}


def get_location(location_id: str) -> Location | None:
    return location_map().get(location_id)


# ─────────────────────────── NPC ───────────────────────────


@lru_cache
def npcs() -> tuple[dict[str, Any], ...]:
    raw = _read_json("npcs.json") or []
    out: list[dict[str, Any]] = []
    for item in raw:
        try:
            PersonaFile.model_validate(item["persona"])
        except Exception as exc:
            log.error("NPC persona 非法 %s: %s", item.get("id"), exc)
            continue
        out.append(item)
    return tuple(out)


def npc_by_id(npc_id: str) -> dict[str, Any] | None:
    for n in npcs():
        if n["id"] == npc_id:
            return n
    return None


def system_character() -> dict[str, Any]:
    """sys_broadcast 定义。"""
    for n in npcs():
        if n["id"] == "sys_broadcast":
            return n
    return {
        "id": "sys_broadcast",
        "name": "校园广播",
        "avatar_key": "av_sys",
        "start_location": "field",
        "persona": {
            "display_name": "校园广播",
            "archetype": "校园里所有公告的来源",
            "mbti_like": {"E_I": 0.0, "S_N": 0.0, "T_F": 0.0, "J_P": 0.0},
            "big_five": {"O": 0.5, "C": 0.9, "E": 0.0, "A": 0.8, "N": 0.0},
            "interests": [
                {"topic": "校园生活", "weight": 1.0, "evidence": []},
                {"topic": "时事", "weight": 0.6, "evidence": []},
                {"topic": "知识分享", "weight": 0.5, "evidence": []},
            ],
            "stances": [],
            "speaking_style": {"tone": "播报腔，简洁", "emoji": False, "length": "短",
                               "catchphrases": ["下面播报一则通知"]},
            "values": ["准确", "及时"],
            "social": {"initiative": 0.0, "group_pref": "独处", "avoid_topics": ["闲聊"]},
            "campus_identity": {"major": "无", "grade": "大四", "club": None},
            "appearance": "一块立在操场边的电子公告屏",
            "summary": "校园里所有公告的来源，只播报事实，不加评论。它不发帖以外的动作，也不参与对话。",
        },
    }


# ─────────────────────────── 日历与默认日程 ───────────────────────────


@lru_cache
def calendar() -> dict[str, Any]:
    return _read_json("calendar.json") or {}


def weekday_courses(weekday: int) -> list[list[str]]:
    return calendar().get("weekday_courses", {}).get(str(weekday), [])


def events_for_day(day: int) -> list[dict[str, Any]]:
    cycle_day = (day - 1) % 7 + 1
    return [e for e in calendar().get("campus_events", []) if e.get("day") == cycle_day]


def is_weekend(day: int) -> bool:
    return ((day - 1) % 7) + 1 in (6, 7)


def default_schedule(day: int) -> DailySchedule:
    """按默认模板填充（04 §3 兜底 / 08 §3）。"""
    key = "weekend" if is_weekend(day) else "weekday"
    blocks = calendar().get("default_schedule", {}).get(key, [])
    raw = [
        {"start": s, "end": e, "location_id": loc, "activity": act}
        for s, e, loc, act in blocks
    ]
    schedule = DailySchedule(blocks=raw)
    if not schedule.is_valid_coverage():
        log.error("默认日程模板非法（%s），使用最小可用日程", key)
        return DailySchedule(
            blocks=[
                {"start": "07:00", "end": "11:30", "location_id": "library", "activity": "自习"},
                {"start": "11:30", "end": "13:00", "location_id": "canteen", "activity": "吃午饭"},
                {"start": "13:00", "end": "17:30", "location_id": "library", "activity": "自习"},
                {"start": "17:30", "end": "19:00", "location_id": "canteen", "activity": "吃晚饭"},
                {"start": "19:00", "end": "21:30", "location_id": "library", "activity": "自习"},
                {"start": "21:30", "end": "23:30", "location_id": "dorm", "activity": "休息"},
            ]
        )
    return schedule


# ─────────────────────────── 头像 ───────────────────────────


@lru_cache
def avatars() -> tuple[dict[str, Any], ...]:
    return tuple(_read_json("avatars.json") or [])


def avatar_keys() -> list[str]:
    return [a["key"] for a in avatars() if a.get("key", "").startswith("av_") and a["key"][3:].isdigit()]


def get_avatar(key: str) -> dict[str, Any]:
    for a in avatars():
        if a["key"] == key:
            return a
    if key == "av_sys":
        return {"key": "av_sys", "bg": "#9ca3af", "emoji": "📣"}
    if key == "av_liukanshan":
        return {"key": "av_liukanshan", "bg": "#eef2ff", "emoji": "🦊"}
    return {"key": key or "av_01", "bg": "#e5e7eb", "emoji": "🙂"}


# ─────────────────────────── 评委 ───────────────────────────


@lru_cache
def judges() -> tuple[dict[str, Any], ...]:
    return tuple(_read_json("judges.json") or [])


def judge_by_username(username: str) -> dict[str, Any] | None:
    for j in judges():
        if j.get("username") == username:
            return j
    return None


# ─────────────────────────── 兴趣词表 ───────────────────────────


INTEREST_VOCAB: tuple[str, ...] = (
    "科技", "人工智能", "编程", "考研", "求职", "职场", "校园生活", "美食", "体育",
    "街舞", "音乐", "文学", "电影", "哲学", "社会议题", "法律", "时事", "自然",
    "摄影", "科幻", "独立游戏", "游戏", "情感", "心理", "效率", "知识分享",
    "旅行", "动漫", "金融", "健康",
)

_EVENT_TAG_ALIASES: dict[str, str] = {
    "社交": "校园生活",
    "机器学习": "人工智能",
    "AI": "人工智能",
    "深度学习": "人工智能",
    "大模型": "人工智能",
    "程序": "编程",
    "代码": "编程",
    "阅读": "文学",
    "诗歌": "文学",
    "看书": "文学",
    "跑步": "体育",
    "运动": "健康",
    "健身": "健康",
    "摄影技巧": "摄影",
    "电影赏析": "电影",
    "游戏开发": "独立游戏",
    "校园": "校园生活",
    "考试": "考研",
    "工作": "职场",
}


def normalize_topic(topic: str) -> str:
    """把 LLM 输出的 topic 归一到词表（08 §2）。"""
    if not topic:
        return "校园生活"
    t = topic.strip()
    if t in INTEREST_VOCAB:
        return t
    if t in _EVENT_TAG_ALIASES:
        return _EVENT_TAG_ALIASES[t]
    # 包含关系
    for word in INTEREST_VOCAB:
        if word in t or t in word:
            return word
    for alias, word in _EVENT_TAG_ALIASES.items():
        if alias in t:
            return word
    return t[:12]


def normalize_tags(tags: list[str]) -> list[str]:
    out: list[str] = []
    for t in tags:
        n = normalize_topic(t)
        if n and n not in out:
            out.append(n)
    return out[:5]


# ─────────────────────────── 预热剧本 ───────────────────────────


@lru_cache
def warmup() -> tuple[dict[str, Any], ...]:
    return tuple(_read_json("warmup.json") or [])


def reload_all() -> None:
    for fn in (locations, npcs, calendar, avatars, judges, warmup):
        fn.cache_clear()


__all__ = [
    "locations", "location_map", "get_location", "npcs", "npc_by_id", "system_character",
    "calendar", "weekday_courses", "events_for_day", "is_weekend", "default_schedule",
    "avatars", "avatar_keys", "get_avatar", "judges", "judge_by_username",
    "INTEREST_VOCAB", "normalize_topic", "normalize_tags", "warmup", "reload_all",
]
