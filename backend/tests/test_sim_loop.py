"""04 §2：完整 tick 循环 + E2E 验收（fast-forward 后的校园墙与对话数）。

对应 10 §2 WS1 交付物：`fast-forward 48` 后校园墙 ≥10 帖、≥5 对话。

注意：`Ticker.tick()` 内部自建 session（`session_scope()`），因此这些测试
只通过 `world` 改内存状态，再用独立 session 校验库里的结果，避免
"object already attached to another session"。
"""
from __future__ import annotations

import pytest
from sqlmodel import select

from app.sim import dialogue as dlg_mod
from app.sim import memory as mem_mod
from app.sim.ticker import Ticker


def _fresh_session():
    from app.db import session_scope

    return session_scope()


# ─────────────── tick 单步 ───────────────


@pytest.mark.asyncio
async def test_single_tick_advances_time_and_persists(world):
    t = Ticker()
    t.world = world
    before = world.tick
    await t.tick(world)
    assert world.tick == before + 1

    from app.models import WorldState

    async with _fresh_session() as s:
        state = (await s.exec(select(WorldState).where(WorldState.id == 1))).first()
        assert state.tick == world.tick


@pytest.mark.asyncio
async def test_tick_moves_characters_to_schedule_location(world):
    """日程执行 → 至少有人被搬到日程地点。"""
    from app.sim.actions import follow_schedule_all
    from app.sim.ticker import wake_all

    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()
    async with _fresh_session() as s:
        await follow_schedule_all(s, world, world.awake_characters())
        await s.commit()

    on_schedule = 0
    for c in world.awake_characters():
        sched = world.schedule_of(c)
        blk = sched.block_at(world.minute) if sched else None
        if blk and c.location_id == blk.location_id:
            on_schedule += 1
    assert on_schedule >= 1


@pytest.mark.asyncio
async def test_tick_new_day_resets_daily_counters(world, offline_llm):
    """06:00 新一天：affinity_delta_today 归零。"""
    a, b = list(world.characters.values())[0], list(world.characters.values())[1]
    async with _fresh_session() as s:
        rel = await mem_mod.ensure_relationship(s, a.id, b.id)
        rel.affinity_delta_today = 7
        s.add(rel)
        await s.commit()

    world.state.minute_of_day = 1410  # 23:30 → 下一次 advance 跨到 06:00
    t = Ticker()
    t.world = world
    await t.tick(world)

    async with _fresh_session() as s:
        rows = (await s.exec(select(mem_mod.Relationship))).all()
    assert all(r.affinity_delta_today == 0 for r in rows)


@pytest.mark.asyncio
async def test_wake_and_sleep(world):
    from app.sim.ticker import sleep_all, wake_all

    for c in world.characters.values():
        if c.kind != "system":
            c.is_asleep = True
            c.energy = 10
    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()
    assert all(c.energy == 100 for c in world.characters.values() if c.kind != "system")
    assert all(not c.is_asleep for c in world.characters.values() if c.kind != "system")

    async with _fresh_session() as _s:
        sleep_all(world, _s)
        await _s.commit()
        await _s.commit()
    assert all(c.is_asleep for c in world.characters.values() if c.kind != "system")


# ─────────────── 对白配对 ───────────────


@pytest.mark.asyncio
async def test_dialogue_pair_up_limits_daily(world, fake_llm):
    """同一对每天最多 3 次（04 §6.2）。"""
    a, b = list(world.characters.values())[0], list(world.characters.values())[1]
    async with _fresh_session() as s:
        count = 0
        for _ in range(6):
            if await dlg_mod._pair_dialogues_today(s, a.id, b.id, world.day):
                count += 1
            else:
                break
        await s.commit()
    assert count <= 3


@pytest.mark.asyncio
async def test_dialogue_fallback_writes_greeting_memory(world, fake_llm):
    """LLM 无输出 → 兜底打招呼：affinity +2 + 记忆 importance 3。"""
    fake_llm({})
    a, b = list(world.characters.values())[0], list(world.characters.values())[1]
    a.is_asleep = False
    b.is_asleep = False
    a.location_id = b.location_id = "library"

    async with _fresh_session() as s:
        rel_ab = await mem_mod.ensure_relationship(s, a.id, b.id)
        rel_ba = await mem_mod.ensure_relationship(s, b.id, a.id)
        before = rel_ab.affinity
        await dlg_mod._fallback_greeting(s, world, a, b, rel_ab, rel_ba)
        await s.commit()

    async with _fresh_session() as s:
        rows = (await s.exec(select(mem_mod.Memory).where(
            mem_mod.Memory.character_id == a.id,
            mem_mod.Memory.kind == "dialogue"))).all()
        rel2 = await mem_mod.get_relationship(s, a.id, b.id)
    assert rel2 is not None
    assert rel2.affinity == before + 2
    assert rows
    assert rows[-1].importance == 3


# ─────────────── E2E：跑满一天 ───────────────


@pytest.mark.asyncio
async def test_full_day_advances_without_error(world, fake_llm):
    """40 tick × 无 LLM → 靠日程兜底持续推进，不抛异常。"""
    from app.sim.ticker import wake_all

    t = Ticker()
    t.world = world
    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()

    start_day = world.day
    for _ in range(40):
        await t.tick(world)

    assert world.tick >= 40
    assert world.day >= start_day


@pytest.mark.asyncio
async def test_e2e_posts_from_decisions(world, fake_llm):
    """脚本化决策让每个清醒角色都发帖 → 校园墙应快速增长。"""
    from app.models import Post
    from app.sim.ticker import wake_all

    fake_llm(
        {
            "decide": {
                "thought": "发条动态",
                "action": {"type": "post", "board": "wall",
                           "text": "今天在图书馆待了一下午，效率还不错。"},
                "mood_delta": {"valence": 0.05},
                "memory": {"text": "我发了条动态", "importance": 3},
            }
        }
    )

    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()
    for c in world.awake_characters():
        c.last_decided_tick = -99

    t = Ticker()
    t.world = world
    for _ in range(10):
        await t.tick(world)

    async with _fresh_session() as s:
        posts = (await s.exec(select(Post))).all()
    assert len(posts) >= 10


@pytest.mark.asyncio
async def test_e2e_fast_forward_meets_acceptance(world, fake_llm):
    """10 §2 WS1：48 tick 后校园墙 ≥10 帖、≥5 对话。

    脚本里 talk 必须带 `target_id`（04 §5：`talk(target_id, text?)`），
    否则动作会在校验阶段被丢弃、退化成日程兜底 —— 这正是本用例要守住的契约。
    同时也混入 `post`（真实模型不会只说话不发言），否则校园墙永远为空。
    """
    from app.models import Dialogue, Post
    from app.sim.ticker import wake_all

    counter = {"n": 0}
    wall_texts = [
        "今天在图书馆待了一下午，效率还不错。",
        "四食堂新出的糖醋排骨真的可以，推荐。",
        "操场跑了五圈，风很舒服。",
        "论文开题好难，谁来救救我。",
        "深夜奶茶店，第二杯半价，有人吗。",
    ]

    def _pick_action(ctx: dict) -> dict:
        """模拟真实模型的正确行为：优先找人搭话，轮次间隔里发帖。"""
        counter["n"] += 1
        present = ctx.get("present") or []
        target = None
        for line in present:
            if "id=" in line:
                target = line.split("id=", 1)[1].split("；", 1)[0].split("）", 1)[0].strip()
                break

        # 1/3 概率发帖，制造校园墙内容；否则能搭话就搭话
        if target is not None and counter["n"] % 3 != 0:
            return {
                "thought": "想找人说说话",
                "action": {"type": "talk", "target_id": target, "text": "你也在这儿啊。"},
                "mood_delta": {"valence": 0.05},
                "memory": {"text": "我想找人说说话", "importance": 3},
            }
        return {
            "thought": "记录一下此刻",
            "action": {
                "type": "post",
                "board": "wall",
                "text": wall_texts[counter["n"] % len(wall_texts)],
            },
            "mood_delta": {"valence": 0.05},
            "memory": {"text": "我发了条动态", "importance": 3},
        }

    fake_llm(
        {
            "decide": _pick_action,
            "dialogue": {
                "turns": [
                    {"speaker_id": "A", "text": "你也在这儿啊。"},
                    {"speaker_id": "B", "text": "嗯，来赶作业。"},
                    {"speaker_id": "A", "text": "一起吧，我也没写完。"},
                    {"speaker_id": "B", "text": "好啊。"},
                ],
                "a_to_b": {"affinity_delta": 4, "memory": "和同学一起自习"},
                "b_to_a": {"affinity_delta": 3, "memory": "和同学一起自习"},
                "mood_a": {"valence": 0.1},
                "mood_b": {"valence": 0.1},
                "ended_because": "该学习了",
            },
        }
    )

    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
    for c in world.awake_characters():
        c.location_id = "library"
        c.last_decided_tick = -99

    t = Ticker()
    t.world = world
    for _ in range(48):
        await t.tick(world)

    async with _fresh_session() as s:
        posts = (await s.exec(select(Post))).all()
        dlg_rows = (await s.exec(select(Dialogue))).all()
    # 10 §2 WS1 验收：≥10 帖、≥5 场对话
    assert len(dlg_rows) >= 5, f"只有 {len(dlg_rows)} 场对话"
    assert len(posts) >= 10, f"只有 {len(posts)} 帖"


@pytest.mark.asyncio
async def test_tick_survives_llm_failure(world, fake_llm):
    """LLM 全挂时 tick 不崩，降级为兜底。"""
    fake_llm({})
    from app.sim.ticker import wake_all

    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()
    t = Ticker()
    t.world = world
    for _ in range(5):
        await t.tick(world)
    assert world.tick >= 5


@pytest.mark.asyncio
async def test_tick_persists_snapshot_once(world, offline_llm):
    """tick 末尾一次性落库：world_state 的 tick 与内存一致。"""
    from app.models import WorldState
    from app.sim.ticker import wake_all

    async with _fresh_session() as _s:
        wake_all(world, _s)
        await _s.commit()
        await _s.commit()
    t = Ticker()
    t.world = world
    await t.tick(world)

    async with _fresh_session() as s:
        state = (await s.exec(select(WorldState).where(WorldState.id == 1))).first()
        assert state.tick == world.tick
