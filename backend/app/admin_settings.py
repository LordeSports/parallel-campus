"""运行配置：加密落卷，白名单更新；不记录或回显 Key。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .config import BACKEND_DIR, settings
from .errors import ValidationError
from .schemas.admin import ApiSettingsRequest, ApiSettingsView

FIELDS = (
    "llm_base_url", "llm_model_strong", "llm_model_cheap", "llm_api_key", "llm_enabled",
    "zhihu_access_secret", "zhihu_oauth_app_id", "zhihu_oauth_app_key",
    "tick_seconds_online", "tick_seconds_idle",
)
SECRETS = ("llm_api_key", "zhihu_access_secret", "zhihu_oauth_app_key")


def settings_path() -> Path:
    if settings.admin_settings_file:
        return Path(settings.admin_settings_file)
    db_path = settings.sqlite_path()
    return (db_path.parent if db_path else BACKEND_DIR / "data") / "admin-settings.enc"


def _cipher() -> Fernet:
    key = hmac.new(settings.session_secret.encode(), b"pc-admin-settings-v1", hashlib.sha256).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def _read() -> dict:
    path = settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(_cipher().decrypt(path.read_bytes()))
        if not isinstance(data, dict) or set(data) - set(FIELDS):
            raise ValueError("unknown settings")
        return data
    except (InvalidToken, ValueError) as exc:
        raise RuntimeError("管理员配置无法解密，请确认 SESSION_SECRET 与保存时一致") from exc


def load_runtime_settings() -> None:
    for name, value in _read().items():
        setattr(settings, name, value)


async def reload_clients() -> None:
    """配置变更后重建客户端并保留用量记录回调；调用时不应有在途 LLM。"""
    from .llm.gateway import get_llm, reset_llm
    from .zhihu.content import aclose

    old = get_llm()
    await old.aclose()
    reset_llm()
    get_llm().usage_sink = old.usage_sink
    await aclose()


def save_runtime_settings(changes: dict) -> None:
    """调用方持有 write_lock，文件成功替换后才更新内存。"""
    if set(changes) - set(FIELDS):
        raise ValueError("unsupported runtime setting")
    data = {**_read(), **changes}
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    blob = _cipher().encrypt(json.dumps(data, ensure_ascii=False).encode())
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(blob)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)
    for name, value in changes.items():
        setattr(settings, name, value)


def public_settings() -> ApiSettingsView:
    return ApiSettingsView(
        llm_base_url=settings.llm_base_url,
        llm_model_strong=settings.llm_model_strong,
        llm_model_cheap=settings.llm_model_cheap,
        llm_enabled=settings.llm_enabled,
        llm_api_key_configured=bool(settings.llm_api_key),
        zhihu_access_secret_configured=bool(settings.zhihu_access_secret),
        zhihu_oauth_app_id=settings.zhihu_oauth_app_id,
        zhihu_oauth_app_key_configured=bool(settings.zhihu_oauth_app_key),
        dev_mode=settings.dev_mode,
        tick_seconds_online=settings.tick_seconds_online,
        tick_seconds_idle=settings.tick_seconds_idle,
    )


def api_changes(payload: ApiSettingsRequest) -> dict:
    if (payload.llm_base_url != settings.llm_base_url.rstrip("/") and settings.llm_api_key
            and not payload.clear_llm_api_key
            and not (payload.llm_api_key and payload.llm_api_key.get_secret_value().strip())):
        raise ValidationError("更换 API 地址时请重新输入 API Key，或勾选清除")
    data = payload.model_dump(exclude=set(SECRETS) | {f"clear_{key}" for key in SECRETS})
    for key in SECRETS:
        value = getattr(payload, key)
        raw = value.get_secret_value().strip() if value else ""
        if raw:
            data[key] = raw
        if getattr(payload, f"clear_{key}"):
            data[key] = ""
    return data
