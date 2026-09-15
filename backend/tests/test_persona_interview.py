"""对话式画像访谈：四步循环 + 收尾落库（用脚本化 LLM，不联网）。"""
from __future__ import annotations

import pytest

from app.models import User, new_id
from app.persona import interview


def _draft(name: str = "小测") -> dict:
    return {
        "display_name": name,
        "archetype": "好奇的工科生",
        "mbti_like": {"E_I": 0.2, "S_N": 0.1, "T_F": -0.2, "J_P": 0.3},
        "big_five": {"O": 0.7, "C": 0.6, "E": 0.4, "A": 0.5, "N": 0.4},
        "interests": [
            {"topic": "科技", "weight": 0.8, "evidence": []},
            {"topic": "独立游戏", "weight": 0.6, "evidence": []},
            {"topic": "美食", "weight": 0.5, "evidence": []},
        ],
        "stances": [],
        "speaking_style": {"tone": "随和", "emoji": True, "length": "短", "catchphrases": ["稳了"]},
        "values": ["真诚", "好奇"],
        "social": {"initiative": 0.6, "group_pref": "小圈子", "avoid_topics": ["个人隐私"]},
        "campus_identity": {"major": "计算机", "grade": "大二", "club": "桨板社"},
        "appearance": "连帽衫 + 双肩包",
        "summary": "一个喜欢折腾数码、偶尔打独立游戏的大二学生，熟人面前话很多。",
    }


def _user() -> User:
    return User(id=new_id("u_"), display_name="小测", avatar_key="av_01", auth_kind="dev")


@pytest.mark.asyncio
async def test_interview_start_asks_first_question(session, fake_llm):
    llm = fake_llm({"persona_interview": {
        "reply": "你好呀！", "question": "你平时喜欢做什么？",
        "done": False, "progress": 35, "missing": ["说话风格"],
        "draft": _draft(),
    }})
    user = _user()
    view = await interview.start(session, user)

    assert view["done"] is False
    assert view["question"] == "你平时喜欢做什么？"
    assert view["session_id"]
    assert view["messages"] and view["messages"][0]["role"] == "assistant"
    assert llm.calls and llm.calls[0]["template"] == "persona_interview"


@pytest.mark.asyncio
async def test_interview_answer_updates_draft_and_finishes(session, fake_llm):
    # ScriptedLLM 支持可调用 payload：按调用次序返回第 1、2 轮
    responses = [
        {   # 第 1 轮（start）
            "reply": "你好呀！", "question": "你平时喜欢做什么？",
            "done": False, "progress": 35, "missing": [], "draft": _draft(),
        },
        {   # 第 2 轮（answer）：LLM 认为信息够了
            "reply": "懂了，折腾型选手。", "question": "",
            "done": True, "progress": 92, "missing": [],
            "draft": _draft("小测改"),
        },
    ]
    idx = {"i": -1}

    def scripted(_ctx):  # noqa: ANN001, ANN202
        idx["i"] += 1
        return responses[idx["i"]]

    fake_llm({"persona_interview": scripted})
    user = _user()

    started = await interview.start(session, user)
    finished = await interview.answer(session, user, started["session_id"], "我喜欢折腾数码和独立游戏")

    assert finished["done"] is True
    assert finished["draft"]["display_name"] == "小测改"

    # 收尾：草稿能落成正式 PersonaFile
    file = await interview.load_draft(session, user, started["session_id"])
    assert file.display_name == "小测改"
    assert len(file.interests) >= 3


@pytest.mark.asyncio
async def test_interview_answer_on_missing_session_raises(session, fake_llm):
    fake_llm({})
    with pytest.raises(Exception):
        await interview.answer(session, _user(), "pi_not_exist", "你好")


@pytest.mark.asyncio
async def test_interview_offline_llm_gives_friendly_error(session):
    """LLM 不可用时要给出**带替代路径**的提示（改用手动编辑），而不是裸异常。"""
    from app.errors import AppError
    from app.llm.gateway import set_llm

    class _Offline:
        offline = True
        offline_reason = "未配置 LLM_API_KEY"
        degraded = False
        llm_fail_streak = 0

        async def json(self, *a, **k):  # noqa: ANN002, ANN003
            raise AssertionError("offline 时不应发起调用")

    set_llm(_Offline())  # conftest 的 reset 钩子会在测试后清理
    with pytest.raises(AppError) as exc:
        await interview.start(session, _user())
    assert "手动编辑" in str(exc.value)
