"""会话签名、Fernet token 加密、脱敏日志（spec/03 §1.2、spec/06 §8）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import struct
import time
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


def _state_payload(value: str) -> dict[str, Any] | None:
    """解出签名串的 payload；签名不符、格式非法或**超过 10 分钟**都返回 None。"""
    try:
        data = _serializer(OAUTH_STATE_SALT).loads(value, max_age=OAUTH_STATE_MAX_AGE)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _state_age_seconds(value: str) -> float | None:
    """从签名串中段的明文时间戳算出已过去秒数（仅用于诊断日志）。"""
    parts = value.split(".")
    if len(parts) != 3:
        return None
    try:
        raw = base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4))
        issued = struct.unpack(">I", raw)[0]
    except Exception:
        return None
    return max(0.0, time.time() - issued)


def verify_oauth_state(cookie_value: str | None, query_state: str | None) -> bool:
    """校验回调 state（CSRF 双提交）。

    **真实流程**：`api/auth.py` 把 `sign_oauth_state()` 的返回值**同一个签名串**
    既写进 cookie，又作为 `state` 发给知乎；知乎原样回显。所以正常情况下
    `query_state == cookie_value`。

    ⚠️ 历史 bug：这里曾只把 cookie 内层的 nonce 与 query 比对，而 query 是**完整签名串**，
    两者永远不可能相等 → 线上固定报 `state_mismatch`（cookie 与 query 都在、且刚刚签发）。
    因此下面三种形态都接受，且每一种都要求 cookie 签名有效且未过期：
    1. 完整签名串（真实流程）
    2. 裸 nonce（旧调用方 / 单测）
    3. 另一份合法签名串，且内层 nonce 相同
    """
    if not cookie_value or not query_state:
        return False
    data = _state_payload(cookie_value)
    if data is None:
        return False
    nonce = str(data.get("s") or "")
    if not nonce:
        return False
    if hmac.compare_digest(cookie_value, query_state):
        return True
    if hmac.compare_digest(nonce, query_state):
        return True
    query = _state_payload(query_state)
    query_nonce = str(query.get("s") or "") if query else ""
    return bool(query_nonce) and hmac.compare_digest(nonce, query_nonce)


def diagnose_oauth_state(cookie_value: str | None, query_state: str | None) -> dict[str, Any]:
    """把 state 校验拆成可判读的结论，供 dev 日志使用。

    原先日志只会说「不匹配或超过 10 分钟」，无法区分「cookie 没带回来」「签名验不过」
    「两边值不同」——三者修法完全不同。
    """
    cookie_ok = bool(cookie_value) and _state_payload(cookie_value) is not None
    same_raw = bool(cookie_value) and bool(query_state) and cookie_value == query_state
    age = _state_age_seconds(cookie_value) if cookie_value else None

    reason = "ok"
    if not cookie_value:
        reason = "no_cookie"
    elif not query_state:
        reason = "no_query_state"
    elif not cookie_ok:
        reason = "cookie_signature_invalid_or_expired"
    elif not verify_oauth_state(cookie_value, query_state):
        reason = "cookie_query_mismatch"

    return {
        "reason": reason,
        "ok": reason == "ok",
        "cookie_present": bool(cookie_value),
        "query_present": bool(query_state),
        "cookie_signature_ok": cookie_ok,
        "cookie_age_seconds": None if age is None else round(age, 1),
        "state_max_age_seconds": OAUTH_STATE_MAX_AGE,
        "same_raw": same_raw,
    }


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
    "diagnose_oauth_state",
    "sign_admin_session", "verify_admin_session",
    "encrypt_token", "decrypt_token", "redact", "sha1_short", "check_admin_token",
    "dumps_json",
]
