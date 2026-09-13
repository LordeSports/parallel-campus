"""验证写会话真的落库（回归「commit 退化为 rollback」这个坑）。

用法：python scripts/verify_write.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("SESSION_SECRET", "vw")
os.environ.setdefault("ADMIN_TOKEN", "vw")
os.environ.setdefault("LLM_API_KEY", "")


async def main() -> int:
    import tempfile

    from sqlalchemy import event, text
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from sqlmodel import SQLModel

    from app import db as db_mod
    from app import models  # noqa: F401
    from app.models import Post

    tmp = Path(tempfile.mkdtemp())
    eng = create_async_engine(
        f"sqlite+aiosqlite:///{(tmp / 'v.db').as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(eng.sync_engine, "connect", db_mod._autocommit_off)
    event.listen(eng.sync_engine, "begin", db_mod._begin)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    db_mod.set_engine(eng)

    ok = True

    # ① write_session 里 add + commit 必须真正落库
    async with db_mod.write_session() as s:
        s.add(Post(id="p_test_1", board="wall", text="写会话测试", tick=1, author_id=None))
        await s.commit()

    async with eng.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM posts"))).scalar_one()
    print(f"{'✓' if n == 1 else '✗'} write_session 落库：posts={n}")
    ok &= n == 1

    # ② session_scope（deferred）里的写也能落库
    async with db_mod.session_scope() as s:
        s.add(Post(id="p_test_2", board="wall", text="读会话写测试", tick=2, author_id=None))
        await s.commit()

    async with eng.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM posts"))).scalar_one()
    print(f"{'✓' if n == 2 else '✗'} session_scope 落库：posts={n}")
    ok &= n == 2

    # ③ 回滚不落库
    async with db_mod.write_session() as s:
        s.add(Post(id="p_test_3", board="wall", text="应被回滚", tick=3, author_id=None))
        await s.rollback()

    async with eng.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM posts"))).scalar_one()
    print(f"{'✓' if n == 2 else '✗'} rollback 生效：posts={n}")
    ok &= n == 2

    # ④ 并发写不互相阻塞（两次 write_session 交替）
    import time

    t0 = time.perf_counter()
    for i in range(10):
        async with db_mod.write_session() as s:
            s.add(Post(id=f"p_c{i}", board="wall", text=f"并发 {i}", tick=10 + i, author_id=None))
            await s.commit()
    dt = time.perf_counter() - t0
    async with eng.connect() as conn:
        n = (await conn.execute(text("SELECT COUNT(*) FROM posts"))).scalar_one()
    print(f"{'✓' if n == 12 else '✗'} 10 次串行写：posts={n}，耗时 {dt:.2f}s（应 < 5s）")
    ok &= n == 12 and dt < 5

    await eng.dispose()
    print("\n结果：", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
