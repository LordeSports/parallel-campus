"""05 §4：JSON 修复链 + 9 个模板渲染。"""
from __future__ import annotations

import pytest

from app.llm.gateway import coerce, parse_json_lenient, render_template
from app.schemas.domain import (
    Briefing,
    DailySchedule,
    Decision,
    DialogueModel,
    HotEvents,
    MatchReport,
    NewDay,
    PersonaFile,
    Reflection,
)

# ─────────────── JSON 修复链（05 §1.2） ───────────────


def test_lenient_plain_json():
    assert parse_json_lenient('{"a": 1}') == {"a": 1}


def test_lenient_fenced_json():
    raw = '```json\n{"a": 1, "b": [1, 2]}\n```'
    assert parse_json_lenient(raw) == {"a": 1, "b": [1, 2]}


def test_lenient_with_prose_around():
    raw = '好的，这是结果：\n{"a": 1}\n希望有帮助！'
    assert parse_json_lenient(raw) == {"a": 1}


def test_lenient_trailing_comma():
    assert parse_json_lenient('{"a": 1, "b": 2,}') == {"a": 1, "b": 2}


def test_lenient_single_quotes():
    assert parse_json_lenient("{'a': 'x', 'b': 1}") == {"a": "x", "b": 1}


def test_lenient_python_literals():
    data = parse_json_lenient('{"a": True, "b": False, "c": None}')
    assert data == {"a": True, "b": False, "c": None}


def test_lenient_truncated_json():
    """截断 JSON：补齐未闭合括号后应可解析（05 §1.2 步骤 3）。"""
    data = parse_json_lenient('{"a": 1, "b": {"c": 2')
    assert data.get("a") == 1


def test_lenient_truncated_in_string():
    data = parse_json_lenient('{"a": "还没写完')
    assert "a" in data


def test_lenient_truncated_trailing_key():
    data = parse_json_lenient('{"a": 1, "b"')
    assert data.get("a") == 1


def test_lenient_garbage_raises():
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(NewDay, "完全不是 JSON")


# ─────────────── schema 强制：缺字段 / 越界 / 超长 ───────────────


def test_coerce_missing_fields_use_defaults():
    """修复链步骤 4：缺字段用 schema 默认值填补。"""
    d = coerce(NewDay, '{"weather": {"kind": "sunny", "temp_c": 20, "text": "晴"}}')
    assert isinstance(d, NewDay)
    assert d.weather.kind == "sunny"
    assert d.announcements == []


def test_coerce_missing_required_field_raises():
    """必填字段缺失且无默认 → 抛 LlmOutputError，由调用方兜底（05 §1.2 步骤 5）。"""
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(NewDay, '{"announcements": []}')


def test_coerce_bad_enum_raises_for_caller_fallback():
    """非法枚举无法修补 → 抛错，调用方走 _pick_fallback_weather。"""
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(NewDay, '{"weather": {"kind": "沙尘暴", "temp_c": 20, "text": "x"}}')


def test_coerce_out_of_range_raises_for_caller_fallback():
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(NewDay, '{"weather": {"kind": "sunny", "temp_c": 999, "text": "x"}}')


def test_coerce_overlong_text_raises_for_caller_fallback():
    """超长且 schema 无截断 validator → 抛错，由调用方兜底。"""
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(NewDay, '{"weather": {"kind": "sunny", "temp_c": 20, "text": "' + "长" * 200 + '"}}')


def test_coerce_decision_action_normalized():
    d = coerce(
        Decision,
        '{"thought": "想去图书馆", "action": {"type": "move", "location_id": "library"},'
        ' "memory": {"text": "我决定去图书馆", "importance": 3}}',
    )
    assert d.action.type == "move"
    assert d.action.location_id == "library"
    assert d.memory.text == "我决定去图书馆"


def test_coerce_decision_unknown_action_raises():
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(Decision, '{"thought": "x", "action": {"type": "fly_to_moon"}}')


_DIALOGUE_OK = (
    '{"turns": [{"speaker_id": "a", "text": " 你好 "}, {"speaker_id": "b", "text": "你也好"}],'
    ' "a_to_b": {"affinity_delta": 3, "memory": "和乙聊了几句"},'
    ' "b_to_a": {"affinity_delta": 2, "memory": "和甲聊了几句"},'
    ' "mood_a": {"valence": 0.1}, "mood_b": {"valence": 0.1},'
    ' "ended_because": "上课了"}'
)


def test_coerce_dialogue_turns_stripped():
    d = coerce(DialogueModel, _DIALOGUE_OK)
    assert isinstance(d, DialogueModel)
    assert d.turns[0].text == "你好"


def test_coerce_dialogue_missing_side_raises():
    """缺 a_to_b 等必填字段 → 抛错，调用方走 _fallback_greeting（05 §3 P4）。"""
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(DialogueModel, '{"turns": [{"speaker_id": "a", "text": "你好"}]}')


def test_coerce_dialogue_affinity_delta_out_of_range_raises():
    from app.errors import LlmOutputError

    bad = _DIALOGUE_OK.replace('"affinity_delta": 3', '"affinity_delta": 999')
    with pytest.raises(LlmOutputError):
        coerce(DialogueModel, bad)


def test_coerce_reflection_insights_capped():
    ins = ",".join(f'{{"text": "想法{i}", "importance": 8}}' for i in range(6))
    d = coerce(Reflection, '{"insights": [' + ins + "]}")
    assert len(d.insights) <= 3


def test_coerce_hot_events_duration_out_of_range_raises():
    from app.errors import LlmOutputError

    with pytest.raises(LlmOutputError):
        coerce(
            HotEvents,
            '{"events": [{"title": "拆机台", "description": "在图书馆",'
            ' "location_id": "library", "duration_ticks": 99, "tags": ["科技"],'
            ' "wall_post": "来玩", "source_index": "H1"}]}',
        )


def test_coerce_hot_event_valid():
    d = coerce(
        HotEvents,
        '{"events": [{"title": "拆机台", "description": "在图书馆",'
        ' "location_id": "library", "duration_ticks": 8, "tags": ["科技"],'
        ' "wall_post": "来玩", "source_index": "H1"}]}',
    )
    assert len(d.events) == 1
    assert d.events[0].location_id == "library"


def test_coerce_match_report_valid():
    d = coerce(
        MatchReport,
        '{"day_summary": "你的分身今天很好。", "top_friends": ['
        '{"character_id": "npc_1", "story": "在图书馆聊了科幻。",'
        ' "shared_topics": ["科幻"], "affinity": 10, "affinity_delta": 5}]}',
    )
    assert d.day_summary
    assert len(d.top_friends) == 1


def test_coerce_match_report_caps_friends_at_three():
    friends = ",".join(
        f'{{"character_id": "npc_{i}", "story": "s", "shared_topics": [],'
        f' "affinity": 1, "affinity_delta": 1}}'
        for i in range(5)
    )
    d = coerce(MatchReport, '{"day_summary": "x", "top_friends": [' + friends + "]}")
    assert len(d.top_friends) == 3


# ─────────────── 模板渲染（9 个，夹具 ctx） ───────────────

_FIXTURE_CTX = {
    "persona_extract": {
        "evidence": "【C1】测试内容",
        "stats": {"contents": 1, "followees": 1, "favlists": 0, "saved_items": 0},
        "display_name_hint": "测试",
        "persona_schema_doc": "{}",
        "persona_schema_doc_unused": "",
    },
    "daily_schedule": {
        "mode": "batch",
        "characters": [
            {
                "id": "npc_1", "name": "甲", "persona_brief": "甲的人设。",
                "identity": "计算机系 大一", "habits": "", "yesterday_reflections": [],
                "top_relations": [{"name": "乙", "affinity": 3}],
            }
        ],
        "day": 1, "weekday_label": "周一",
        "weather": {"kind": "sunny", "temp_c": 22, "text": "晴"},
        "calendar_items": ["08:00 高数 @teaching_a"],
        "locations": ["teaching_a: 教学楼（上课）"],
        "constraints": "07:00–23:30 无缝覆盖",
    },
    "decide": {
        "me": {
            "id": "npc_1", "name": "甲", "persona_brief": "甲的人设。",
            "identity": "计算机系 大一", "mood_label": "平静", "energy_label": "精神",
        },
        "now": {
            "time_label": "第1天 08:00", "weekday_label": "周一", "weather_text": "晴",
            "location": {"name": "教学楼", "ambience": "走廊里有人在小跑。", "crowd_label": "有点热闹"},
        },
        "present": ["乙（同学；你对TA好感 3，还不熟）"],
        "schedule_now": "08:00-09:30 在teaching_a 上高数",
        "schedule_next": "12:00-13:00 在canteen 午饭",
        "stimuli": ["乙 刚发了一条你感兴趣的帖子（salience 4）"],
        "memories": ["- 昨天和乙一起上了课。"],
        "active_events": ["社团招新 @中心广场"],
        "recent_posts": ["（1赞）今天天气不错"],
        "whisper": None,
        "actions_doc": "move / talk / post",
        "locations": [{"id": "teaching_a", "name": "教学楼"}],
    },
    "dialogue": {
        "a": {"id": "npc_1", "name": "甲", "persona_brief": "甲的人设。", "mood_label": "平静"},
        "b": {"id": "npc_2", "name": "乙", "persona_brief": "乙的人设。", "mood_label": "兴奋"},
        "relation_ab": {"affinity": 3, "familiarity_label": "刚认识", "tags": [], "last_topic": None},
        "relation_ba": {"affinity": 0, "familiarity_label": "刚认识", "tags": [], "last_topic": None},
        "scene": {
            "time_label": "第1天 08:00", "location_name": "教学楼",
            "ambience": "走廊里有人在小跑。", "weather_text": "晴",
        },
        "opener": "乙 先开的口。",
        "memories_a": [], "memories_b": [], "events": [], "max_turns": 8,
    },
    "reflect": {
        "me": {"name": "甲", "persona_brief": "甲的人设。"},
        "day_label": "第1天 23:00",
        "memories": ["- 今天上了高数。"],
        "relation_changes": ["乙: +3"],
    },
    "env_new_day": {
        "day": 2, "weekday_label": "周二", "season": "秋",
        "calendar_items": ["19:00 社团招新 @field"],
        "yesterday_briefing": "第1天，晴。", "yesterday_weather": "",
    },
    "env_hot_events": {
        "hot_items": ["H1 标题 — 摘要 — https://www.zhihu.com/question/1"],
        "locations": [{"id": "field", "name": "中心广场", "kind": "outdoor", "tags": ["活动"]}],
        "active_titles": [], "day_label": "第2天 09:00", "weather": "晴",
    },
    "env_briefing": {
        "day_label": "第1天 23:30", "weather": "晴",
        "stats": {"dialogues": 3, "posts": 5, "comments": 9},
        "top_posts": ["（5赞）今天很开心"], "events": ["社团招新"],
        "notable": ["甲 和 乙 好感 +3"],
    },
    "match_report": {
        "me": {"id": "npc_1", "name": "甲", "persona_brief": "甲的人设。"},
        "day_label": "第1天 23:30",
        "candidates": [{
            "character_id": "npc_2", "name": "乙", "archetype": "同学",
            "affinity": 5, "affinity_delta": 3, "tags": ["科幻"], "memories": ["- 一起聊了科幻。"],
        }],
    },
}

_TEMPLATES = list(_FIXTURE_CTX.keys())


@pytest.mark.parametrize("name", _TEMPLATES)
def test_template_renders(name):
    out = render_template(name, _FIXTURE_CTX[name])
    assert out.strip()
    assert "{{" not in out and "{%" not in out


@pytest.mark.parametrize("name", _TEMPLATES)
def test_template_under_budget(name):
    """05 §4：粗估 tokens = len/1.5 < 6000。"""
    out = render_template(name, _FIXTURE_CTX[name])
    assert len(out) / 1.5 < 6000


def test_all_nine_templates_exist():
    from app.config import PROMPTS_DIR

    found = {p.stem for p in PROMPTS_DIR.glob("*.j2")}
    assert found == set(_TEMPLATES), f"模板不一致：{found ^ set(_TEMPLATES)}"


def test_undefined_variable_strict():
    """StrictUndefined：缺少变量必须报错，而不是静默渲染成空。"""
    from jinja2 import UndefinedError

    with pytest.raises(UndefinedError):
        render_template("env_new_day", {"day": 1})
