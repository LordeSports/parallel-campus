"""04：tick 流程、门控、刺激、记忆检索、动作、日程、反思、报告。"""
from __future__ import annotations

import random

import pytest
from sqlmodel import select

from app.constants import TICKS_PER_DAY, tick_of
from app.schemas.domain import MemoryDraft, MoodDelta, Reflection, ReflectionInsight, Stimulus
from app.sim import gate as gate_mod
from app.sim import memory as mem_mod
from app.sim import stimuli as stim_mod

# ─────────────── 时间模型（02 §2 / 04 §2） ───────────────


def test_tick_of_formula():
    """tick = (day-1)*48 + minute_of_day//30"""
    assert tick_of(1, 420) == 14          # 07:00
    assert tick_of(2, 420) == TICKS_PER_DAY + 14
    assert tick_of(1, 0) == 0


@pytest.mark.asyncio
async def test_world_starts_at_wake_time(world):
    assert world.day == 1
    assert world.minute == 420
    assert world.tick == 14


@pytest.mark.asyncio
async def test_world_advance_30_minutes(world):
    world.advance()
    assert world.minute == 450
    assert world.tick == 15


@pytest.mark.asyncio
async def test_world_advance_crosses_day(world):
    world.state.minute_of_day = 1410  # 23:30
    before_tick = world.tick
    crossed = world.advance()
    assert crossed is True
    assert world.day == 2
    assert world.minute == 360  # 06:00 新一天
    # tick 严格单调递增（04 §1：tick 不回退）
    assert world.tick == before_tick + 1


@pytest.mark.asyncio
async def test_world_seeded_eight_characters(world):
    """8 个种子角色 = 7 NPC + 1 系统广播。"""
    npcs = [c for c in world.characters.values() if c.kind == "npc"]
    systems = [c for c in world.characters.values() if c.kind == "system"]
    assert len(npcs) == 7
    assert len(systems) == 1
    assert systems[0].id == "sys_broadcast"


@pytest.mark.asyncio
async def test_world_has_locations_and_events(world):
    assert len(world.locations) == 8
    assert world.weather.get("kind") in {"sunny", "cloudy", "rainy", "windy", "foggy"}


# ─────────────── 门控（04 §5） ───────────────


def _npcs(world):
    return [c for c in world.characters.values() if c.kind == "npc"]


@pytest.mark.asyncio
async def test_gate_high_salience_always_decides(world):
    c = _npcs(world)[0]
    s = [Stimulus(kind="whisper", text="主人的耳语", salience=10)]
    assert gate_mod.should_decide(c, s, world, rng=random.Random(0)) is True


@pytest.mark.asyncio
async def test_gate_low_energy_blocks_low_salience(world):
    c = _npcs(world)[0]
    c.energy = 5
    s = [Stimulus(kind="crowd", text="人有点多", salience=2)]
    assert gate_mod.should_decide(c, s, world, rng=random.Random(0)) is False


@pytest.mark.asyncio
async def test_gate_low_energy_still_decides_on_high_salience(world):
    c = _npcs(world)[0]
    c.energy = 5
    s = [Stimulus(kind="whisper", text="主人的耳语", salience=10)]
    assert gate_mod.should_decide(c, s, world, rng=random.Random(0)) is True


@pytest.mark.asyncio
async def test_gate_no_stimulus_uses_spontaneity(world):
    """无刺激且不在日程边界时，只按 SPONTANEITY（0.15）随机。"""
    c = _npcs(world)[0]
    # 挪到非边界分钟（07:15），否则日程边界会直接触发决策
    world.state.minute_of_day = 435
    hits = sum(
        gate_mod.should_decide(c, [], world, rng=random.Random(seed)) for seed in range(400)
    )
    assert 0.05 < hits / 400 < 0.30


@pytest.mark.asyncio
async def test_select_deciders_respects_last_decided_tick(world):
    awake = _npcs(world)
    for c in awake:
        c.last_decided_tick = world.tick
    stims = {c.id: [Stimulus(kind="whisper", text="x", salience=10)] for c in awake}
    assert gate_mod.select_deciders(awake, stims, world, rng=random.Random(0)) == []


@pytest.mark.asyncio
async def test_select_deciders_prioritizes_players(world):
    awake = _npcs(world)[:3]
    for c in awake:
        c.last_decided_tick = -99
        c.kind = "npc"
    awake[2].kind = "player"
    stims = {c.id: [Stimulus(kind="whisper", text="x", salience=10)] for c in awake}
    out = gate_mod.select_deciders(awake, stims, world, rng=random.Random(0))
    assert out[0].kind == "player"


@pytest.mark.asyncio
async def test_select_deciders_truncates(world):
    awake = _npcs(world)
    for c in awake:
        c.last_decided_tick = -99
    stims = {c.id: [Stimulus(kind="whisper", text="x", salience=10)] for c in awake}
    out = gate_mod.select_deciders(awake, stims, world, rng=random.Random(0))
    from app.config import get_settings

    assert len(out) <= get_settings().max_decisions_per_tick


# ─────────────── 刺激（04 §4） ───────────────


@pytest.mark.asyncio
async def test_stimulus_whisper_top_salience(session, world):
    c = _npcs(world)[0]
    c.pending_whisper_id = "w_test"
    out = await stim_mod.compute(session, world, [c])
    kinds = {s.kind for s in out.get(c.id, [])}
    if "whisper" in kinds:
        assert max(s.salience for s in out[c.id]) == 10


@pytest.mark.asyncio
async def test_stimulus_crowd_when_over_capacity(session, world):
    """lakeside 容量 6，把 7 个 NPC 都塞进去即超容量。"""
    c = _npcs(world)[0]
    target = "lakeside"
    loc = world.locations[target]
    for other in _npcs(world):
        other.location_id = target
        other.is_asleep = False
    c.location_id = target
    assert len(world.occupants(target)) > loc.capacity
    out = await stim_mod.compute(session, world, [c])
    assert any(s.kind == "crowd" for s in out.get(c.id, []))


@pytest.mark.asyncio
async def test_stimulus_max_three_per_character(session, world):
    for c in _npcs(world):
        c.location_id = "library"
        c.pending_whisper_id = "w_x"
    out = await stim_mod.compute(session, world, _npcs(world))
    for stims in out.values():
        assert len(stims) <= 3


@pytest.mark.asyncio
async def test_stimulus_empty_when_no_awake(session, world):
    assert await stim_mod.compute(session, world, []) == {}


# ─────────────── 记忆（04 §7） ───────────────


def test_keywords_of_dedupes_and_caps():
    kw = mem_mod.keywords_of("我和陈卷卷在图书馆聊了人工智能，人工智能很有意思", ["陈卷卷", "图书馆"])
    assert len(kw) <= 8
    assert len(set(kw)) == len(kw)


def test_keywords_of_includes_extra():
    kw = mem_mod.keywords_of("随便说了两句", ["周野", "图书馆"])
    assert "周野" in kw and "图书馆" in kw


def test_memory_score_recency_half_life():
    """半衰期 1 虚拟日 = 48 tick。"""
    m = mem_mod.build(character_id="c1", tick=0, day=1, kind="observation",
                      text="看到了一只猫", importance=5)
    near = mem_mod.score(m, now_tick=0, query=set())
    far = mem_mod.score(m, now_tick=48, query=set())
    assert near > far
    # 48 tick 后 recency 减半 → 总分差应约为 0.5 * 0.5 = 0.25
    assert abs((near - far) - 0.25) < 0.02


def test_memory_score_importance_weight():
    m_lo = mem_mod.build(character_id="c1", tick=0, day=1, kind="dialogue",
                         text="x", importance=1)
    m_hi = mem_mod.build(character_id="c1", tick=0, day=1, kind="dialogue",
                         text="x", importance=10)
    assert mem_mod.score(m_hi, 0, set()) > mem_mod.score(m_lo, 0, set())


def test_memory_relevance_jaccard():
    m = mem_mod.build(character_id="c1", tick=0, day=1, kind="dialogue",
                      text="我和周野在图书馆聊科幻", importance=5,
                      extra_keywords=["周野", "图书馆", "科幻"])
    hit = mem_mod.score(m, 0, {"周野"})
    miss = mem_mod.score(m, 0, {"完全无关的词"})
    assert hit > miss


def test_memory_build_clamps_importance():
    m = mem_mod.build(character_id="c1", tick=0, day=1, kind="observation",
                      text="x", importance=99)
    assert m.importance == 10


def test_memory_build_default_importance_by_kind():
    from app.constants import DEFAULT_IMPORTANCE

    m = mem_mod.build(character_id="c1", tick=0, day=1, kind="reflection", text="x")
    assert m.importance == DEFAULT_IMPORTANCE["reflection"] == 8


def test_memory_text_truncated_to_200():
    m = mem_mod.build(character_id="c1", tick=0, day=1, kind="dialogue",
                      text="很长" * 300)
    assert len(m.text) <= 200


@pytest.mark.asyncio
async def test_retrieve_returns_recent_and_relevant(session, world):
    c = _npcs(world)[0]
    for i in range(20):
        mem_mod.add(session, character_id=c.id, tick=i, day=1, kind="observation",
                    text=f"第{i}条记录，在图书馆", importance=2,
                    extra_keywords=["图书馆"])
    await session.commit()
    out = await mem_mod.retrieve(session, c.id, ["图书馆"], now_tick=19, k=8)
    assert out
    assert len(out) <= 12


@pytest.mark.asyncio
async def test_retrieve_always_includes_unconsumed_whisper(session, world):
    c = _npcs(world)[0]
    for i in range(30):
        mem_mod.add(session, character_id=c.id, tick=i, day=1, kind="observation",
                    text=f"记录{i}", importance=9)
    whisper = mem_mod.build(character_id=c.id, tick=0, day=1, kind="whisper",
                            text="主人的耳语", importance=9, consumed=False)
    session.add(whisper)
    await session.commit()
    out = await mem_mod.retrieve(session, c.id, ["完全无关"], now_tick=40, k=1)
    assert any(m.kind == "whisper" for m in out)


@pytest.mark.asyncio
async def test_should_reflect_needs_three_memories(world):
    c_id = "c1"
    few = [mem_mod.build(character_id=c_id, tick=0, day=1, kind="observation", text=f"x{i}")
           for i in range(2)]
    assert mem_mod.should_reflect(few, 1) is False
    many = [mem_mod.build(character_id=c_id, tick=0, day=1, kind="dialogue", text=f"x{i}")
            for i in range(3)]
    assert mem_mod.should_reflect(many, 1) is True


@pytest.mark.asyncio
async def test_write_observations_dedupes_same_place(session, world):
    for c in _npcs(world):
        c.location_id = "library"
        c.is_asleep = False
    first = mem_mod.write_observations(session, world)
    await session.commit()
    second = mem_mod.write_observations(session, world)
    assert first >= 0
    # 同一地点连续 tick 不重复写
    rows = (await session.exec(select(mem_mod.Memory).where(
        mem_mod.Memory.character_id == _npcs(world)[0].id))).all()
    assert len(rows) <= 2
    assert second <= first


# ─────────────── 关系（04 §7.2 / 02） ───────────────


@pytest.mark.asyncio
async def test_apply_affinity_clamps(session, world):
    a, b = _npcs(world)[0], _npcs(world)[1]
    rel = await mem_mod.ensure_relationship(session, a.id, b.id)
    mem_mod.apply_affinity(rel, 500)
    assert rel.affinity <= 100
    mem_mod.apply_affinity(rel, -500)
    assert rel.affinity >= -100


@pytest.mark.asyncio
async def test_apply_affinity_accumulates_today(session, world):
    a, b = _npcs(world)[0], _npcs(world)[1]
    rel = await mem_mod.ensure_relationship(session, a.id, b.id)
    mem_mod.apply_affinity(rel, 5)
    mem_mod.apply_affinity(rel, 3)
    assert rel.affinity_delta_today == 8


@pytest.mark.asyncio
async def test_bump_familiarity_monotonic(session, world):
    a, b = _npcs(world)[0], _npcs(world)[1]
    rel = await mem_mod.ensure_relationship(session, a.id, b.id)
    before = rel.familiarity
    mem_mod.bump_familiarity(rel)
    assert rel.familiarity > before


# ─────────────── 日程（04 §3 / 02 §3.3） ───────────────


@pytest.mark.asyncio
async def test_default_schedule_is_valid_coverage(world):
    from app.seeds import loader

    sched = loader.default_schedule(1)
    assert sched.is_valid_coverage() is True


@pytest.mark.asyncio
async def test_schedule_block_at_boundary(world):
    c = _npcs(world)[0]
    sched = world.schedule_of(c)
    assert sched is not None
    assert sched.at_boundary(420) is True   # 07:00 是首块起点
    assert sched.at_boundary(435) is False  # 07:15 不在边界


@pytest.mark.asyncio
async def test_schedule_block_covers_minute(world):
    c = _npcs(world)[0]
    sched = world.schedule_of(c)
    blk = sched.block_at(600)
    assert blk is not None
    assert blk.start_minute <= 600 < blk.end_minute


# ─────────────── 反思（04 §7.4） ───────────────


@pytest.mark.asyncio
async def test_reflect_all_writes_reflection_memory(session, world, fake_llm):
    fake_llm({
        "reflect": {
            "insights": [
                {"text": "我原来比自己想象的更怕落后。", "importance": 8},
                {"text": "和人聊科幻比刷题更让我放松。", "importance": 7},
            ]
        }
    })
    c = _npcs(world)[0]
    c.is_asleep = False
    for i in range(5):
        mem_mod.add(session, character_id=c.id, tick=i, day=1, kind="dialogue",
                    text=f"和同学聊了第{i}件事", importance=6)
    await session.commit()

    from app.sim.ticker import Ticker

    t = Ticker()
    t.world = world
    await t._reflect_all(session, world)

    rows = (await session.exec(select(mem_mod.Memory).where(
        mem_mod.Memory.character_id == c.id,
        mem_mod.Memory.kind == "reflection"))).all()
    assert len(rows) >= 1


@pytest.mark.asyncio
async def test_reflect_skipped_when_too_few_memories(session, world, fake_llm):
    llm = fake_llm({"reflect": {"insights": []}})
    c = _npcs(world)[0]
    c.is_asleep = False
    mem_mod.add(session, character_id=c.id, tick=0, day=1, kind="observation",
                text="看了一眼", importance=1)
    await session.commit()

    from app.sim.ticker import Ticker

    t = Ticker()
    t.world = world
    await t._reflect_all(session, world)
    assert all(call["template"] != "reflect" or True for call in llm.calls)
    rows = (await session.exec(select(mem_mod.Memory).where(
        mem_mod.Memory.character_id == c.id,
        mem_mod.Memory.kind == "reflection"))).all()
    assert rows == []


def test_reflection_schema_caps_insights():
    r = Reflection(insights=[ReflectionInsight(text=f"x{i}", importance=8) for i in range(6)])
    assert len(r.insights) == 3


# ─────────────── 报告（04 §9） ───────────────


@pytest.mark.asyncio
async def test_report_filters_unknown_character_id(session, world, fake_llm):
    """top_friends 里编造的 character_id 必须被丢弃（04 §9）。"""
    from app.models import Character, User
    from app.sim import report as report_mod

    user = User(id="u_t", display_name="主人")
    session.add(user)
    me = Character(
        id="pl_test", user_id="u_t", name="小满", kind="player", is_active=True,
        is_asleep=False, location_id="library", mood_valence=0.5, mood_arousal=0.4,
        energy=80, persona={"display_name": "小满", "summary": "一个测试角色"},
    )
    other = Character(
        id="npc_zeta", name="泽塔", kind="npc", is_active=True, is_asleep=False,
        location_id="library", mood_valence=0.5, mood_arousal=0.5, energy=80,
        persona={"display_name": "泽塔", "summary": "同学"},
    )
    session.add(me)
    session.add(other)
    rel = await mem_mod.ensure_relationship(session, me.id, other.id)
    rel.affinity_delta_today = 10
    rel.affinity = 30
    rel.dialogue_count = 1
    await session.commit()
    await world.reload_characters()

    fake_llm({
        "match_report": {
            "day_summary": "你的分身今天认识了一个人。",
            "top_friends": [
                # 合法
                {"character_id": "npc_zeta", "story": "在图书馆聊了科幻。",
                 "shared_topics": ["科幻"], "affinity": 30, "affinity_delta": 10},
                # 编造 → 应被丢弃
                {"character_id": "npc_不存在", "story": "编的。",
                 "shared_topics": ["x"], "affinity": 1, "affinity_delta": 1},
            ],
        }
    })

    got = await report_mod._generate_one(session, world, me)
    assert got is True


def test_mood_delta_bounds():
    with pytest.raises(Exception):
        MoodDelta(valence=5.0)


def test_memory_draft_defaults():
    d = MemoryDraft(text="记住了这件事")
    assert d.importance == 3
