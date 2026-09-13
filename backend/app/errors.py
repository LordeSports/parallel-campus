"""领域异常与 HTTP 映射（spec/03 §1.1）。"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    status_code: int = 400
    code: str = "validation_error"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {"code": self.code, "message": self.message}
        if self.detail:
            body["detail"] = self.detail
        return {"error": body}


class ValidationError(AppError):
    status_code = 400
    code = "validation_error"


class Unauthorized(AppError):
    status_code = 401
    code = "unauthorized"


class Forbidden(AppError):
    status_code = 403
    code = "forbidden"


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class Conflict(AppError):
    status_code = 409
    code = "conflict"


class RateLimited(AppError):
    status_code = 429
    code = "rate_limited"

    def __init__(self, message: str, retry_after_seconds: int = 60) -> None:
        super().__init__(message, {"retry_after_seconds": retry_after_seconds})
        self.retry_after_seconds = retry_after_seconds


class ZhihuError(AppError):
    """知乎接口失败（06 §2 归一化）。"""

    status_code = 502
    code = "zhihu_error"

    def __init__(self, message: str, status: int | None = None, zhihu_code: int | str | None = None) -> None:
        detail: dict[str, Any] = {}
        if status is not None:
            detail["http_status"] = status
        if zhihu_code is not None:
            detail["zhihu_code"] = zhihu_code
        super().__init__(message, detail)
        self.zhihu_code = zhihu_code


class QuotaExceeded(AppError):
    """本地配额已满（不发请求）。"""

    status_code = 503
    code = "quota_exceeded"

    def __init__(self, api: str) -> None:
        super().__init__(f"今日知乎额度已用完（{api}）", {"api": api})
        self.api = api


class LlmError(AppError):
    status_code = 503
    code = "llm_error"


class LlmOutputError(LlmError):
    """LLM 输出无法解析为 schema —— 调用方使用兜底值。"""

    def __init__(self, message: str = "LLM 输出无法解析", raw: str = "") -> None:
        super().__init__(message, {"raw_preview": raw[:200]} if raw else None)


class TokenExchangeError(Exception):
    """OAuth 换 token 失败（06 §3）。"""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


__all__ = [
    "AppError", "ValidationError", "Unauthorized", "Forbidden", "NotFound",
    "Conflict", "RateLimited", "ZhihuError", "QuotaExceeded", "LlmError",
    "LlmOutputError", "TokenExchangeError",
]
