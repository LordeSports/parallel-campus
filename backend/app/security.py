"""会话签名、Fernet token 加密、脱敏日志（spec/03 §1.2、spec/06 §8）。"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import settings

log = logging.getLogger("pc.security")

SESSION_COOKIE = "pc_session"
OAUTH_STATE_COOKIE = "pc_oauth_state"
SESSION_MAX_AGE = 7 * 24 * 3600          # 7d
OAUTH_STATE_MAX_AGE = 10 * 60            # 10min
SESSION_SALT = "pc-session-v1"
ADMIN_SESSION_SALT = "pc-admin-v1"
ADMIN_COOKIE = "pc_admin"
ADMIN_SESSION_MAX_AGE = 8 * 3600
OAUTH_STATE_SALT = "pc-oauth-state-v1"


def _serializer(salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key=settings.session_secret, salt=salt)


# ─────────────────────────── 会话 ───────────────────────────


def sign_session(uid: str, iat: int | None = None) -> str:
    import time

    payload = {"uid": uid, "iat": iat if iat is not None else int(time.time())}
    return _serializer(SESSION_SALT).dumps(payload)


def verify_session(token: str) -> str | None:
    """返回 uid；无效/过期返回 None。"""
    try:
        data: dict[str, Any] = _serializer(SESSION_SALT).loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired, Exception):
        return None
    uid = data.get("uid")
    return uid if isinstance(uid, str) and uid else None


def sign_admin_session(username: str) -> str:
    return _serializer(ADMIN_SESSION_SALT).dumps({"admin": username, "version": _admin_version()})


def _admin_version() -> str:
    return hmac.new(settings.session_secret.encode(),
                    (settings.admin_username + "\0" + settings.admin_password).encode(),
                    hashlib.sha256).hexdigest()


def verify_admin_session(token: str | None) -> str | None:
    if not token or not settings.admin_password:
        return None
    try:
        data = _serializer(ADMIN_SESSION_SALT).loads(token, max_age=ADMIN_SESSION_MAX_AGE)
    except Exception:
        return None
    if not isinstance(data, dict) or data.get("admin") != settings.admin_username:
        return None
    version = data.get("version")
    if not isinstance(version, str) or not hmac.compare_digest(version, _admin_version()):
        return None
    return settings.admin_username


def sign_oauth_state() -> str:
    state = secrets.token_urlsafe(32)
    return _serializer(OAUTH_STATE_SALT).dumps({"s": state})


def verify_oauth_state(cookie_value: str | None, query_state: str | None) -> bool:
    if not cookie_value or not query_state:
        return False
    try:
        data: dict[str, Any] = _serializer(OAUTH_STATE_SALT).loads(
            cookie_value, max_age=OAUTH_STATE_MAX_AGE
        )
    except Exception:
        return False
    return hmac.compare_digest(str(data.get("s", "")), query_state)


# ─────────────────────────── Token 加密 ───────────────────────────


def _fernet() -> Fernet | None:
    key = settings.token_enc_key.strip()
    if not key:
        return None
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        log.error("TOKEN_ENC_KEY 不是合法 Fernet key，token 将不加密存储")
        return None


def encrypt_token(raw: str) -> bytes:
    f = _fernet()
    if f is None:
        # 无 key：以明文存（仅 DEV）；生产启动校验已保证 key 存在
        return b"plain:" + raw.encode()
    return f.encrypt(raw.encode())


def decrypt_token(blob: bytes | None) -> str | None:
    if not blob:
        return None
    if blob.startswith(b"plain:"):
        return blob[len(b"plain:") :].decode(errors="replace")
    f = _fernet()
    if f is None:
        return None
    try:
        return f.decrypt(blob).decode(errors="replace")
    except InvalidToken:
        return None


# ─────────────────────────── 脱敏 ───────────────────────────


def redact(value: str | None, keep: int = 6) -> str:
    """日志脱敏：只留 sha1 前 N 位（06 §8）。"""
    if not value:
        return "-"
    return hashlib.sha1(value.encode()).hexdigest()[:keep]


def sha1_short(value: str | None, keep: int = 8) -> str:
    if not value:
        return ""
    return hashlib.sha1(value.encode()).hexdigest()[:keep]


def check_admin_token(header_value: str | None) -> bool:
    if not header_value:
        return False
    return hmac.compare_digest(header_value, settings.admin_token)


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


__all__ = [
    "SESSION_COOKIE", "OAUTH_STATE_COOKIE", "SESSION_MAX_AGE", "OAUTH_STATE_MAX_AGE",
    "sign_session", "verify_session", "sign_oauth_state", "verify_oauth_state",
    "sign_admin_session", "verify_admin_session",
    "encrypt_token", "decrypt_token", "redact", "sha1_short", "check_admin_token",
    "dumps_json",
]
