"""Pydantic 领域 schema（spec/02 §3.2、§3.12、§3.12a、§4）。"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from ..constants import ActionType, Board, LocationId, WeatherKind

MINUTE_RE = r"^([01]\d|2[0-3]):[0-5]\d$"

Grade = Literal["大一", "大二", "大三", "大四", "研一", "研二", "研三"]
SpeakLength = Literal["短", "中", "长"]
GroupPref = Literal["独处", "小圈子", "广交"]


class StrictModel(BaseModel):
    """禁止多余字段，越界即报错——LLM 输出的越界由修复链处理。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


# ─────────────────────────── PersonaFile ───────────────────────────


class Interest(StrictModel):
    topic: str = Field(max_length=12)
    weight: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)


class Stance(StrictModel):
    text: str = Field(max_length=40)
    evidence: list[str] = Field(default_factory=list)


class SpeakingStyle(StrictModel):
    tone: str = Field(default="自然", max_length=30)
    emoji: bool = False
    length: SpeakLength = "中"
    catchphrases: list[str] = Field(default_factory=list)

    @field_validator("catchphrases")
    @classmethod
    def _cap_catchphrases(cls, v: list[str]) -> list[str]:
        return [x[:20] for x in v[:3]]


class Social(StrictModel):
    initiative: float = Field(default=0.5, ge=0.0, le=1.0)
    group_pref: GroupPref = "小圈子"
    avoid_topics: list[str] = Field(default_factory=list)

    @field_validator("avoid_topics")
    @classmethod
    def _cap_avoid(cls, v: list[str]) -> list[str]:
        return [x[:12] for x in v[:5]]


class CampusIdentity(StrictModel):
    major: str = Field(default="未定", max_length=20)
    grade: Grade = "大二"
    club: str | None = Field(default=None, max_length=20)


class PersonaFile(StrictModel):
    display_name: str = Field(min_length=1, max_length=24)
    archetype: str = Field(max_length=20)
    mbti_like: dict[Literal["E_I", "S_N", "T_F", "J_P"], float]
    big_five: dict[Literal["O", "C", "E", "A", "N"], float]
    interests: list[Interest] = Field(min_length=3, max_length=8)
    stances: list[Stance] = Field(default_factory=list, max_length=5)
    speaking_style: SpeakingStyle = Field(default_factory=SpeakingStyle)
    values: list[str] = Field(default_factory=list)
    social: Social = Field(default_factory=Social)
    campus_identity: CampusIdentity = Field(default_factory=CampusIdentity)
    appearance: str = Field(default="", max_length=80)
    summary: str = Field(min_length=1, max_length=400)

    @field_validator("values")
    @classmethod
    def _cap_values(cls, v: list[str]) -> list[str]:
        return [x[:6] for x in v[:4]]

    @field_validator("mbti_like", mode="before")
    @classmethod
    def _fill_mbti(cls, v: Any) -> dict[str, float]:
        keys = ("E_I", "S_N", "T_F", "J_P")
        data = v if isinstance(v, dict) else {}
        out: dict[str, float] = {}
        for k in keys:
            try:
                out[k] = max(-1.0, min(1.0, float(data.get(k, 0.0))))
            except (TypeError, ValueError):
                out[k] = 0.0
        return out

    @field_validator("big_five", mode="before")
    @classmethod
    def _fill_big_five(cls, v: Any) -> dict[str, float]:
        keys = ("O", "C", "E", "A", "N")
        data = v if isinstance(v, dict) else {}
        out: dict[str, float] = {}
        for k in keys:
            try:
                out[k] = max(0.0, min(1.0, float(data.get(k, 0.5))))
            except (TypeError, ValueError):
                out[k] = 0.5
        return out

    @model_validator(mode="after")
    def _sort_interests(self) -> PersonaFile:
        self.interests = sorted(self.interests, key=lambda i: i.weight, reverse=True)
        return self

    # ── 摘要形式（05 §1.5，≤400 字）──
    def brief(self) -> str:
        top = "、".join(f"{i.topic}({i.weight:.1f})" for i in self.interests[:5])
        style = self.speaking_style
        catch = ("／".join(style.catchphrases)) or "无口头禅"
        ident = self.campus_identity
        club = f"；{ident.club}" if ident.club else ""
        summary_head = self.summary[:150]
        return (
            f"{self.display_name}：{self.archetype}。"
            f"{summary_head}"
            f"｜兴趣：{top}｜说话：{style.tone}，{style.length}句，口头禅{catch}"
            f"｜社交：{style and self.social.group_pref}，主动度{self.social.initiative:.1f}"
            f"｜价值观：{'、'.join(self.values) or '—'}"
            f"｜身份：{ident.major} {ident.grade}{club}"
        )

    def mood_relevant_topics(self, n: int = 4) -> list[str]:
        return [i.topic for i in self.interests[:n]]


class InterviewTurn(StrictModel):
    """对话式画像访谈：LLM 每轮的输出。

    - `reply` 是对上一段回答的回应（展示给用户）
    - `question` 是下一个问题；`done=true` 时应为空
    - `draft` 每轮都带全量画像（前端实时可见画像在"长出来"）
    - `missing` 列出还缺什么，用于展示"还想知道"
    """

    reply: str = Field(default="", max_length=240)
    question: str = Field(default="", max_length=160)
    done: bool = False
    progress: int = Field(default=40, ge=0, le=100)
    missing: list[str] = Field(default_factory=list)
    draft: PersonaFile | None = None


# ─────────────────────────── 日程 ───────────────────────────


class ScheduleBlock(StrictModel):
    start: str = Field(pattern=MINUTE_RE)
    end: str = Field(pattern=MINUTE_RE)
    location_id: LocationId
    activity: str = Field(max_length=30)

    @property
    def start_minute(self) -> int:
        h, m = self.start.split(":")
        return int(h) * 60 + int(m)

    @property
    def end_minute(self) -> int:
        h, m = self.end.split(":")
        return int(h) * 60 + int(m)


class DailySchedule(StrictModel):
    blocks: list[ScheduleBlock]

    @model_validator(mode="after")
    def _sorted(self) -> DailySchedule:
        self.blocks = sorted(self.blocks, key=lambda b: b.start_minute)
        return self

    def block_at(self, minute_of_day: int) -> ScheduleBlock | None:
        for b in self.blocks:
            if b.start_minute <= minute_of_day < b.end_minute:
                return b
        return None

    def next_block(self, minute_of_day: int) -> ScheduleBlock | None:
        for b in self.blocks:
            if b.start_minute > minute_of_day:
                return b
        return None

    def at_boundary(self, minute_of_day: int) -> bool:
        """当前时刻是否为某块的开始（含跨日边界 07:00）。"""
        return any(b.start_minute == minute_of_day for b in self.blocks)

    def is_valid_coverage(self) -> bool:
        """07:00–23:30 无缝、无重叠、30 分对齐、块数 1..14。"""
        if not self.blocks or len(self.blocks) > 14:
            return False
        cursor = 420
        for b in self.blocks:
            if b.start_minute != cursor or b.end_minute <= b.start_minute:
                return False
            if b.start_minute % 30 or b.end_minute % 30:
                return False
            cursor = b.end_minute
        return cursor == 1410


# ─────────────────────────── Decision / Dialogue ───────────────────────────


class Action(StrictModel):
    type: ActionType
    location_id: LocationId | None = None
    target_id: str | None = None
    post_id: str | None = None
    board: Literal["wall", "tree_hole"] | None = None
    text: str | None = None
    query: str | None = None
    event_id: str | None = None


class WhisperResponse(StrictModel):
    accepted: bool
    reason: str = Field(max_length=30)


class MemoryDraft(StrictModel):
    text: str = Field(max_length=60)
    importance: int = Field(default=3, ge=1, le=10)


class MoodDelta(StrictModel):
    valence: float = Field(default=0.0, ge=-0.3, le=0.3)
    arousal: float = Field(default=0.0, ge=-0.3, le=0.3)


class Decision(StrictModel):
    thought: str = Field(max_length=40)
    action: Action
    mood_delta: MoodDelta = Field(default_factory=MoodDelta)
    whisper_response: WhisperResponse | None = None
    memory: MemoryDraft | None = None


class DialogueTurn(StrictModel):
    speaker_id: str
    text: str = Field(max_length=60)


class DialogueSide(StrictModel):
    affinity_delta: int = Field(ge=-20, le=25)
    tags: list[str] = Field(default_factory=list)
    memory: str = Field(max_length=60)

    @field_validator("tags")
    @classmethod
    def _cap_tags(cls, v: list[str]) -> list[str]:
        return [x[:8] for x in v[:3]]


class DialogueModel(StrictModel):
    turns: list[DialogueTurn] = Field(min_length=1)
    a_to_b: DialogueSide
    b_to_a: DialogueSide
    mood_a: MoodDelta
    mood_b: MoodDelta
    ended_because: str = Field(max_length=20)


# ─────────────────────────── 环境 agent 输出 ───────────────────────────


class Weather(StrictModel):
    kind: WeatherKind
    temp_c: int = Field(ge=5, le=35)
    text: str = Field(max_length=40)


class NewDay(StrictModel):
    weather: Weather
    announcements: list[str] = Field(default_factory=list)

    @field_validator("announcements")
    @classmethod
    def _cap_ann(cls, v: list[str]) -> list[str]:
        return [x[:60] for x in v[:2]]


class HotEvent(StrictModel):
    title: str = Field(max_length=30)
    description: str = Field(max_length=120)
    location_id: LocationId
    duration_ticks: int = Field(ge=4, le=12)
    tags: list[str] = Field(default_factory=list)
    wall_post: str = Field(max_length=140)
    source_index: str = "H1"

    @field_validator("tags")
    @classmethod
    def _cap_tags(cls, v: list[str]) -> list[str]:
        return [x[:8] for x in v[:5]]


class HotEvents(StrictModel):
    events: list[HotEvent] = Field(default_factory=list)


class Briefing(StrictModel):
    text: str = Field(max_length=150)


class ReflectionInsight(StrictModel):
    text: str = Field(max_length=80)
    importance: int = Field(default=8, ge=5, le=10)


class Reflection(StrictModel):
    insights: list[ReflectionInsight] = Field(default_factory=list)

    @field_validator("insights")
    @classmethod
    def _cap_insights(cls, v: list[ReflectionInsight]) -> list[ReflectionInsight]:
        """05 §3 P5：最多 3 条。"""
        return v[:3]


class ScheduleBatch(StrictModel):
    """NPC 批量日程（05 §3 P2 batch）。"""

    schedules: dict[str, DailySchedule] = Field(default_factory=dict)


# ─────────────────────────── 报告 ───────────────────────────


class FriendEntry(StrictModel):
    character_id: str
    story: str = Field(max_length=160)
    shared_topics: list[str] = Field(default_factory=list)
    affinity: int
    affinity_delta: int

    @field_validator("shared_topics")
    @classmethod
    def _cap_topics(cls, v: list[str]) -> list[str]:
        return [x[:12] for x in v[:5]]


class MatchReport(StrictModel):
    day_summary: str = Field(max_length=200)
    top_friends: list[FriendEntry] = Field(default_factory=list)

    @field_validator("top_friends")
    @classmethod
    def _cap_friends(cls, v: list[FriendEntry]) -> list[FriendEntry]:
        return v[:3]


# ─────────────────────────── 刺激 ───────────────────────────


StimulusKind = Literal[
    "whisper", "dm_unread", "mention", "new_face", "post_relevant",
    "event_here", "event_interest", "crowd",
]


class Stimulus(StrictModel):
    kind: StimulusKind
    ref_id: str | None = None
    text: str = Field(max_length=60)
    salience: int = Field(ge=1, le=10)


# ─────────────────────────── 地点（seeds，不入库）───────────────────────────


class Location(StrictModel):
    id: LocationId
    name: str = Field(max_length=20)
    emoji: str
    x: int
    y: int
    w: int
    h: int
    outdoor: bool
    description: str = Field(max_length=60)
    affordances: list[str] = Field(default_factory=list)
    ambience: dict[str, str] = Field(default_factory=dict)
    capacity: int = Field(gt=0)

    def ambience_text(self, minute_of_day: int, weather: WeatherKind | None = None) -> str:
        slot = time_slot(minute_of_day)
        base = self.ambience.get(slot, "")
        if weather in ("rainy", "windy"):
            extra = self.ambience.get(weather, "")
            if extra:
                return f"{base}。{extra}" if base else extra
        return base


def time_slot(minute_of_day: int) -> str:
    """07:00–10:30 morning · 11:00–13:30 noon · 14:00–17:30 afternoon
    · 18:00–22:30 evening · 其他 night（08 §1）"""
    if 420 <= minute_of_day < 630:
        return "morning"
    if 660 <= minute_of_day < 810:
        return "noon"
    if 840 <= minute_of_day < 1050:
        return "afternoon"
    if 1080 <= minute_of_day < 1350:
        return "evening"
    return "night"


# 便于 LLM schema 文档生成
__all__ = [
    "StrictModel", "Interest", "Stance", "SpeakingStyle", "Social", "CampusIdentity",
    "PersonaFile", "ScheduleBlock", "DailySchedule", "Action", "WhisperResponse",
    "MemoryDraft", "MoodDelta", "Decision", "DialogueTurn", "DialogueSide",
    "DialogueModel", "Weather", "NewDay", "HotEvent", "HotEvents", "Briefing",
    "ReflectionInsight", "Reflection", "ScheduleBatch", "FriendEntry", "MatchReport",
    "Stimulus", "StimulusKind", "Location", "time_slot",
    "Annotated", "Grade",
]
