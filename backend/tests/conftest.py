"""pytest 全局夹具：内存 SQLite、mock LLM、mock 知乎。

设计原则：
- 不依赖网络，不依赖真实 API key。
- 每个测试拿到独立的 in-memory SQLite（用 StaticPool 保持连接复用）。
- LLM 默认 offline（返回兜底），需要时用 `fake_llm` 注入脚本化响应。
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any, Callable

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# 测试环境变量必须在 import app.* 之前设好
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("SESSION_SECRET", "test-session-secret")
os.environ.setdefault("TOKEN_ENC_KEY", "")
os.environ.setdefault("ADMIN_TOKEN", "test-admin")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("LLM_BASE_URL", "")
os.environ.setdefault("ZHIHU_SECRET", "")


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture
async def engine(tmp_path):
    """每个测试独立的临时文件 SQLite，与生产引擎同配置（NullPool + IMMEDIATE）。

    必须用 `NullPool`（而非 `StaticPool`）：`BEGIN IMMEDIATE` 挂在 SQLAlchemy 的
    `begin` 事件上，复用同一条连接时上一条连接已留下未结束的隐式事务，
    第二次 begin 会报 "cannot start a transaction within a transaction"，
    被吞掉后测试会静默退化成兜底路径——比慢更糟。
    """
    from sqlalchemy.pool import NullPool

    from app import db as db_mod

    db_file = tmp_path / "test.db"
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{db_file.as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    # 与 app.db._sqlite_engine 完全一致：PRAGMA 在 connect 事件里设，
    # 事务由 begin 事件显式发起（默认 DEFERRED，写会话走 IMMEDIATE）
    event.listen(eng.sync_engine, "connect", db_mod._autocommit_off)
    event.listen(eng.sync_engine, "begin", db_mod._begin)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    prev = db_mod.peek_engine()
    db_mod.set_engine(eng)
    try:
        yield eng
    finally:
        db_mod.set_engine(prev)
        await eng.dispose()


@pytest_asyncio.fixture
async def session(engine) -> AsyncSession:
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s


@pytest.fixture(autouse=True)
def _reset_singletons():
    """每个测试结束后清掉 llm / world / ticker 单例与缓存。

    `app.sim.world._world` 是**进程级全局**：不清掉的话，下一个测试
    （即使换了新的临时库）仍会拿到上一个测试的内存世界，表现为顺序相关的
    诡异失败（如「角色还停在旧地点」）。因此这里在**前后**都重置一次。
    """
    _purge()

    yield

    _purge()


def _purge() -> None:
    try:
        from app.sim import world as world_mod
        world_mod.set_world(None)
    except Exception:
        pass
    try:
        from app.llm.gateway import reset_llm
        reset_llm()
    except Exception:
        pass
    try:
        from app.sim.ticker import reset_ticker
        reset_ticker()
    except Exception:
        pass
    try:
        from app.sim import stimuli as stim_mod
        stim_mod.clear_cache()
    except Exception:
        pass


# ─────────────────────── LLM ───────────────────────


class ScriptedLLM:
    """按模板名返回预设 JSON 的假 LLM。

    用法：
        llm = ScriptedLLM({"decide": {...}, "dialogue": {...}})
        未命中模板时返回 `default`。
    """

    def __init__(self, responses: dict[str, Any] | None = None, default: Any = None):
        self.responses = responses or {}
        self.default = default
        self.calls: list[dict[str, Any]] = []
        self.offline = False
        self.degraded = False
        self.llm_fail_streak = 0

    async def json(self, tier, template, ctx, schema, **kwargs):  # noqa: ANN001
        self.calls.append(
            {"tier": tier, "template": template, "ctx": ctx, "schema": schema, **kwargs}
        )
        payload = self.responses.get(template, self.default)
        if payload is None:
            from app.errors import LlmOutputError

            raise LlmOutputError(f"no scripted response for {template}")
        if callable(payload):
            payload = payload(ctx)
        if hasattr(schema, "model_validate"):
            return schema.model_validate(payload)
        return payload

    async def text(self, tier, template, ctx, **kwargs):  # noqa: ANN001
        self.calls.append({"tier": tier, "template": template, "ctx": ctx, **kwargs})
        payload = self.responses.get(template, self.default)
        return payload if isinstance(payload, str) else ""

    async def aclose(self) -> None:
        return None


@pytest.fixture
def fake_llm() -> Callable[..., ScriptedLLM]:
    from app.llm import gateway

    def _install(responses: dict[str, Any] | None = None, default: Any = None) -> ScriptedLLM:
        llm = ScriptedLLM(responses, default)
        gateway.set_llm(llm)
        return llm

    return _install


@pytest.fixture
def offline_llm(fake_llm) -> ScriptedLLM:
    """不提供任何脚本 → 所有生成走兜底。"""
    return fake_llm({})


# ─────────────────────── 世界 ───────────────────────


@pytest_asyncio.fixture
async def world(engine, offline_llm):
    """一个已种子化的干净世界（7 NPC + 1 系统角色），并已生成当日日程。

    `load_or_seed` 只落角色与事件；日程在 06:00 的 `env.new_day` 里生成。
    测试里直接套用默认模板，让 `schedule_of()` 立即可用。

    **必须显式依赖 `engine`**：否则 `session_scope()` 会拿到进程级的生产引擎
    （`data/pc.db`），测试会读写真实数据库——既能被上一次跑测试留下的
    `world_state`（如 day=36）污染而误报失败，也会反过来弄脏开发数据。

    **不依赖 `session` fixture**：内部全程用 `session_scope()` 短连接，
    避免与 `Ticker.tick()` 自己的连接争锁（SQLite "database is locked"）。
    """
    from app.db import session_scope
    from app.seeds import default_schedule
    from app.sim.world import World

    w = await World.load_or_seed()
    sched = default_schedule(1).model_dump()
    async with session_scope() as s:
        for c in w.characters.values():
            if c.kind == "system":
                continue
            c.schedule = sched
            c.schedule_day = w.day
            await s.merge(c)
        await s.commit()
    await w.reload_characters()
    return w


@pytest.fixture
def zhihu_fixtures() -> Path:
    return BACKEND / "app" / "seeds" / "mock_zhihu"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
