"""API 视图 schema（spec/03）。字段名即线上 JSON 字段名。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from ..constants import Board, CharacterKind, LocationId, SseEventType, WeatherKind
from .domain import HotEvents, PersonaFile  # noqa: F401  (re-export 便于 api 层引用)


class View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── 通用 ──


class ErrorBody(View):
    code: str
    message: str
    detail: dict[str, Any] | None = None


class ErrorResponse(View):
    error: ErrorBody


class Page(View):
    items: list[Any]
    next_cursor: str | None = None


# ── 认证 ──


class UserView(View):
    id: str
    display_name: str
    avatar_key: str
    auth_kind: Literal["zhihu", "dev"]
    # player：投放分身；observer：只看世界，不需要人格与分身
    role: Literal["player", "observer"] = "player"
    has_persona: bool = False
    character_id: str | None = None
    zhihu_url: str | None = None


class DevLoginRequest(View):
    name: str = Field(default="测试用户", min_length=1, max_length=24)
    role: Literal["player", "observer"] = "player"


class RoleRequest(View):
    role: Literal["player", "observer"]


# ── 人格 ──


class SourceStats(View):
    contents: int = 0
    followees: int = 0
    favlists: int = 0
    saved_items: int = 0
    failed: list[str] = Field(default_factory=list)


class PersonaResponse(View):
    file: PersonaFile
    thin: bool = False
    version: int = 1
    source_stats: SourceStats = Field(default_factory=SourceStats)
    confirmed_at: str | None = None
    generated_left_today: int = 3


class PersonaUpdateRequest(View):
    file: PersonaFile


class InterviewAnswerRequest(View):
    session_id: str = Field(min_length=1, max_length=40)
    answer: str = Field(min_length=1, max_length=400)


class InterviewFinishRequest(View):
    session_id: str = Field(min_length=1, max_length=40)


class InterviewView(View):
    session_id: str
    round_no: int = 0
    done: bool = False
    progress: int = 0
    messages: list[dict[str, Any]] = Field(default_factory=list)
    question: str = ""
    reply: str = ""
    missing: list[str] = Field(default_factory=list)
    draft: dict[str, Any] | None = None
    max_rounds: int = 8


class DeployRequest(View):
    display_name: str = Field(min_length=1, max_length=24)
    avatar_key: str = "av_01"
    appearance: str = Field(default="", max_length=80)
    major: str = Field(default="", max_length=20)
    grade: Literal["大一", "大二", "大三", "大四", "研一", "研二", "研三"] = "大二"
    club: str | None = Field(default=None, max_length=20)


# ── 世界 ──


class MoodView(View):
    valence: float = 0.0
    arousal: float = 0.0


class WeatherView(View):
    kind: WeatherKind = "sunny"
    temp_c: int = 22
    text: str = ""


class ActiveEventView(View):
    id: str
    kind: str
    title: str
    description: str = ""
    location_id: LocationId | None = None
    start_tick: int = 0
    end_tick: int = 0
    tags: list[str] = Field(default_factory=list)
    source_title: str | None = None
    source_url: str | None = None
    status: str = "active"


class BriefingView(View):
    day: int
    text: str


class WorldStateView(View):
    day: int
    minute_of_day: int
    weekday: int
    tick: int
    time_label: str
    weather: WeatherView
    speed_mode: str
    tick_seconds: float
    observers: int = 0
    degraded: bool = False
    active_events: list[ActiveEventView] = Field(default_factory=list)
    briefing: BriefingView | None = None


class LocationView(View):
    id: LocationId
    name: str
    emoji: str
    x: int
    y: int
    w: int
    h: int
    outdoor: bool
    description: str
    affordances: list[str] = Field(default_factory=list)
    ambience: dict[str, str] = Field(default_factory=dict)
    capacity: int
    occupants: list[str] = Field(default_factory=list)


class CharacterSummaryView(View):
    id: str
    kind: CharacterKind
    name: str
    avatar_key: str
    location_id: LocationId
    activity: str = ""
    mood: MoodView = Field(default_factory=MoodView)
    is_asleep: bool = False
    is_me: bool = False
    dialogue_id: str | None = None
    energy: int = 100


class IdentityView(View):
    major: str = ""
    grade: str = ""
    club: str | None = None


class MemoryItemView(View):
    tick: int
    kind: str
    text: str
    importance: int = 3


class RelationshipItemView(View):
    character_id: str
    name: str
    affinity: int
    tags: list[str] = Field(default_factory=list)


class CharacterDetailView(CharacterSummaryView):
    identity: IdentityView = Field(default_factory=IdentityView)
    appearance: str = ""
    archetype: str = ""
    summary: str = ""
    recent_memories: list[MemoryItemView] = Field(default_factory=list)
    top_relationships: list[RelationshipItemView] = Field(default_factory=list)


class EventView(View):
    id: str
    tick: int
    day: int
    type: str
    actor_id: str | None = None
    target_id: str | None = None
    location_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    time_label: str = ""


class DialogueTurnView(View):
    speaker_id: str
    text: str


class DialogueView(View):
    id: str
    tick: int
    time_label: str
    location_id: LocationId
    a_id: str
    b_id: str
    turns: list[DialogueTurnView] = Field(default_factory=list)
    a_to_b_delta: int = 0
    b_to_a_delta: int = 0
    ended_because: str = ""
    is_player_involved: bool = False


# ── 校园墙 ──


class AuthorView(View):
    id: str
    name: str
    avatar_key: str
    kind: CharacterKind


class SourceView(View):
    title: str
    url: str


class PostView(View):
    id: str
    board: Board
    author: AuthorView | None = None
    author_label: str | None = None
    text: str
    tick: int
    time_label: str = ""
    like_count: int = 0
    comment_count: int = 0
    source: SourceView | None = None
    event_id: str | None = None
    liked_by_me: bool = False


class CommentView(View):
    id: str
    post_id: str
    author: AuthorView | None = None
    author_label: str | None = None
    text: str
    tick: int
    time_label: str = ""


class PostDetailView(View):
    post: PostView
    comments: list[CommentView] = Field(default_factory=list)


class CreatePostRequest(View):
    board: Literal["tree_hole"] = "tree_hole"
    text: str = Field(min_length=1, max_length=500)


class CreateCommentRequest(View):
    text: str = Field(min_length=1, max_length=200)


class LikeResponse(View):
    liked: bool
    like_count: int


# ── 我的分身 ──


class AvatarView(CharacterDetailView):
    whispers_left_today: int = 0
    deployed_at_tick: int = 0
    persona_version: int = 1


class DiaryEntryView(View):
    tick: int
    time_label: str = ""
    type: str
    text: str
    payload: dict[str, Any] = Field(default_factory=dict)


class MoodPointView(View):
    tick: int
    valence: float
    arousal: float


class ReflectionItemView(View):
    tick: int
    text: str
    importance: int = 8


class WhisperItemView(View):
    id: str
    text: str
    tick: int
    accepted: bool | None = None
    reason: str | None = None


class DiaryView(View):
    day: int
    entries: list[DiaryEntryView] = Field(default_factory=list)
    mood_series: list[MoodPointView] = Field(default_factory=list)
    reflections: list[ReflectionItemView] = Field(default_factory=list)
    whispers: list[WhisperItemView] = Field(default_factory=list)


class WhisperRequest(View):
    text: str = Field(min_length=1, max_length=80)


class WhisperResponseView(View):
    whisper_id: str
    whispers_left_today: int


class ReportFriendCharacter(View):
    id: str
    name: str
    avatar_key: str
    kind: CharacterKind
    archetype: str = ""


class ReportFriendView(View):
    character: ReportFriendCharacter
    story: str
    shared_topics: list[str] = Field(default_factory=list)
    affinity: int
    affinity_delta: int
    is_human: bool = False
    zhihu_url: str | None = None


class ReportView(View):
    day: int
    generated_tick: int
    summary: str
    top_friends: list[ReportFriendView] = Field(default_factory=list)


# ── SSE ──


class HelloPayload(View):
    tick: int
    server_time: str
    speed_mode: str


class TickPayload(View):
    tick: int
    day: int
    minute_of_day: int
    time_label: str
    speed_mode: str
    tick_seconds: float


class WeatherPayload(View):
    day: int
    weather: WeatherView


class EventStartedPayload(View):
    event: ActiveEventView


class CharacterMovedPayload(View):
    character_id: str
    from_: LocationId = Field(alias="from")
    to: LocationId
    activity: str = ""

    model_config = ConfigDict(populate_by_name=True)


class CharacterActivityPayload(View):
    character_id: str
    activity: str
    mood: MoodView = Field(default_factory=MoodView)


class DialogueStartedPayload(View):
    dialogue_id: str
    a_id: str
    b_id: str
    location_id: LocationId


class DialogueTurnPayload(View):
    dialogue_id: str
    index: int
    speaker_id: str
    text: str


class DialogueEndedPayload(View):
    dialogue_id: str
    a_id: str
    b_id: str
    a_to_b_delta: int
    b_to_a_delta: int
    ended_because: str = ""


class PostCreatedPayload(View):
    post: PostView


class CommentCreatedPayload(View):
    comment: CommentView
    post_id: str


class LikeCreatedPayload(View):
    post_id: str
    liker_id: str
    like_count: int


class DmSentPayload(View):
    from_id: str
    to_id: str


class WhisperResponsePayload(View):
    character_id: str
    whisper_id: str
    accepted: bool
    reason: str = ""


class ReflectionPayload(View):
    character_id: str
    text: str


class BriefingPayload(View):
    day: int
    text: str


class ReportReadyPayload(View):
    character_id: str
    day: int


class DegradedPayload(View):
    degraded: bool


# ── 管理 ──


class FastForwardResponse(View):
    mode: str
    remaining_ticks: int


class ModeResponse(View):
    mode: str


class LlmTodayView(View):
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    fail_streak: int = 0


class ZhihuTodayView(View):
    hot_list: int = 0
    zhihu_search: int = 0
    zhida: int = 0
    user_data: int = 0


class AdminStatusView(View):
    mode: str
    remaining_ticks: int = 0
    tick: int = 0
    llm_today: LlmTodayView = Field(default_factory=LlmTodayView)
    zhihu_today: ZhihuTodayView = Field(default_factory=ZhihuTodayView)


class HotPullResponse(View):
    events_created: int


class HealthView(View):
    status: str = "ok"
    version: str = "0.1.0"
    build: str = ""
    tick: int = 0
    mode: str = "idle"
    dev_mode: bool = False


__all__ = [name for name in dir() if name.endswith(("View", "Request", "Response", "Payload", "Body"))]
