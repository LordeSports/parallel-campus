"""人格提取管线（spec/06 §4、spec/05 §3 P1）。

拉取 → 证据包 → P1 → 后处理（丢弃非法 evidence、补齐 interests、敏感词过滤）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from ..config import settings
from ..errors import ZhihuError
from ..llm.gateway import get_llm
from ..models import User
from ..schemas.domain import Interest, PersonaFile
from ..seeds import INTEREST_VOCAB, normalize_topic
from ..sim.filter import check_text
from ..zhihu.user_data import EvidencePack, build_evidence, pull_user_data

log = logging.getLogger("pc.persona")

MIN_INTERESTS = 3
MAX_INTERESTS = 8


@dataclass
class GenerateResult:
    file: PersonaFile
    thin: bool
    source_stats: dict[str, Any]


async def generate_persona(session: AsyncSession, user: User, *, force: bool = False) -> GenerateResult:
    """完整管线。失败抛 ZhihuError / LlmError，由 API 层映射。"""
    from ..security import decrypt_token
    from ..zhihu.content import _client

    token = decrypt_token(user.zhihu_token_enc)

    evidence: EvidencePack
    client = _client(session)
    data: dict[str, list[dict[str, Any]]] = {}
    failed: list[str] = []

    if token:
        data, failed = await pull_user_data(client, token)

    stats = {
        "contents": len(data.get("contents", [])),
        "followees": len(data.get("followees", [])),
        "favlists": len(data.get("favlists", [])),
        "saved_items": len(data.get("collections", [])) + len(data.get("favlist_contents", [])),
        "failed": failed,
    }

    # 全部失败 → thin=true 且 502
    if token and failed and not any(
        [data.get("contents"), data.get("followees"), data.get("favlists"), data.get("collections")]
    ):
        raise ZhihuError("无法读取你的知乎公开数据，请重试或稍后再试")

    evidence = build_evidence(data, failed)
    stats.update({
        "contents": evidence.stats["contents"],
        "followees": evidence.stats["followees"],
        "favlists": evidence.stats["favlists"],
        "saved_items": evidence.stats["saved_items"],
    })

    llm = get_llm()
    if llm.offline or evidence.thin:
        file = _neutral_persona(user.display_name)
        return GenerateResult(file=file, thin=True, source_stats=stats)

    ctx = {
        "evidence": evidence.text or "（没有可用的公开内容）",
        "stats": stats,
        "display_name_hint": user.display_name or "",
    }
    try:
        raw = await llm.json("strong", "persona_extract", ctx, PersonaFile,
                             timeout=60.0, max_tokens=2000)
    except Exception as exc:
        log.warning("P1 生成失败 %s: %s", user.display_name, exc)
        file = _neutral_persona(user.display_name)
        return GenerateResult(file=file, thin=True, source_stats=stats)

    file = post_process(raw, evidence, user.display_name)
    return GenerateResult(file=file, thin=evidence.thin, source_stats=stats)


# ─────────────────────────── 后处理 ───────────────────────────


def post_process(raw: PersonaFile, evidence: EvidencePack, display_name: str) -> PersonaFile:
    """丢弃非法 evidence ID；interests 补齐；topic 归一；敏感词过滤。"""
    valid_ids = _extract_ids(evidence.text)

    interests: list[Interest] = []
    for i in raw.interests:
        evidence_ids = [e for e in (i.evidence or []) if e in valid_ids]
        topic = normalize_topic(i.topic)
        ok, _ = check_text(topic)
        if not ok:
            continue
        interests.append(Interest(topic=topic, weight=max(0.0, min(1.0, i.weight)),
                                  evidence=evidence_ids))
    interests = interests[:MAX_INTERESTS]

    # interests 少于 3 → 用 followees Headline 高频词补齐 weight 0.3
    if len(interests) < MIN_INTERESTS:
        existing = {i.topic for i in interests}
        for topic in _headline_topics(evidence.text):
            if len(interests) >= MIN_INTERESTS:
                break
            if topic in existing:
                continue
            interests.append(Interest(topic=topic, weight=0.3, evidence=[]))
            existing.add(topic)
    while len(interests) < MIN_INTERESTS:
        for topic in INTEREST_VOCAB:
            if len(interests) >= MIN_INTERESTS:
                break
            if any(i.topic == topic for i in interests):
                continue
            interests.append(Interest(topic=topic, weight=0.3, evidence=[]))

    raw.interests = sorted(interests, key=lambda i: i.weight, reverse=True)

    # stances 的 evidence 同样校验
    for s in raw.stances:
        s.evidence = [e for e in (s.evidence or []) if e in valid_ids]
        ok, _ = check_text(s.text)
        if not ok:
            s.text = ""

    raw.stances = [s for s in raw.stances if s.text.strip()][:5]

    # 文本清洗
    for attr in ("archetype", "appearance", "summary"):
        value = getattr(raw, attr)
        ok, _ = check_text(value)
        if not ok:
            setattr(raw, attr, "")

    if not raw.archetype:
        raw.archetype = "还在认识自己的同学"
    if len(raw.summary) < 20:
        raw.summary = (
            f"{display_name or '这位同学'}的公开内容还不多，画像只能给一个中性起点。"
            "你可以在编辑页直接改成更贴近自己的样子。"
        )
    raw.summary = raw.summary[:400]

    raw.values = [v[:6] for v in raw.values if check_text(v)[0]][:4]
    if not raw.values:
        raw.values = ["真诚"]

    if not raw.display_name or not raw.display_name.strip():
        raw.display_name = display_name or "未命名"
    raw.display_name = raw.display_name[:24]

    if not raw.appearance:
        raw.appearance = "穿得简单，背包里总塞着一本书"

    # 说话风格兜底
    if not raw.speaking_style.tone:
        raw.speaking_style.tone = "自然"
    raw.speaking_style.catchphrases = [
        c[:20] for c in raw.speaking_style.catchphrases if check_text(c)[0]
    ][:3]

    if not raw.social.avoid_topics:
        raw.social.avoid_topics = ["个人隐私"]

    return raw


def _extract_ids(evidence_text: str) -> set[str]:
    import re

    return set(re.findall(r"\b([CFLS]\d{1,3})\b", evidence_text or ""))


def _headline_topics(evidence_text: str) -> list[str]:
    """从 followees Headline 里提取高频兴趣词（08 §2 词表匹配）。"""
    counts: dict[str, int] = {}
    for line in (evidence_text or "").splitlines():
        if not line.startswith("F"):
            continue
        _, _, rest = line.partition(" ")
        for word in INTEREST_VOCAB:
            if word in rest:
                counts[word] = counts.get(word, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda x: x[1], reverse=True)]


def _neutral_persona(name: str) -> PersonaFile:
    return PersonaFile(
        display_name=(name or "未命名")[:24],
        archetype="还在认识自己的同学",
        mbti_like={"E_I": 0.0, "S_N": 0.0, "T_F": 0.0, "J_P": 0.0},
        big_five={"O": 0.5, "C": 0.5, "E": 0.5, "A": 0.5, "N": 0.5},
        interests=[
            Interest(topic="校园生活", weight=0.6),
            Interest(topic="知识分享", weight=0.5),
            Interest(topic="旅行", weight=0.4),
        ],
        stances=[],
        speaking_style={"tone": "自然", "emoji": False, "length": "中", "catchphrases": []},
        values=["真诚"],
        social={"initiative": 0.5, "group_pref": "小圈子", "avoid_topics": ["个人隐私"]},
        campus_identity={"major": "未定", "grade": "大二", "club": None},
        appearance="穿得简单，走路不急",
        summary=(
            "这位同学的公开内容还不多，画像只能给出一个中性的起点。"
            "你可以直接修改每一项，或者稍后再试一次生成。中性画像不影响分身参与校园生活，"
            "只是它在开始时会更倾向于按日程行动、少主动搭话。"
        ),
    )


__all__ = ["generate_persona", "post_process", "GenerateResult", "_neutral_persona"]
