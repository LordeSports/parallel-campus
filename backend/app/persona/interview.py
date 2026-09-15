"""对话式画像访谈（用户要求的四步循环）。

    1. 读取用户知乎公开信息        → `_pull_evidence`（start 时拉一次并缓存）
    2. 通过用户信息形成初版问题    → LLM 第一轮（基于证据）
    3. LLM 通过回答完善画像        → 每轮更新 draft
    4. 通过画像 + 知乎搜索形成新问题 → `_probes`（把画像兴趣喂给站内搜索）→ 回到 3
    …… 直到 LLM 认为 `done`（或到轮数上限）。

会话状态存 `persona_interview` 表（新表，老库无需迁移）。
finish 时 draft 经 `post_process` 清洗后落成正式 Persona。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from ..errors import AppError, NotFound
from ..llm.gateway import get_llm
from ..models import PersonaInterview, User, new_id, now_utc
from ..schemas.domain import InterviewTurn, PersonaFile
from ..security import decrypt_token
from ..zhihu.content import _client, zhihu_search
from ..zhihu.user_data import build_evidence, pull_user_data

log = logging.getLogger("pc.persona.interview")

MAX_ROUNDS = 8
PROBE_TOPICS = 2
LLM_TIMEOUT = 45.0
LLM_MAX_TOKENS = 1800


async def _pull_evidence(session: AsyncSession, user: User) -> tuple[str, dict[str, Any]]:
    """第 1 步：读知乎公开信息。没授权/失败 → 空证据（纯访谈也能进行）。"""
    token = decrypt_token(user.zhihu_token_enc)
    if not token:
        return "", {"contents": 0, "followees": 0, "favlists": 0, "saved_items": 0, "failed": ["no_token"]}
    try:
        data, failed = await pull_user_data(_client(session), token)
    except Exception as exc:
        log.info("访谈证据拉取失败（转纯访谈）: %s", exc)
        return "", {"contents": 0, "followees": 0, "favlists": 0, "saved_items": 0, "failed": ["pull_failed"]}
    pack = build_evidence(data, failed)
    return pack.text, pack.stats


async def _probes(draft: PersonaFile | None) -> list[str]:
    """第 4 步：用画像的兴趣喂知乎站内搜索，给下一问提供真实素材。"""
    if draft is None:
        return []
    out: list[str] = []
    for topic in [i.topic for i in draft.interests[:PROBE_TOPICS]]:
        try:
            items = await zhihu_search(topic, count=2)
        except Exception as exc:
            log.debug("访谈探针搜索失败 %s: %s", topic, exc)
            continue
        for it in items:
            title = str(it.get("title") or "")[:30]
            brief = str(it.get("content_text") or "")[:60].replace("\n", " ")
            out.append(f"{topic}：《{title}》{brief}")
    return out[: PROBE_TOPICS * 2]


def _history(row: PersonaInterview) -> list[dict[str, str]]:
    """messages → 模板用的 speaker/text 列表（截断到最近 10 条，控 token）。"""
    out: list[dict[str, str]] = []
    for m in row.messages[-10:]:
        speaker = "你" if m.get("role") == "user" else "访谈者"
        text = str(m.get("text") or "")[:200]
        out.append({"speaker": speaker, "text": text})
    return out


def _draft_note(draft: PersonaFile | None) -> str:
    return draft.brief()[:200] if draft else ""


async def _run_turn(
    row: PersonaInterview, user: User, *, round_no: int
) -> InterviewTurn:
    llm = get_llm()
    if llm.offline:
        raise AppError("对话式画像需要可用的大模型；请先在后台配置 LLM 或改用手动编辑")

    draft = None
    if row.draft:
        try:
            draft = PersonaFile.model_validate(row.draft)
        except Exception:
            draft = None

    probes = await _probes(draft)
    ctx = {
        "display_name": user.display_name or "",
        "evidence": row.evidence_text or "（没有可用的公开内容，请完全依靠问答）",
        "history": _history(row),
        "round_no": round_no,
        "max_rounds": MAX_ROUNDS,
        "probes": probes,
        "draft_note": _draft_note(draft),
    }
    turn = await llm.json("strong", "persona_interview", ctx, InterviewTurn,
                         timeout=LLM_TIMEOUT, max_tokens=LLM_MAX_TOKENS)

    # 兜底：LLM 拖着不结束 → 到上限强制收尾
    if round_no >= MAX_ROUNDS and not turn.done:
        turn.done = True
        turn.question = ""
        turn.reply = (turn.reply or "") + "（访谈轮数已到上限，先用现有信息生成画像。）"
    return turn


def _view(row: PersonaInterview, turn: InterviewTurn) -> dict[str, Any]:
    return {
        "session_id": row.id,
        "round_no": row.round_no,
        "done": turn.done,
        "progress": turn.progress,
        "messages": row.messages,
        "question": turn.question,
        "reply": turn.reply,
        "missing": turn.missing,
        "draft": turn.draft.model_dump() if turn.draft else row.draft,
        "max_rounds": MAX_ROUNDS,
    }


async def start(session: AsyncSession, user: User) -> dict[str, Any]:
    """第 1+2 步：拉证据 → 开场第一问。已有进行中的访谈则续上。"""
    row = (
        await session.exec(
            select(PersonaInterview).where(
                col(PersonaInterview.user_id) == user.id,
                col(PersonaInterview.status) == "active",
            )
        )
    ).first()
    if row is not None:
        # 续上：把最后一问再发一遍
        last_q = next(
            (m["text"] for m in reversed(row.messages) if m.get("role") == "assistant"), ""
        )
        turn = InterviewTurn(question=last_q, progress=30, done=False)
        return _view(row, turn)

    evidence_text, stats = await _pull_evidence(session, user)
    row = PersonaInterview(
        id=new_id("pi_"), user_id=user.id, evidence_text=evidence_text,
        evidence_stats=stats, messages=[], round_no=0,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    turn = await _run_turn(row, user, round_no=0)
    row.messages = [{"role": "assistant", "text": turn.reply, "question": turn.question}]
    row.round_no = 0
    if turn.draft:
        row.draft = turn.draft.model_dump()
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _view(row, turn)


async def answer(
    session: AsyncSession, user: User, session_id: str, text: str
) -> dict[str, Any]:
    """第 3+4 步：记录回答 → LLM 完善画像并给下一问。"""
    row = (
        await session.exec(
            select(PersonaInterview).where(
                col(PersonaInterview.id) == session_id,
                col(PersonaInterview.user_id) == user.id,
            )
        )
    ).first()
    if row is None or row.status != "active":
        raise NotFound("访谈会话不存在或已结束")

    clean = text.strip()[:400]
    if not clean:
        raise AppError("回答不能为空")

    row.messages = [*row.messages, {"role": "user", "text": clean}]
    row.round_no = row.round_no + 1

    turn = await _run_turn(row, user, round_no=row.round_no)
    row.messages = [
        *row.messages,
        {"role": "assistant", "text": turn.reply, "question": turn.question},
    ]
    if turn.draft:
        row.draft = turn.draft.model_dump()
    row.updated_at = now_utc()
    if turn.done:
        row.status = "done"
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _view(row, turn)


async def load_draft(session: AsyncSession, user: User, session_id: str) -> PersonaFile:
    """finish 用：取出最新 draft（没有就给中性画像，交给用户手改）。"""
    from .pipeline import _neutral_persona

    row = (
        await session.exec(
            select(PersonaInterview).where(
                col(PersonaInterview.id) == session_id,
                col(PersonaInterview.user_id) == user.id,
            )
        )
    ).first()
    if row is None:
        raise NotFound("访谈会话不存在")
    if row.draft:
        try:
            return PersonaFile.model_validate(row.draft)
        except Exception as exc:
            log.warning("访谈草稿非法，退回中性画像: %s", exc)
    return _neutral_persona(user.display_name)


__all__ = ["MAX_ROUNDS", "start", "answer", "load_draft"]
