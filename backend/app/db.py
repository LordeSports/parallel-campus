"""数据库引擎、会话与单写者锁。

约束（spec/04 §1）：uvicorn `--workers 1`；所有写库经 `db.write_lock`；
一个 tick 的落库在末尾一次事务提交。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings

log = logging.getLogger("pc.db")

# 全局单写者锁：整个进程只有一把，保证 tick 落库与 API 写操作串行
write_lock = asyncio.Lock()

_engine: AsyncEngine | None = None

# WAL 允许读写并行，但 SQLite 仍只允许一个写事务。
# NullPool 不复用空闲连接；是否持有写锁取决于事务模式和会话生命周期。
_SQLITE_CONNECT_ARGS = {"check_same_thread": False, "timeout": 30}
_SQLITE_PRAGMAS = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA busy_timeout=30000",
    "PRAGMA foreign_keys=ON",
)


def apply_sqlite_pragmas(conn) -> None:
    """对同步连接对象逐一执行 PRAGMA（不依赖 sqlalchemy.text）。"""
    from sqlalchemy import text

    for stmt in _SQLITE_PRAGMAS:
        conn.execute(text(stmt))


def _autocommit_off(dbapi_conn, _rec) -> None:
    """连接建立时：关闭 DBAPI 隐式事务 + 打 PRAGMA。

    顺序很重要——`isolation_level = None` 让 sqlite3 不再自动 `BEGIN`，
    这样下面这些 PRAGMA（`synchronous` 尤其）才不会被「事务内不可改」拒掉。
    之后事务完全由 SQLAlchemy 的 `begin` 事件显式驱动（见 `_begin`）。
    """
    dbapi_conn.isolation_level = None
    for stmt in _SQLITE_PRAGMAS:
        dbapi_conn.execute(stmt)


def _begin(conn) -> None:
    """SQLAlchemy 事务起步：默认 DEFERRED，只有「写事务」才 IMMEDIATE。

    **为什么不能一律 IMMEDIATE**：`begin` 事件对**每个**事务都会触发，包括
    纯 SELECT 的短事务。若读事务也拿 `BEGIN IMMEDIATE`，它就抢下写锁并一直
    持到 rollback——其他连接（Ticker 落库、其他请求）全部被挡在
    `busy_timeout` 上死等，表现为「每 tick 卡 30 秒然后 database is locked」。

    **为什么写事务必须 IMMEDIATE**：SQLite 默认的 deferred 事务在「先读后写」
    时要把共享锁升级为排他锁；升级失败会**立即**抛 `database is locked`，
    且不受 `busy_timeout` 保护。以 IMMEDIATE 起步可先拿写锁，冲突时归一为
    「等待」，由 busy_timeout 兜住。

    判定方式：SQLAlchemy 在 `begin` 事件上把 `conn` 包成
    `Connection`；我们用一个 Connection 级的标记位（`info`）来区分——写事务
    由 `write_session()` 显式置位。读事务保持 deferred。

    事务统一由此事件开启，调用方不要重复发 BEGIN。
    """
    if conn.info.get("pc_write_txn"):
        conn.exec_driver_sql("BEGIN IMMEDIATE")
    else:
        conn.exec_driver_sql("BEGIN")


def _prepare_sqlite_dir(url: str) -> None:
    path = settings.sqlite_path()
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)


def _sqlite_engine(url: str) -> AsyncEngine:
    """SQLite 引擎：WAL + NullPool，按会话区分读写事务。"""
    from sqlalchemy import event

    engine = create_async_engine(
        url,
        echo=False,
        future=True,
        poolclass=NullPool,
        connect_args=dict(_SQLITE_CONNECT_ARGS),
    )
    event.listen(engine.sync_engine, "connect", _autocommit_off)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _prepare_sqlite_dir(settings.database_url)
        if settings.database_url.startswith("sqlite"):
            _engine = _sqlite_engine(settings.database_url)
        else:
            _engine = create_async_engine(
                settings.database_url, echo=False, future=True
            )
    return _engine


def set_engine(engine: AsyncEngine | None) -> None:
    """测试用：注入内存/临时引擎。"""
    global _engine
    _engine = engine


def peek_engine() -> AsyncEngine | None:
    """测试用：读取当前引擎但不创建。"""
    return _engine


async def init_db() -> None:
    """建表 + 增量补列。

    SQLite 的 PRAGMA 已在 `_autocommit_off`（引擎 `connect` 事件）里逐连接设好，
    这里不再重复——`synchronous` 在事务内设置会被 SQLite 拒绝。
    """
    engine = get_engine()
    # 确保所有模型已注册到 metadata
    from . import models  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


# 已上线表的新增列（create_all 只建缺失的表，**不会**给旧表补列）。
# 都是「可空或带默认值」的加法列，重复执行安全。
_ADDITIVE_COLUMNS: tuple[tuple[str, str, str], ...] = (
    # (表名, 列名, 列定义)
    ("users", "role", "VARCHAR(10) DEFAULT 'player'"),
)


def _add_missing_columns(conn) -> None:  # noqa: ANN001
    """给已存在的表补上新增列；已存在则跳过。

    老库（用户线上那份 `pc.db`）缺这些列时，读取会直接报
    `no such column`，所以启动时补一次是最省事的做法。
    """
    from sqlalchemy import text

    for table, column, ddl in _ADDITIVE_COLUMNS:
        exists = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table},
        ).first()
        if exists is None:
            continue  # 新库由 create_all 建好，列已存在
        cols = {row[1] for row in conn.execute(text(f'PRAGMA table_info("{table}")'))}
        if column in cols:
            continue
        conn.execute(text(f'ALTER TABLE "{table}" ADD COLUMN {column} {ddl}'))
        log.info("已为表 %s 补列 %s", table, column)


async def dispose_db() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """独立会话（默认 DEFERRED 事务，适合只读或零散写）。"""
    engine = get_engine()
    async with AsyncSession(engine, expire_on_commit=False) as session:
        yield session


@asynccontextmanager
async def _connection_session(*, write: bool) -> AsyncIterator[AsyncSession]:
    """在 autobegin 前设置事务模式，连接归还前清除标记。"""
    engine = get_engine()
    async with engine.connect() as conn:
        conn.info["pc_write_txn"] = write
        try:
            async with AsyncSession(bind=conn, expire_on_commit=False) as session:
                yield session
        finally:
            if not conn.invalidated:
                conn.info.pop("pc_write_txn", None)


@asynccontextmanager
async def write_session() -> AsyncIterator[AsyncSession]:
    """写事务正常退出时提交；运行时调用方需先获取 write_lock。"""
    async with _connection_session(write=True) as session:
        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise


@asynccontextmanager
async def _request_session(*, write: bool) -> AsyncIterator[AsyncSession]:
    """请求由路由显式提交，退出时回滚尚未提交的数据。"""
    lock_context = write_lock if write else _noop_async_context()
    async with lock_context:
        async with _connection_session(write=write) as session:
            yield session


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI 依赖：按请求类型创建读或写会话。

    只读请求使用 deferred 事务，避免普通 GET 抢占 SQLite 写锁。会修改数据的
    HTTP 方法在进程内串行化，并以 ``BEGIN IMMEDIATE`` 开始事务，保证「先读后写」
    时不会因 deferred 锁升级失败而直接得到 ``database is locked``。
    """
    is_write = request.method.upper() not in {"GET", "HEAD", "OPTIONS"}
    async with _request_session(write=is_write) as session:
        yield session


async def get_write_session() -> AsyncIterator[AsyncSession]:
    """显式写请求依赖，用于 OAuth GET 回调等有写入语义的端点。"""
    async with _request_session(write=True) as session:
        yield session


@asynccontextmanager
async def _noop_async_context() -> AsyncIterator[None]:
    yield None


__all__ = [
    "get_engine",
    "set_engine",
    "peek_engine",
    "init_db",
    "dispose_db",
    "session_scope",
    "write_session",
    "get_session",
    "get_write_session",
    "write_lock",
    "apply_sqlite_pragmas",
    "_autocommit_off",
    "_begin",
]
