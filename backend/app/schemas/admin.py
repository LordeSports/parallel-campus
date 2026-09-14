"""管理员输入与脱敏视图（spec/11）。"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..constants import LocationId, WeatherKind
from .domain import PersonaFile
from .views import ActiveEventView, AdminStatusView, CharacterSummaryView, WorldStateView


class AdminInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AdminLoginRequest(AdminInput):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=256)


class AdminSessionView(BaseModel):
    enabled: bool
    authenticated: bool
    username: str | None = None


class SimulationRequest(AdminInput):
    mode: Literal["auto", "paused", "idle", "online", "fast_forward"]
    tick_seconds_online: float = Field(default=20, ge=1, le=3600, allow_inf_nan=False)
    tick_seconds_idle: float = Field(default=300, ge=1, le=86400, allow_inf_nan=False)
    ticks: int = Field(default=48, ge=1, le=1000)


class ClockRequest(AdminInput):
    day: int = Field(ge=1, le=100000)
    minute_of_day: int = Field(ge=360, le=1410, multiple_of=30)


class AdminWeatherRequest(AdminInput):
    kind: WeatherKind
    temp_c: int = Field(ge=-50, le=60)
    text: str = Field(default="", max_length=80)


class NpcRequest(AdminInput):
    name: str = Field(min_length=1, max_length=24)
    avatar_key: str = Field(default="av_01", max_length=20)
    persona: PersonaFile
    location_id: LocationId = "dorm"
    activity: str = Field(default="在校园里", max_length=30)
    energy: int = Field(default=100, ge=0, le=100)
    mood_valence: float = Field(default=0, ge=-1, le=1, allow_inf_nan=False)
    mood_arousal: float = Field(default=0, ge=-1, le=1, allow_inf_nan=False)
    is_asleep: bool = False
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("名字不能为空")
        return value.strip()


class NpcView(CharacterSummaryView):
    is_active: bool
    persona: PersonaFile


class SceneRequest(AdminInput):
    title: str = Field(min_length=1, max_length=30)
    description: str = Field(default="", max_length=120)
    location_id: LocationId
    duration_ticks: int = Field(default=6, ge=1, le=96)
    tags: list[str] = Field(default_factory=list, max_length=5)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()

    @field_validator("tags")
    @classmethod
    def validate_tags(cls, value: list[str]) -> list[str]:
        if any(len(tag) > 12 for tag in value):
            raise ValueError("每个标签最多 12 字")
        return list(dict.fromkeys(tag.strip() for tag in value if tag.strip()))


class CampusLocationRequest(AdminInput):
    id: str = Field(min_length=2, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=20)
    emoji: str = Field(default="📍", min_length=1, max_length=8)
    x: int = Field(ge=0, le=920)
    y: int = Field(ge=0, le=540)
    w: int = Field(ge=80, le=500)
    h: int = Field(ge=60, le=300)
    outdoor: bool = False
    description: str = Field(default="", max_length=60)
    affordances: list[str] = Field(default_factory=list, max_length=8)
    ambience: dict[str, str] = Field(default_factory=dict)
    capacity: int = Field(default=20, ge=1, le=200)
    is_active: bool = True

    @field_validator("name")
    @classmethod
    def location_name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("地点名称不能为空")
        return value.strip()

    @field_validator("affordances")
    @classmethod
    def normalize_affordances(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip()[:12] for item in value if item.strip()))[:8]


class ApiSettingsRequest(AdminInput):
    llm_base_url: str = Field(max_length=300)
    llm_model_strong: str = Field(min_length=1, max_length=80)
    llm_model_cheap: str = Field(min_length=1, max_length=80)
    llm_enabled: bool = True
    llm_api_key: SecretStr | None = Field(default=None, max_length=4096)
    zhihu_access_secret: SecretStr | None = Field(default=None, max_length=4096)
    zhihu_oauth_app_id: str = Field(default="", max_length=200)
    zhihu_oauth_app_key: SecretStr | None = Field(default=None, max_length=4096)
    clear_llm_api_key: bool = False
    clear_zhihu_access_secret: bool = False
    clear_zhihu_oauth_app_key: bool = False

    @field_validator("llm_model_strong", "llm_model_cheap")
    @classmethod
    def nonempty_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("模型名称不能为空")
        return value.strip()

    @field_validator("llm_base_url")
    @classmethod
    def valid_base_url(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("请填写不含凭证、查询参数或片段的 HTTP(S) 地址")
        return value


class ApiSettingsView(BaseModel):
    llm_base_url: str
    llm_model_strong: str
    llm_model_cheap: str
    llm_enabled: bool = True
    llm_api_key_configured: bool
    zhihu_access_secret_configured: bool
    zhihu_oauth_app_id: str
    zhihu_oauth_app_key_configured: bool
    dev_mode: bool
    tick_seconds_online: float
    tick_seconds_idle: float


class UsageGroupView(BaseModel):
    model: str
    calls: int
    prompt_tokens: int
    completion_tokens: int


class UsageItemView(BaseModel):
    id: str
    at: str
    model: str
    tier: str
    template: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int
    ok: bool
    error: str | None = None


class AdminOverviewView(BaseModel):
    world: WorldStateView
    status: AdminStatusView
    control_mode: str
    counts: dict[str, int]
    usage_by_model: list[UsageGroupView]
    recent_usage: list[UsageItemView]
    scenes: list[ActiveEventView]
