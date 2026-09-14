"""LLM 网关（spec/05 §1）。

- Jinja2 模板 → `--- system ---` / `--- user ---` 切分成两条消息
- OpenAI 兼容 `/chat/completions`
- JSON 修复链 5 步
- 重试 1 次（仅网络/5xx/非法 JSON）
- `llm_usage` 落库、`llm_fail_streak` / `degraded` 维护
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from functools import lru_cache
from typing import Any, TypeVar

import httpx
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from pydantic import BaseModel, ValidationError

from ..config import PROMPTS_DIR, settings
from ..constants import LlmTier
from ..errors import LlmError, LlmOutputError
from ..schemas.domain import PersonaFile

log = logging.getLogger("pc.llm")

T = TypeVar("T", bound=BaseModel)

COMMON_SYSTEM_PREFIX = """你是「平行校园」模拟引擎的一部分。只输出 JSON，不要输出任何解释或 Markdown。
使用简体中文，口语自然，像真实大学生。禁止：政治敏感、色情、人身攻击、真实个人隐私、引战；
不得编造知乎链接或不存在的引用；不得让角色声称自己是 AI。"""

# 各模板默认 temperature（05 §2）。模板 front-matter 可覆盖。
TEMPLATE_TEMPERATURE: dict[str, float] = {
    "persona_extract": 0.4,
    "daily_schedule": 0.5,
    "decide": 0.9,
    "dialogue": 0.9,
    "reflect": 0.7,
    "env_new_day": 0.6,
    "env_hot_events": 0.4,
    "env_briefing": 0.7,
    "match_report": 0.7,
}

SYSTEM_SPLIT = "--- system ---"
USER_SPLIT = "--- user ---"


# ─────────────────────────── Jinja 环境 ───────────────────────────


@lru_cache
def _env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(PROMPTS_DIR)),
        undefined=StrictUndefined,
        autoescape=select_autoescape(enabled_extensions=(), default=False),
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=False,
    )
    env.filters["shorten"] = lambda s, n=80: (str(s)[:n] if s else "")
    return env


def render_template(template: str, ctx: dict[str, Any]) -> str:
    """渲染 `prompts/<template>.j2`，自动注入 common_prefix。"""
    name = template if template.endswith(".j2") else f"{template}.j2"
    tmpl = _env().get_template(name)
    data = dict(ctx)
    data.setdefault("common_prefix", COMMON_SYSTEM_PREFIX)
    data.setdefault("persona_schema_doc", PERSONA_SCHEMA_DOC)
    data.setdefault("actions_doc", ACTIONS_DOC)
    if "loc" not in data:
        data["loc"] = ctx.get("locations")
    return tmpl.render(**data)


def split_messages(rendered: str) -> tuple[str, str]:
    """按分隔符切成 (system, user)；缺失时整段作 user。"""
    text = rendered.strip()
    system = ""
    user = text
    if SYSTEM_SPLIT in text:
        _, _, after_sys = text.partition(SYSTEM_SPLIT)
        if USER_SPLIT in after_sys:
            system, _, user = after_sys.partition(USER_SPLIT)
        else:
            system, user = after_sys, after_sys
    elif USER_SPLIT in text:
        system, _, user = text.partition(USER_SPLIT)
    system = system.strip()
    if system and COMMON_SYSTEM_PREFIX not in system:
        system = COMMON_SYSTEM_PREFIX + "\n" + system
    return system.strip(), user.strip()


# ─────────────────────────── JSON 修复链 ───────────────────────────

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")


def _strip_fence(text: str) -> str:
    m = _FENCE_RE.search(text)
    if m:
        return m.group(1).strip()
    return text


def _slice_object(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _repair(text: str) -> str:
    out = _TRAILING_COMMA_RE.sub(r"\1", text)
    out = re.sub(r"'([^'\\]*)'(\s*:)", r'"\1"\2', out)     # 单引号 key
    out = re.sub(r":\s*'([^'\\]*)'", r': "\1"', out)        # 单引号 value
    out = re.sub(r"\bTrue\b", "true", out)
    out = re.sub(r"\bFalse\b", "false", out)
    out = re.sub(r"\bNone\b", "null", out)
    return out


def _close_unbalanced(text: str) -> str:
    """截断 JSON 兜底：补齐未闭合的字符串/对象/数组。

    只在原文里 `{`/`[` 明显多于 `}`/`]` 时才动手，避免破坏正常文本。
    """
    in_str = False
    esc = False
    stack: list[str] = []
    for ch in text:
        if esc:
            esc = False
            continue
        if ch == "\\":
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]" and stack:
            stack.pop()
    if not stack and not in_str:
        return text
    out = text
    if in_str:
        out += '"'
    # 丢掉悬空的残缺键（"key": 或 "key"）
    out = re.sub(r',\s*"[^"]*"\s*:\s*$', "", out)
    out = re.sub(r',\s*"[^"]*"\s*$', "", out)
    out = re.sub(r'[{,]\s*$', "", out)
    for ch in reversed(stack):
        out += "}" if ch == "{" else "]"
    return out


def parse_json_lenient(raw: str) -> dict[str, Any]:
    """修复链步骤 1–3：返回 dict；全部失败抛 ValueError。"""
    if not raw or not raw.strip():
        raise ValueError("empty LLM output")
    text = raw.strip()
    # 1. 直接解析
    for candidate in (text, _strip_fence(text), _slice_object(_strip_fence(text))):
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
        except (json.JSONDecodeError, TypeError):
            continue
    # 2. 截断修复（补齐未闭合括号）后再试
    sliced = _slice_object(_strip_fence(text))
    for candidate in (sliced, _repair(sliced)):
        try:
            data = json.loads(_close_unbalanced(candidate))
            if isinstance(data, dict):
                return data
            if isinstance(data, list):
                return {"items": data}
        except (json.JSONDecodeError, TypeError):
            continue
    # 3. 常见修补
    patched = _repair(sliced)
    try:
        data = json.loads(patched)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"JSON 修复失败: {exc}\n原文: {text[:300]}") from exc
    raise ValueError(f"JSON 修复失败（非对象）: {text[:300]}")


def _fill_defaults(schema: type[BaseModel], data: dict[str, Any]) -> dict[str, Any]:
    """修复链步骤 4：用 schema 默认值填补缺失字段后重试。"""
    out = dict(data)
    for name, field in schema.model_fields.items():
        if name in out:
            continue
        if field.default is not None and field.default is not ...:
            out[name] = field.default
        elif field.default_factory is not None:  # type: ignore[comparison-overlap]
            try:
                out[name] = field.default_factory()  # type: ignore[misc]
            except Exception:
                pass
    return out


def coerce(schema: type[T], raw: str) -> T:
    """完整修复链：dict → 校验 → 逐字段默认填补 → 再校验。"""
    try:
        data = parse_json_lenient(raw)
    except ValueError as exc:
        raise LlmOutputError(str(exc), raw) from exc
    try:
        return schema.model_validate(data)
    except ValidationError as first_err:
        filled = _fill_defaults(schema, data)
        try:
            return schema.model_validate(filled)
        except ValidationError as exc:
            raise LlmOutputError(f"schema 校验失败: {exc.errors()[:3]}", raw) from exc


# ─────────────────────────── 离线兜底（无 API key 时）───────────────────────────


class _OfflineMode(Exception):
    pass


# ─────────────────────────── 网关 ───────────────────────────


class LLM:
    """单例网关。`json()` 返回 schema 实例；`text()` 返回纯文本。"""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url).rstrip("/")
        self.api_key = api_key if api_key is not None else settings.llm_api_key
        self._client = client
        self._owns_client = client is None
        self._json_mode_ok = settings.llm_supports_json_mode
        # 由 world 注入的统计回调
        self.usage_sink = None  # type: ignore[assignment]

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=settings.llm_timeout + 10)
        return self._client

    def _model(self, tier: LlmTier) -> str:
        return settings.llm_model_strong if tier == "strong" else settings.llm_model_cheap

    @property
    def offline(self) -> bool:
        """不可用时视为离线：上层（ticker / 决策 / 对话 / 报告）会自动退回日程与规则。"""
        return (not self.api_key) or (not settings.llm_enabled)

    @property
    def offline_reason(self) -> str:
        if not settings.llm_enabled:
            return "LLM 开关已关闭（管理后台「API 配置」可开启）"
        if not self.api_key:
            return "未配置 LLM_API_KEY"
        return ""

    async def _chat(
        self,
        *,
        tier: LlmTier,
        template: str,
        messages: list[dict[str, str]],
        temperature: float,
        max_tokens: int,
        json_mode: bool,
        timeout: float | None,
    ) -> tuple[str, dict[str, Any]]:
        if self.offline:
            raise LlmError(f"{self.offline_reason or 'LLM 不可用'}，已退回规则模式")
        model = self._model(tier)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode and self._json_mode_ok:
            payload["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        eff_timeout = timeout or settings.llm_timeout

        started = time.monotonic()
        last_exc: Exception | None = None
        for attempt in range(2):  # 最多 1 次重试
            try:
                resp = await self._http().post(url, json=payload, headers=headers, timeout=eff_timeout)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == 0:
                    log.warning("llm 网络错误，重试一次: %s", exc)
                    continue
                await self._record(tier, template, model, "", 0, started, ok=False, error=str(exc))
                raise LlmError(f"LLM 网络错误: {exc}") from exc

            if resp.status_code >= 500:
                last_exc = LlmError(f"LLM {resp.status_code}")
                if attempt == 0:
                    log.warning("llm 5xx，重试一次: %s", resp.status_code)
                    continue
                await self._record(tier, template, model, "", 0, started, ok=False,
                                   error=f"http_{resp.status_code}")
                raise LlmError(f"LLM 服务不可用（{resp.status_code}）")

            if resp.status_code == 400 and "response_format" in resp.text and self._json_mode_ok:
                # 供应商不支持 json 模式：去掉后重试一次（05 §1.1）
                log.info("供应商不支持 response_format，降级为提示词约束")
                self._json_mode_ok = False
                payload.pop("response_format", None)
                try:
                    resp = await self._http().post(url, json=payload, headers=headers, timeout=eff_timeout)
                except Exception as exc:
                    await self._record(tier, template, model, "", 0, started, ok=False, error=str(exc))
                    raise LlmError(f"LLM 请求失败: {exc}") from exc

            if resp.status_code >= 400:
                body = resp.text[:300]
                await self._record(tier, template, model, "", 0, started, ok=False,
                                   error=f"http_{resp.status_code}")
                raise LlmError(f"LLM 请求被拒绝（{resp.status_code}）: {body}")

            try:
                data = resp.json()
            except Exception as exc:
                await self._record(tier, template, model, "", 0, started, ok=False, error="bad_response")
                raise LlmError(f"LLM 响应不是 JSON: {exc}") from exc

            if isinstance(data, dict) and data.get("error"):
                # 可能是 prompts 太长；不重试，交给调用方兜底
                await self._record(tier, template, model, "", 0, started, ok=False, error="api_error")
                raise LlmError(f"LLM 返回错误: {str(data.get('error'))[:200]}")

            content = _extract_content(data)
            usage = data.get("usage") or {}
            await self._record(
                tier, template, model, content,
                int(usage.get("completion_tokens") or 0), started, ok=True, error=None,
                prompt_tokens=int(usage.get("prompt_tokens") or 0),
            )
            return content, usage

        raise LlmError(f"LLM 请求失败: {last_exc}")

    async def _record(
        self,
        tier: LlmTier,
        template: str,
        model: str,
        content: str,
        completion_tokens: int,
        started: float,
        *,
        ok: bool,
        error: str | None,
        prompt_tokens: int = 0,
    ) -> None:
        latency = int((time.monotonic() - started) * 1000)
        if not prompt_tokens and content:
            prompt_tokens = max(0, len(content) // 4)
        if self.usage_sink is not None:
            try:
                await self.usage_sink(
                    tier=tier, template=template, model=model,
                    prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                    latency_ms=latency, ok=ok, error=error,
                )
            except Exception:
                log.exception("usage_sink 失败")

    async def json(
        self,
        tier: LlmTier,
        template: str,
        ctx: dict[str, Any],
        schema: type[T],
        *,
        timeout: float | None = None,
        max_tokens: int = 1200,
    ) -> T:
        rendered = render_template(template, ctx)
        system, user = split_messages(rendered)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        temperature = TEMPLATE_TEMPERATURE.get(template, 0.7)

        last_err: Exception | None = None
        for attempt in range(2):
            content, _ = await self._chat(
                tier=tier, template=template, messages=messages,
                temperature=temperature, max_tokens=max_tokens,
                json_mode=True, timeout=timeout,
            )
            try:
                return coerce(schema, content)
            except LlmOutputError as exc:
                last_err = exc
                if attempt == 0:
                    # 非法 JSON：追加纠正指令再试一次（05 §1）
                    log.warning("LLM 输出非法 JSON，附带纠正指令重试一次")
                    messages = messages + [
                        {"role": "assistant", "content": content[:500]},
                        {"role": "user", "content": "上面的输出不是合法 JSON。请只输出符合要求的 JSON 对象，不要任何解释、不要 Markdown 代码块。"},
                    ]
                    continue
        raise LlmOutputError(str(last_err)) from last_err

    async def text(
        self,
        tier: LlmTier,
        template: str,
        ctx: dict[str, Any],
        *,
        max_tokens: int = 400,
        timeout: float | None = None,
    ) -> str:
        rendered = render_template(template, ctx)
        system, user = split_messages(rendered)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": user})
        content, _ = await self._chat(
            tier=tier, template=template, messages=messages,
            temperature=TEMPLATE_TEMPERATURE.get(template, 0.7),
            max_tokens=max_tokens, json_mode=False, timeout=timeout,
        )
        return content.strip()


def _extract_content(data: dict[str, Any]) -> str:
    """兼容 choices[0].message.content 与个别供应商的 output_text。"""
    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            msg = first.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if isinstance(content, str):
                    return content
                if isinstance(content, list):  # 多段 content
                    return "".join(
                        seg.get("text", "") for seg in content if isinstance(seg, dict)
                    )
            if isinstance(first.get("text"), str):
                return first["text"]
    for key in ("output_text", "content", "text"):
        if isinstance(data.get(key), str):
            return data[key]
    return ""


# ─────────────────────────── 文档片段（注入 prompt）───────────────────────────


PERSONA_SCHEMA_DOC = """
{
  "display_name": "string 1..24",
  "archetype": "string ≤20（一句话人设）",
  "mbti_like": {"E_I": -1..1, "S_N": -1..1, "T_F": -1..1, "J_P": -1..1},
  "big_five": {"O": 0..1, "C": 0..1, "E": 0..1, "A": 0..1, "N": 0..1},
  "interests": [{"topic": "≤12字", "weight": 0..1, "evidence": ["C3","F12"]}],   // 3..8 条，按 weight 降序
  "stances": [{"text": "≤40字", "evidence": ["C7"]}],                            // 0..5 条
  "speaking_style": {"tone": "≤30字", "emoji": true, "length": "短|中|长", "catchphrases": ["≤3条"]},
  "values": ["≤6字", "..."],                                                     // 1..4 条
  "social": {"initiative": 0..1, "group_pref": "独处|小圈子|广交", "avoid_topics": ["≤5条"]},
  "campus_identity": {"major": "≤20字", "grade": "大一|大二|大三|大四|研一|研二|研三", "club": "可空"},
  "appearance": "≤80字，只写风格气质",
  "summary": "150..350字，第三人称"
}
""".strip()


ACTIONS_DOC = """
可用动作（填 action.type，并给对应字段）：
- move       : {"type":"move","location_id":"<地点id>"}
- talk       : {"type":"talk","target_id":"<在场角色id>","text":"开场白 ≤60字"}
- post       : {"type":"post","board":"wall|tree_hole","text":"≤500字"}
- comment    : {"type":"comment","post_id":"p_...","text":"≤200字"}
- like       : {"type":"like","post_id":"p_..."}
- dm         : {"type":"dm","target_id":"<角色id>","text":"≤200字"}
- attend     : {"type":"attend","event_id":"e_..."}
- do         : {"type":"do","text":"当前活动 ≤30字"}
- search_zhihu: {"type":"search_zhihu","query":"≤30字"}
- idle       : {"type":"idle"}

硬约束（违反的动作会被丢弃，你会白decision一次）：
1. talk 必须给 target_id，且只能选【在场的人】里列出的 id（形如 npc_xxx / pl_xxx），
   不要写名字，不要省略 target_id。text 是你的开场白，符合你的说话风格。
2. dm 必须给 target_id，可以是任何角色（不必同地）。
3. move 只能去【可去的地点】里列出的 id。
4. attend 必须给 event_id，只能填【校园里正在发生的事】里的事件。
5. 不确定事实时用 search_zhihu 查知乎，不要凭想象编造观点。
""".strip()


# 全局单例
_gateway: LLM | None = None


def get_llm() -> LLM:
    global _gateway
    if _gateway is None:
        _gateway = LLM()
    return _gateway


def set_llm(llm: LLM | None) -> None:
    global _gateway
    _gateway = llm


def reset_llm() -> None:
    """测试用：丢弃单例，下次 `get_llm()` 重新构造。"""
    global _gateway
    _gateway = None


__all__ = [
    "LLM", "get_llm", "set_llm", "render_template", "split_messages", "coerce",
    "parse_json_lenient", "COMMON_SYSTEM_PREFIX", "PERSONA_SCHEMA_DOC", "ACTIONS_DOC",
    "TEMPLATE_TEMPERATURE",
]
