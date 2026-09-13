"""Ticker 状态机（spec/04 §1–§2、spec/02 §5.1）。

```
paused ──resume──► idle ◄──observers==0── online
  ▲                 │ observers≥1 ─────────►│
  └──pause──────────┴────────────────────────┘
fast_forward：admin 触发，跑完 N tick 后回到 idle/online（按观众数）
```
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from sqlmodel import col, select

from ..config import settings
from ..constants import decompose_tick
from ..db import session_scope, write_lock, write_session
from ..models import LlmUsage, Memory, WorldState, now_utc
from ..schemas.events import make_event
from . import actions as actions_mod
from . import char_agent, dialogue as dialogue_mod, env_agent, gate, memory as mem_mod
from . import report as report_mod, stimuli as stimuli_mod
from .bus import bus
from .world import World, get_world, set_world

log = logging.getLogger("pc.ticker")


def decide_mode(observers: int, admin_override: str | None, remaining_ticks: int) -> str:
    if admin_override == "paused":
        return "paused"
    if admin_override == "fast_forward" or remaining_ticks > 0:
        return "fast_forward"
    return "online" if observers >= 1 else "idle"


def tick_period(mode: str) -> float:
    if mode == "online":
        return float(settings.tick_seconds_online)
    if mode == "idle":
        return float(settings.tick_seconds_idle)
    return 0.0


class Ticker:
    """单例心跳。`start()` 起后台任务；`stop()` 收尾。"""

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self.world: World | None = None
        self.last_tick_started: float = 0.0
        self.last_tick_finished: float = 0.0
        self.running = False
        self._usage_tasks: set[asyncio.Task[None]] = set()
        self._llm_install()

    # ── LLM usage 落库 ──

    def _llm_install(self) -> None:
        from ..llm.gateway import get_llm

        async def _persist_usage(**kw: Any) -> None:
            async with write_lock:
                async with write_session() as session:
                    session.add(
                        LlmUsage(
                            tier=kw.get("tier", "cheap"),
                            template=kw.get("template", ""),
                            model=kw.get("model", ""),
                            prompt_tokens=int(kw.get("prompt_tokens") or 0),
                            completion_tokens=int(kw.get("completion_tokens") or 0),
                            latency_ms=int(kw.get("latency_ms") or 0),
                            ok=bool(kw.get("ok")),
                            error=(kw.get("error") or None),
                        )
                    )
                    state = (
                        await session.exec(select(WorldState).where(WorldState.id == 1))
                    ).first()
                    if state is not None:
                        if kw.get("ok"):
                            state.llm_fail_streak = 0
                            if state.degraded:
                                state.degraded = False
                                bus.emit(make_event("degraded", state.tick, state.day,
                                                    {"degraded": False}))
                        else:
                            state.llm_fail_streak += 1
                            if state.llm_fail_streak >= 3 and not state.degraded:
                                state.degraded = True
                                bus.emit(make_event("degraded", state.tick, state.day,
                                                    {"degraded": True}))
                        session.add(state)
                    await session.commit()
                    if state is not None and self.world is not None:
                        self.world.state.llm_fail_streak = state.llm_fail_streak
                        self.world.state.degraded = state.degraded

        async def _write_usage(**kw: Any) -> None:
            try:
                await _persist_usage(**kw)
            except Exception:
                log.exception("LLM 用量落库失败")

        async def _sink(**kw: Any) -> None:
            # LLM 调用可能发生在持锁事务内；只排队，不能同步等待另一条写连接。
            task = asyncio.create_task(_write_usage(**kw), name="pc-llm-usage")
            self._usage_tasks.add(task)
            task.add_done_callback(self._usage_tasks.discard)

        get_llm().usage_sink = _sink

    # ── 生命周期 ──

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self.running = True
        self._task = asyncio.create_task(self._loop(), name="pc-ticker")
        log.info("Ticker 已启动")

    async def stop(self) -> None:
        self._stop.set()
        self.running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        if self._usage_tasks:
            # 数据库在 ticker.stop() 后关闭，先等待已排队的用量记录。
            await asyncio.gather(*tuple(self._usage_tasks))
        log.info("Ticker 已停止")

    async def _loop(self) -> None:
        try:
            self.world = await get_world()
        except Exception:
            log.exception("世界载入失败，Ticker 退出")
            return

        while not self._stop.is_set():
            try:
                world = self.world
                if world is None:
                    break
                observers = bus.subscriber_count()
                mode = decide_mode(observers, world.state.admin_override, world.state.remaining_ticks)
                world.state.speed_mode = mode
                world.state.observer_count = observers

                if mode == "paused":
                    await asyncio.sleep(1.0)
                    continue

                started = asyncio.get_event_loop().time()
                self.last_tick_started = started
                try:
                    await self.tick(world)
                except Exception:
                    log.exception("tick 失败")
                    world.state.llm_fail_streak += 1
                finally:
                    if world.state.remaining_ticks > 0:
                        world.state.remaining_ticks -= 1
                        if world.state.remaining_ticks == 0:
                            world.state.admin_override = None
                            log.info("fast_forward 完成")

                elapsed = asyncio.get_event_loop().time() - started
                self.last_tick_finished = asyncio.get_event_loop().time()
                period = tick_period(mode)
                await asyncio.sleep(max(0.0, period - elapsed))
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("Ticker 循环异常")
                await asyncio.sleep(1.0)

    # ── 单个 tick（04 §2 的 20 步）──

    async def tick(self, world: World) -> None:
        # 1. 推进时间
        crossed = world.advance()
        # 2. emit tick
        world.emit(
            make_event("tick", world.tick, world.day, world.tick_payload(
                tick_period(world.state.speed_mode)))
        )

        async with write_lock:
            # ── 阶段 A：环境推进（含 LLM 的热榜/事件，但只在**写短事务**里落库）──
            async with write_session() as session:
                # 3. 06:00 新一天
                if world.is_new_day() or crossed:
                    await env_agent.new_day(session, world)

                # 4. 07:00 醒来
                if world.is_wake_time():
                    wake_all(world, session)

                # 6. 热榜
                try:
                    await env_agent.maybe_pull_hot(session, world)
                except Exception:
                    log.exception("maybe_pull_hot 失败")

                # 7. 事件状态机
                try:
                    await env_agent.roll_events(session, world)
                except Exception:
                    log.exception("roll_events 失败")

                # 8. 清醒角色
                awake = world.awake_characters()

                # 9. 刺激
                stimuli_mod.clear_cache()
                try:
                    stim_map = await stimuli_mod.compute(session, world, awake)
                except Exception:
                    log.exception("stimuli.compute 失败")
                    stim_map = {}

                # 10. 门控
                deciders = gate.select_deciders(awake, stim_map, world)
            # ← 阶段 A 事务在此提交：SQLite 写锁释放，外部 API 请求可正常写入

            # 11. 并发决策 —— **不持有任何写事务**（LLM 是长尾，持锁会让
            #     dev-login / 发帖等请求等到 busy_timeout 才失败）
            decisions = await self._decide_all(world, deciders, stim_map)

            # ── 阶段 B：动作 + 对话落地 ──
            async with write_session() as session:
                # 12. 未决策 / 超时 → 日程兜底
                applied_ids = set(decisions.keys()) | {c.id for c in deciders}
                for c in awake:
                    if c.id not in decisions and c.id not in applied_ids:
                        await actions_mod.follow_schedule(session, world, c)

                # 注意：deciders 中失败的直接走日程
                for c in deciders:
                    if c.id not in decisions:
                        await actions_mod.follow_schedule(session, world, c)

                # 13. 动作落地
                try:
                    outcome = await actions_mod.apply_all(session, world, decisions)
                except Exception:
                    log.exception("actions.apply_all 失败")
                    outcome = actions_mod.ActionOutcome()

                # 14. 对话
                try:
                    busy = await dialogue_mod.run_all(session, world, outcome)
                    for c, other_name in busy:
                        mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                                    kind="observation", text=f"想找{other_name}聊，TA在忙",
                                    importance=2)
                except Exception:
                    log.exception("dialogue.run_all 失败")

                # 15. 观察写入
                try:
                    mem_mod.write_observations(session, world)
                except Exception:
                    log.exception("write_observations 失败")

                # 16. 同地共处 familiarity += 0.02
                try:
                    await self._co_presence(session, world)
                except Exception:
                    log.exception("co_presence 失败")

                # 17. 精力 −2
                for c in awake:
                    c.energy = max(0, c.energy - 2)

            # ── 阶段 C：日终（反思 / 简报 / 报告）与快照落库 ──
            async with write_session() as session:
                # 18. 23:00 反思
                if world.is_reflect_time():
                    try:
                        await self._reflect_all(session, world)
                    except Exception:
                        log.exception("reflect_all 失败")

                # 19. 23:30 简报 + 报告 + 睡眠
                if world.is_sleep_time():
                    try:
                        await env_agent.briefing(session, world)
                    except Exception:
                        log.exception("briefing 失败")
                    try:
                        await report_mod.generate_all(session, world)
                    except Exception:
                        log.exception("report.generate_all 失败")
                    sleep_all(world, session)

                # 20. 落库 + 清理
                events = bus.take_pending()
                for c in world.characters.values():
                    c.dialogue_id = None       # tick 末清空（02 §3.3）
                    session.add(c)
                world.clear_tick_scratch()
                await world.persist(session, events)

    # ── 决策并发 ──

    async def _decide_all(self, world, deciders, stim_map) -> dict:
        """并发决策。**必须**在写事务之外调用（决策走 LLM，是长尾操作）。

        每个角色自带一次短读会话自取上下文，避免并发共享同一 session。
        """
        if not deciders:
            return {}
        sem = asyncio.Semaphore(max(1, settings.max_concurrent_llm))
        results: dict[str, Any] = {}

        async def _one(c):
            async with sem:
                # 每次决策用一条独立的**短读**连接自取上下文（记忆检索 / 关系 /
                # 在场角色）。若共享 session，并发协程会在同一事务上交错，
                # 且会把读事务拖到整轮 LLM 结束。
                try:
                    async with session_scope() as s:
                        d = await char_agent.decide(
                            s, world, c, stim_map.get(c.id, []),
                            timeout=float(settings.llm_timeout),
                        )
                except Exception:
                    log.exception("decide 会话异常 %s", c.name)
                    d = None
                if d is not None:
                    results[c.id] = d
                c.last_decided_tick = world.tick

        try:
            await asyncio.wait_for(
                asyncio.gather(*(_one(c) for c in deciders), return_exceptions=True),
                timeout=float(settings.llm_timeout) * 2.5,
            )
        except asyncio.TimeoutError:
            log.warning("决策阶段整体超时，未完成者走日程")
        return results

    # ── 共处 ──

    async def _co_presence(self, session, world) -> None:
        talked: set[tuple[str, str]] = set()
        for d in world.characters.values():
            pass
        by_loc: dict[str, list] = {}
        for c in world.awake_characters():
            by_loc.setdefault(c.location_id, []).append(c)
        for occ in by_loc.values():
            if len(occ) < 2:
                continue
            for i, x in enumerate(occ):
                for y in occ[i + 1 :]:
                    rel = await mem_mod.ensure_relationship(session, x.id, y.id)
                    rel.familiarity = min(1.0, rel.familiarity + 0.02)
                    session.add(rel)
                    rel2 = await mem_mod.ensure_relationship(session, y.id, x.id)
                    rel2.familiarity = min(1.0, rel2.familiarity + 0.02)
                    session.add(rel2)

    # ── 反思 ──

    async def _reflect_all(self, session, world) -> None:
        from ..llm.gateway import get_llm
        from ..schemas.domain import Reflection

        llm = get_llm()
        for c in world.awake_characters():
            rows = (
                await session.exec(
                    select(Memory)
                    .where(col(Memory.character_id) == c.id, col(Memory.day) == world.day)
                    .order_by(col(Memory.tick).desc())
                    .limit(120)
                )
            ).all()
            pool = mem_mod.day_memories_for_reflection(list(rows), world.day)
            if len(pool) < 3:
                continue

            # 当日最高 whisper 未消费 → 反思要包含它
            text = ""
            if not llm.offline:
                ctx = {
                    "me": {"name": c.name, "persona_brief": _brief(c)},
                    "day_label": world.time_label(),
                    "memories": mem_mod.format_for_prompt(pool, decompose_tick),
                    "relation_changes": await _relation_changes(session, world, c),
                }
                try:
                    out = await llm.json(
                        "strong" if c.kind == "player" else "cheap",
                        "reflect", ctx, Reflection, max_tokens=600,
                    )
                    for ins in out.insights[:3]:
                        ok, _ = __import__(
                            "app.sim.filter", fromlist=["check_text"]
                        ).check_text(ins.text)
                        if not ok:
                            continue
                        imp = max(5, min(10, ins.importance))
                        mem_mod.add(session, character_id=c.id, tick=world.tick, day=world.day,
                                    kind="reflection", text=ins.text[:80], importance=imp)
                        world.emit(
                            make_event("reflection", world.tick, world.day,
                                       {"character_id": c.id, "text": ins.text[:80]},
                                       actor_id=c.id)
                        )
                        text = ins.text
                except Exception as exc:
                    log.info("反思失败 %s: %s", c.name, exc)

    # ── admin ──

    async def fast_forward(self, ticks: int) -> int:
        world = self.world or await get_world()
        world.state.admin_override = "fast_forward"
        world.state.remaining_ticks = max(1, ticks)
        return world.state.remaining_ticks

    async def pause(self) -> str:
        world = self.world or await get_world()
        world.state.admin_override = "paused"
        return "paused"

    async def resume(self) -> str:
        world = self.world or await get_world()
        world.state.admin_override = None
        world.state.remaining_ticks = 0
        return decide_mode(bus.subscriber_count(), None, 0)


ticker = Ticker()


def reset_ticker() -> None:
    """测试用：同步停掉并丢弃 ticker 单例。

    不 await `stop()`（本函数在同步 fixture 里调用）；直接 cancel 任务并置位停止事件。
    """
    global ticker
    try:
        ticker._stop.set()  # noqa: SLF001
        ticker.running = False
        if ticker._task is not None:  # noqa: SLF001
            ticker._task.cancel()  # noqa: SLF001
            ticker._task = None  # noqa: SLF001
    except Exception:
        pass
    ticker = Ticker()


# ─────────────────────────── 工具 ───────────────────────────


def wake_all(world: World, session) -> None:
    for c in world.characters.values():
        if c.kind == "system":
            continue
        c.is_asleep = False
        c.energy = 100
        c.last_observation_key = ""
        session.add(c)


def sleep_all(world: World, session) -> None:
    for c in world.characters.values():
        if c.kind == "system":
            continue
        c.is_asleep = True
        c.activity = "睡着了"
        session.add(c)


def _brief(c) -> str:
    from ..schemas.domain import PersonaFile

    try:
        return PersonaFile.model_validate(c.persona).brief()
    except Exception:
        return f"{c.name}：一位同学。"


async def _relation_changes(session, world, c) -> list[str]:
    from ..models import Relationship

    rows = (
        await session.exec(
            select(Relationship)
            .where(col(Relationship.from_id) == c.id, col(Relationship.affinity_delta_today) != 0)
            .order_by(col(Relationship.affinity_delta_today).desc())
            .limit(3)
        )
    ).all()
    return [
        f"{world.display_name(r.to_id)}: {'+' if r.affinity_delta_today > 0 else ''}{r.affinity_delta_today}"
        for r in rows
    ]


async def warmup_apply(session, world) -> int:
    """注入 warmup.json 剧本刺激（仅 DEV/admin，08 §7）。"""
    from ..models import Whisper
    from ..seeds import warmup

    applied = 0
    for item in warmup():
        if int(item.get("tick", -1)) != world.tick:
            continue
        cid = item.get("character_id")
        char = world.get_character(cid)
        if char is None:
            continue
        if item.get("type") == "whisper":
            from ..models import new_id

            w = Whisper(id=new_id("w_"), character_id=cid, user_id=char.user_id or "sys",
                        text=str(item.get("text", ""))[:80], tick=world.tick, day=world.day)
            session.add(w)
            char.pending_whisper_id = w.id
            session.add(char)
            applied += 1
    return applied


__all__ = ["Ticker", "ticker", "decide_mode", "tick_period", "wake_all", "sleep_all", "warmup_apply"]
