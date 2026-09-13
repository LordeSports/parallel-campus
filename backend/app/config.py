"""环境配置。字段与 spec/09-ops.md §1 的 .env.example 一一对应。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
SEEDS_DIR = Path(__file__).resolve().parent / "seeds"
PROMPTS_DIR = Path(__file__).resolve().parent / "llm" / "prompts"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR / ".env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── 基本 ──
    app_env: str = "dev"
    dev_mode: bool = True
    public_base_url: str = "http://localhost:8000"
    tz: str = "Asia/Shanghai"
    log_level: str = "info"

    # ── 安全 ──
    session_secret: str = "dev-session-secret-not-for-prod"
    token_enc_key: str = ""
    admin_token: str = "dev-admin-token"
    judge_accounts: str = "judge1:changeme1,judge2:changeme2"

    # ── 存储 ──
    database_url: str = "sqlite+aiosqlite:///./data/pc.db"

    # ── 知乎 ──
    zhihu_access_secret: str = ""
    zhihu_oauth_app_id: str = ""
    zhihu_oauth_app_key: str = ""
    zhihu_oauth_redirect_uri: str = "http://localhost:8000/api/auth/zhihu/callback"
    zhihu_api_base: str = "https://developer.zhihu.com"
    zhihu_open_base: str = "https://openapi.zhihu.com"

    # ── LLM ──
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_api_key: str = ""
    llm_model_strong: str = "deepseek-chat"
    llm_model_cheap: str = "deepseek-chat"
    llm_timeout: float = 25.0
    llm_supports_json_mode: bool = True

    # ── 模拟旋钮（spec/04 §10）──
    tick_seconds_online: float = 20.0
    tick_seconds_idle: float = 300.0
    max_concurrent_llm: int = 8
    max_decisions_per_tick: int = 10
    spontaneity: float = 0.15
    stimulus_decide_prob: float = 0.6
    hot_pull_interval_min: int = 60
    hot_daily_cap: int = 24
    zhida_daily_cap: int = 50
    search_daily_cap: int = 200
    whispers_per_day: int = 3

    # ── 其余旋钮（04 §7，未列入 .env.example 但有默认）──
    memory_retrieve_k: int = 8
    dialogue_max_turns: int = 8
    event_interest_inject_max: int = 6

    # ── 人类限流 ──
    human_post_per_hour: int = 5
    human_comment_per_hour: int = 20

    static_dir: str = ""

    @field_validator("database_url")
    @classmethod
    def _normalize_sqlite_url(cls, v: str) -> str:
        # 允许相对 sqlite 路径；保证是 aiosqlite 驱动
        if v.startswith("sqlite://") and not v.startswith("sqlite+aiosqlite://"):
            v = v.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return v

    # ── 派生属性 ──

    @property
    def is_prod(self) -> bool:
        return self.app_env.lower() == "prod"

    @property
    def zhihu_enabled(self) -> bool:
        """无凭证或 DEV_MODE 时使用 MockZhihuClient。"""
        return bool(self.zhihu_access_secret) and not self.dev_mode

    @property
    def judge_account_map(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for part in self.judge_accounts.split(","):
            part = part.strip()
            if not part or ":" not in part:
                continue
            user, _, pw = part.partition(":")
            if user and pw:
                out[user.strip()] = pw.strip()
        return out

    @property
    def cookie_secure(self) -> bool:
        return self.is_prod or self.public_base_url.startswith("https://")

    def sqlite_path(self) -> Path | None:
        """返回 sqlite 文件路径（用于建目录）；非 sqlite 返回 None。"""
        prefix = "sqlite+aiosqlite:///"
        if not self.database_url.startswith(prefix):
            return None
        raw = self.database_url[len(prefix) :]
        if raw.startswith("/") and not raw.startswith("//"):
            # 绝对路径写法 sqlite+aiosqlite:////data/pc.db → raw 为 "//data/pc.db"
            return Path(raw)
        if raw.startswith("//"):
            return Path(raw[1:])
        # 相对路径，相对 backend 目录
        return (BACKEND_DIR / raw).resolve()

    def validate_runtime(self) -> None:
        """prod 启动校验（09 §1）。"""
        if not self.is_prod:
            return
        missing = [
            name
            for name, value in (
                ("SESSION_SECRET", self.session_secret),
                ("TOKEN_ENC_KEY", self.token_enc_key),
                ("ADMIN_TOKEN", self.admin_token),
                ("LLM_API_KEY", self.llm_api_key),
            )
            if not value or value.startswith("dev-")
        ]
        if missing:
            raise RuntimeError(
                "APP_ENV=prod 时以下必填环境变量缺失或仍为默认值: " + ", ".join(missing)
            )
        if self.dev_mode:
            raise RuntimeError("APP_ENV=prod 时 DEV_MODE 必须为 false")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()


def reload_settings() -> Settings:
    """测试用：清缓存后重读。"""
    get_settings.cache_clear()
    global settings
    settings = get_settings()
    return settings


__all__ = ["Settings", "get_settings", "reload_settings", "settings", "BACKEND_DIR", "SEEDS_DIR", "PROMPTS_DIR"]
