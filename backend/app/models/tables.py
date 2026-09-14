"""SQLModel 表定义（spec/02 §3 全部实体）。

JSON 列统一用 `sa_column=Column(JSON)`，避免 SQLModel 把 dict/list 当字符串。
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import JSON, Column, Index, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from ..constants import (
    Board,
    CharacterKind,
    EventKind,
    MemoryKind,
    SpeedMode,
    WeatherKind,
)


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str, n: int = 12) -> str:
    """`u_`+12 base32 风格 ID（02 §1 约定）。"""
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"
    raw = uuid.uuid4().int
    out = []
    for _ in range(n):
        out.append(alphabet[raw & 31])
        raw >>= 5
    return prefix + "".join(out)


# ─────────────────────────── 3.1 User ───────────────────────────


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(primary_key=True)
    display_name: str = Field(max_length=24)
    avatar_key: str = "av_01"
    auth_kind: str = Field(default="dev", max_length=10)  # zhihu | dev | judge
    zhihu_uid: str | None = Field(default=None, index=True)
    zhihu_url_token: str | None = Field(default=None)
    zhihu_token_enc: bytes | None = Field(default=None)
    token_expires_at: datetime | None = Field(default=None)
    is_judge: bool = Field(default=False)
    judge_username: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=now_utc)
    last_login_at: datetime = Field(default_factory=now_utc)


# ─────────────────────────── 3.2 Persona ───────────────────────────


class Persona(SQLModel, table=True):
    __tablename__ = "personas"

    id: str = Field(primary_key=True)
    user_id: str = Field(index=True, unique=True)
    file: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    thin: bool = Field(default=False)
    source_stats: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    version: int = Field(default=1)
    generated_count_today: int = Field(default=0)
    generated_on: date | None = Field(default=None)
    confirmed_at: datetime | None = Field(default=None)
    created_at: datetime = Field(default_factory=now_utc)


# ─────────────────────────── 3.3 Character ───────────────────────────


class Character(SQLModel, table=True):
    __tablename__ = "characters"

    id: str = Field(primary_key=True)
    kind: str = Field(default="npc", max_length=10)  # CharacterKind
    user_id: str | None = Field(default=None, index=True)
    name: str = Field(max_length=24)
    avatar_key: str = "av_01"
    persona: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    location_id: str = Field(default="dorm", max_length=20, index=True)
    activity: str = Field(default="", max_length=30)
    mood_valence: float = Field(default=0.0)
    mood_arousal: float = Field(default=0.0)
    energy: int = Field(default=100)
    schedule: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    schedule_day: int = Field(default=0)
    is_asleep: bool = Field(default=False)
    pending_whisper_id: str | None = Field(default=None)
    dialogue_id: str | None = Field(default=None)
    last_decided_tick: int = Field(default=-99)
    deployed_at_tick: int = Field(default=0)
    is_active: bool = Field(default=True)
    # 内部状态（不对外暴露）
    attended_event_ids: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_observation_key: str = Field(default="")
    created_at: datetime = Field(default_factory=now_utc)


Index("ix_characters_active_kind", Character.is_active, Character.kind)


# ─────────────────────────── 3.3a CampusLocation（管理员布局）───────────────────────────


class CampusLocation(SQLModel, table=True):
    """管理员可编辑的校园地点覆盖层；无记录时回退到 seeds/locations.json。"""

    __tablename__ = "campus_locations"

    id: str = Field(primary_key=True, max_length=32)
    name: str = Field(max_length=20)
    emoji: str = Field(default="📍", max_length=8)
    x: int = Field(default=40, ge=0, le=1000)
    y: int = Field(default=40, ge=0, le=600)
    w: int = Field(default=180, ge=80, le=500)
    h: int = Field(default=120, ge=60, le=300)
    outdoor: bool = Field(default=False)
    description: str = Field(default="", max_length=60)
    affordances: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    ambience: dict[str, str] = Field(default_factory=dict, sa_column=Column(JSON))
    capacity: int = Field(default=20, ge=1, le=200)
    is_active: bool = Field(default=True)
    updated_at: datetime = Field(default_factory=now_utc)


# ─────────────────────────── 3.4 Relationship ───────────────────────────


class Relationship(SQLModel, table=True):
    __tablename__ = "relationships"
    __table_args__ = (UniqueConstraint("from_id", "to_id", name="uq_rel_pair"),)

    id: str = Field(default_factory=lambda: new_id("rel_"), primary_key=True)
    from_id: str = Field(index=True)
    to_id: str = Field(index=True)
    affinity: int = Field(default=0)
    familiarity: float = Field(default=0.0)
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    last_interaction_tick: int | None = Field(default=None)
    dialogue_count: int = Field(default=0)
    affinity_delta_today: int = Field(default=0)


# ─────────────────────────── 3.5 Memory ───────────────────────────


class Memory(SQLModel, table=True):
    __tablename__ = "memories"

    id: str = Field(default_factory=lambda: new_id("mem_"), primary_key=True)
    character_id: str = Field(index=True)
    tick: int = Field(default=0, index=True)
    day: int = Field(default=1)
    kind: str = Field(default="observation", max_length=12)
    text: str = Field(max_length=200)
    importance: int = Field(default=3)
    keywords: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    ref_id: str | None = Field(default=None)
    consumed: bool = Field(default=False)
    visible: bool = Field(default=True)


Index("ix_memories_char_tick", Memory.character_id, Memory.tick)


# ─────────────────────────── 3.6 Post / Comment / Like ───────────────────────────


class Post(SQLModel, table=True):
    __tablename__ = "posts"

    id: str = Field(default_factory=lambda: new_id("p_"), primary_key=True)
    board: str = Field(default="wall", max_length=12, index=True)
    author_id: str | None = Field(default=None, index=True)
    author_label: str | None = Field(default=None)
    text: str = Field(max_length=500)
    tick: int = Field(default=0, index=True)
    day: int = Field(default=1, index=True)
    like_count: int = Field(default=0)
    comment_count: int = Field(default=0)
    source_title: str | None = Field(default=None)
    source_url: str | None = Field(default=None)
    event_id: str | None = Field(default=None, index=True)
    deleted: bool = Field(default=False)


Index("ix_posts_board_tick", Post.board, Post.tick)


class Comment(SQLModel, table=True):
    __tablename__ = "comments"

    id: str = Field(default_factory=lambda: new_id("c_"), primary_key=True)
    post_id: str = Field(index=True)
    author_id: str | None = Field(default=None)
    author_label: str | None = Field(default=None)
    text: str = Field(max_length=200)
    tick: int = Field(default=0)
    day: int = Field(default=1)
    deleted: bool = Field(default=False)


class Like(SQLModel, table=True):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("post_id", "liker_id", name="uq_like_pair"),)

    id: str = Field(default_factory=lambda: new_id("lk_"), primary_key=True)
    post_id: str = Field(index=True)
    liker_id: str = Field(index=True)
    tick: int = Field(default=0)


# ─────────────────────────── 3.7 Message ───────────────────────────


class Message(SQLModel, table=True):
    __tablename__ = "messages"

    id: str = Field(default_factory=lambda: new_id("m_"), primary_key=True)
    from_id: str = Field(index=True)
    to_id: str = Field(index=True)
    text: str = Field(max_length=200)
    tick: int = Field(default=0)
    day: int = Field(default=1)
    read: bool = Field(default=False)


Index("ix_messages_to_unread", Message.to_id, Message.read)


# ─────────────────────────── 3.8 Dialogue ───────────────────────────


class Dialogue(SQLModel, table=True):
    __tablename__ = "dialogues"

    id: str = Field(default_factory=lambda: new_id("d_"), primary_key=True)
    tick: int = Field(default=0, index=True)
    day: int = Field(default=1, index=True)
    location_id: str = Field(default="library", max_length=20)
    a_id: str = Field(index=True)
    b_id: str = Field(index=True)
    turns: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    a_to_b_delta: int = Field(default=0)
    b_to_a_delta: int = Field(default=0)
    ended_because: str = Field(default="", max_length=30)
    tier: str = Field(default="cheap", max_length=8)
    is_player_involved: bool = Field(default=False)


# ─────────────────────────── 3.9 WorldEvent ───────────────────────────


class WorldEvent(SQLModel, table=True):
    __tablename__ = "world_events"

    id: str = Field(default_factory=lambda: new_id("e_"), primary_key=True)
    kind: str = Field(default="adhoc", max_length=12)  # EventKind
    title: str = Field(max_length=30)
    description: str = Field(default="", max_length=120)
    location_id: str | None = Field(default=None, max_length=20)
    start_tick: int = Field(default=0, index=True)
    end_tick: int = Field(default=0, index=True)
    tags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_title: str | None = Field(default=None)
    source_url: str | None = Field(default=None)
    post_id: str | None = Field(default=None)
    status: str = Field(default="scheduled", max_length=12, index=True)


# ─────────────────────────── 3.10 Event（SSE 回放）───────────────────────────


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: str = Field(default_factory=lambda: new_id("ev_"), primary_key=True)
    tick: int = Field(default=0, index=True)
    day: int = Field(default=1)
    type: str = Field(max_length=24, index=True)
    actor_id: str | None = Field(default=None, index=True)
    target_id: str | None = Field(default=None, index=True)
    location_id: str | None = Field(default=None, max_length=20)
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=now_utc)


Index("ix_events_tick_type", Event.tick, Event.type)


# ─────────────────────────── 3.11 Whisper ───────────────────────────


class Whisper(SQLModel, table=True):
    __tablename__ = "whispers"

    id: str = Field(default_factory=lambda: new_id("w_"), primary_key=True)
    character_id: str = Field(index=True)
    user_id: str = Field(index=True)
    text: str = Field(max_length=80)
    tick: int = Field(default=0)
    day: int = Field(default=1)
    accepted: bool | None = Field(default=None)
    reason: str | None = Field(default=None, max_length=30)
    responded_tick: int | None = Field(default=None)


# ─────────────────────────── 3.12 Report ───────────────────────────


class Report(SQLModel, table=True):
    __tablename__ = "reports"
    __table_args__ = (UniqueConstraint("character_id", "day", name="uq_report_char_day"),)

    id: str = Field(default_factory=lambda: new_id("r_"), primary_key=True)
    character_id: str = Field(index=True)
    day: int = Field(default=1)
    content: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    generated_tick: int = Field(default=0)


# ─────────────────────────── 3.13 WorldState ───────────────────────────


class WorldState(SQLModel, table=True):
    __tablename__ = "world_state"

    id: int = Field(default=1, primary_key=True)
    day: int = Field(default=1)
    minute_of_day: int = Field(default=420)  # 以 07:00 开局
    weekday: int = Field(default=1)
    tick: int = Field(default=0)
    weather: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    speed_mode: str = Field(default="idle", max_length=16)
    admin_override: str | None = Field(default=None, max_length=16)
    remaining_ticks: int = Field(default=0)
    last_hot_pull_at: datetime | None = Field(default=None)
    hot_pull_count_today: int = Field(default=0)
    last_briefing: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    degraded: bool = Field(default=False)
    llm_fail_streak: int = Field(default=0)
    observer_count: int = Field(default=0)
    updated_at: datetime = Field(default_factory=now_utc)


# ─────────────────────────── 3.14 ZhihuCache / QuotaLog ───────────────────────────


class ZhihuCache(SQLModel, table=True):
    __tablename__ = "zhihu_cache"

    key: str = Field(primary_key=True)
    value: Any = Field(default=None, sa_column=Column(JSON))
    api: str = Field(default="", max_length=20, index=True)
    expires_at: datetime = Field(default_factory=now_utc, index=True)


class QuotaLog(SQLModel, table=True):
    __tablename__ = "quota_log"
    __table_args__ = (UniqueConstraint("api", "date", name="uq_quota_api_date"),)

    id: str = Field(default_factory=lambda: new_id("q_"), primary_key=True)
    api: str = Field(max_length=20, index=True)  # hot_list|zhihu_search|zhida|user_data
    date: str = Field(max_length=10, index=True)  # 北京时间自然日 YYYY-MM-DD
    count: int = Field(default=0)


# ─────────────────────────── 3.15 LlmUsage ───────────────────────────


class LlmUsage(SQLModel, table=True):
    __tablename__ = "llm_usage"

    id: str = Field(default_factory=lambda: new_id("llm_"), primary_key=True)
    at: datetime = Field(default_factory=now_utc, index=True)
    tier: str = Field(default="cheap", max_length=8)
    template: str = Field(default="", max_length=40)
    model: str = Field(default="", max_length=60)
    prompt_tokens: int = Field(default=0)
    completion_tokens: int = Field(default=0)
    latency_ms: int = Field(default=0)
    ok: bool = Field(default=True)
    error: str | None = Field(default=None, max_length=200)


# ─────────────────────────── 人类限流日志 ───────────────────────────


class HumanRateLog(SQLModel, table=True):
    """人类发帖/评论/耳语限流（03 §5 429 / 04 §10 WHISPERS_PER_DAY）。"""

    __tablename__ = "human_rate_log"

    id: str = Field(default_factory=lambda: new_id("hrl_"), primary_key=True)
    user_id: str = Field(index=True)
    action: str = Field(max_length=20, index=True)  # post | comment | whisper
    at: datetime = Field(default_factory=now_utc, index=True)
    day: int = Field(default=1, index=True)


# ─────────────────────────── 3.15 可编辑校园地图 ───────────────────────────
#
# 与 `CampusLocation` 的分工：
# - `CampusLocation` 是**地点语义**（角色归属、容量、氛围），角色移动仍以它为准；
# - `CampusMapObject` 是**视觉层**（手绘等距地图上的建筑/摆件/地块），
#   `building` 类对象通过 `location_id` 回指地点，用于把角色画在对应建筑上。
# 两者解耦：管理员重画地图不会影响模拟逻辑。


class CampusMap(SQLModel, table=True):
    """地图元信息（单行，id=1）。`version` 用于玩家端失效判断与 SSE 同步。"""

    __tablename__ = "campus_map"

    id: int = Field(default=1, primary_key=True)
    version: int = Field(default=1)
    # 网格尺寸（tile 数）；等距投影的绘制范围
    cols: int = Field(default=36, ge=8, le=128)
    rows: int = Field(default=26, ge=8, le=128)
    # 地图主题名（展示用）
    title: str = Field(default="平行校园", max_length=24)
    updated_at: datetime = Field(default_factory=now_utc)
    updated_by: str | None = Field(default=None, max_length=32)


class CampusMapObject(SQLModel, table=True):
    """地图上的一个可编辑对象：地面块 / 建筑 / 摆件。

    坐标与尺寸都用 **tile** 为单位（浮点，支持半格吸附），渲染时再投影到屏幕。
    """

    __tablename__ = "campus_map_objects"

    id: str = Field(default_factory=lambda: new_id("mo_"), primary_key=True)
    kind: str = Field(max_length=12, index=True)  # ground | building | prop
    variant: str = Field(max_length=24)           # grass/dirt/water | 建筑样式 | tree/rock/bench
    tx: float = Field(default=0.0)
    ty: float = Field(default=0.0)
    tw: float = Field(default=1.0, ge=0.25, le=128.0)
    th: float = Field(default=1.0, ge=0.25, le=128.0)
    # 立面高度（tile）。地面为 0；建筑 2~8
    height: float = Field(default=0.0, ge=0.0, le=16.0)
    # 绘制层级：地面 0、摆件 10、建筑 20（同层再按深度排序）
    layer: int = Field(default=0)
    name: str = Field(default="", max_length=24)
    location_id: str | None = Field(default=None, max_length=32, index=True)
    # 渲染参数（色调偏移、纹理种子、旋转等），避免为每个变体加列
    props: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    sort_order: int = Field(default=0)


__all__ = [
    "User", "Persona", "Character", "CampusLocation", "Relationship", "Memory", "Post", "Comment", "Like",
    "Message", "Dialogue", "WorldEvent", "Event", "Whisper", "Report", "WorldState",
    "ZhihuCache", "QuotaLog", "LlmUsage", "HumanRateLog",
    "CampusMap", "CampusMapObject",
    "new_id", "now_utc",
    "String",
]

# 保证 `from . import models` 后全部表注册（db.init_db 依赖）
from ..constants import Board as _Board  # noqa: E402,F401
from ..constants import CharacterKind as _CK  # noqa: E402,F401
from ..constants import EventKind as _EK  # noqa: E402,F401
from ..constants import MemoryKind as _MK  # noqa: E402,F401
from ..constants import SpeedMode as _SM  # noqa: E402,F401
from ..constants import WeatherKind as _WK  # noqa: E402,F401
