"""内容安全（spec/04 §12、spec/08 §6）。

- `filter_words.txt`：政治/色情/人身攻击/引战词根
- 正则：手机号 / 邮箱 / 非白名单 URL（URL 白名单仅 zhihu.com）
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("pc.filter")

_WORDS_FILE = Path(__file__).resolve().parent.parent / "seeds" / "filter_words.txt"

# 手机号（中国大陆）、邮箱、URL
_PHONE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"https?://[^\s，。；、）】\]]+", re.IGNORECASE)
_ZHIHU_HOST_RE = re.compile(r"^https?://([a-z0-9-]+\.)*(zhihu\.com|zhimg\.com)(/|$)", re.IGNORECASE)


@lru_cache
def load_words() -> tuple[str, ...]:
    if not _WORDS_FILE.exists():
        log.warning("敏感词表不存在：%s", _WORDS_FILE)
        return ()
    words: list[str] = []
    for line in _WORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.append(line.lower())
    return tuple(words)


def reload_words() -> int:
    load_words.cache_clear()
    return len(load_words())


def check_text(text: str | None) -> tuple[bool, str]:
    """返回 (是否通过, 原因)。原因 slug：empty/word:<w>/phone/email/url。"""
    if text is None:
        return True, ""
    if not text.strip():
        return False, "empty"

    low = text.lower()
    for w in load_words():
        if w and w in low:
            return False, "bad_word"

    if _PHONE_RE.search(text):
        return False, "phone"
    if _EMAIL_RE.search(text):
        return False, "email"
    for url in _URL_RE.findall(text):
        if not _ZHIHU_HOST_RE.match(url):
            return False, "url"
    return True, ""


def is_clean(text: str | None) -> bool:
    return check_text(text)[0]


def sanitize_url(url: str | None) -> str | None:
    """只放行知乎域名的链接（防止 LLM 编造外链）。"""
    if not url:
        return None
    url = url.strip()
    if _ZHIHU_HOST_RE.match(url):
        return url
    return None


def scrub(obj):
    """递归清洗 LLM 输出中的文本字段；命中即替换为占位。返回 (新对象, 是否命中)。"""
    hit = False

    def _walk(v):
        nonlocal hit
        if isinstance(v, str):
            ok, _ = check_text(v)
            if not ok:
                hit = True
                return ""
            return v
        if isinstance(v, dict):
            return {k: _walk(x) for k, x in v.items()}
        if isinstance(v, list):
            return [_walk(x) for x in v]
        return v

    return _walk(obj), hit


__all__ = ["check_text", "is_clean", "load_words", "reload_words", "sanitize_url", "scrub"]
