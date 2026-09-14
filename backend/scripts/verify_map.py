"""验证可编辑校园地图：默认种子幂等 / 读取 / 保存 / 地点绑定覆盖。"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("DEV_MODE", "true")
os.environ.setdefault("SESSION_SECRET", "map-check-secret")
os.environ.setdefault("TOKEN_ENC_KEY", "")
os.environ.setdefault("ADMIN_TOKEN", "map-check-admin")
os.environ.setdefault("LLM_API_KEY", "")
os.environ.setdefault("ZHIHU_SECRET", "")

DB = Path(f"D:/tmp/map_verify_{os.getpid()}.db")

LOCATION_IDS = {
    "teaching_a", "library", "club_room", "canteen",
    "field", "lakeside", "dorm", "milktea",
}


async def main() -> int:
    DB.parent.mkdir(parents=True, exist_ok=True)

    from sqlalchemy import event
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool
    from sqlmodel import SQLModel

    from app import campus_map, db as db_mod
    from app import models  # noqa: F401

    eng = create_async_engine(
        f"sqlite+aiosqlite:///{DB.as_posix()}",
        poolclass=NullPool,
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    event.listen(eng.sync_engine, "connect", db_mod._autocommit_off)
    event.listen(eng.sync_engine, "begin", db_mod._begin)
    async with eng.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    db_mod.set_engine(eng)

    ok = True
    from app.db import session_scope

    # ① 首次种子
    await campus_map.ensure_default_map()
    async with session_scope() as s:
        first = await campus_map.load_map(s)
    n1 = len(first["objects"])
    print(f"① 首次种子：version={first['version']} objects={n1} cols={first['cols']} rows={first['rows']}")
    ok &= n1 > 40 and first["version"] == 1

    # ② 幂等
    await campus_map.ensure_default_map()
    async with session_scope() as s:
        again = await campus_map.load_map(s)
    print(f"② 二次调用：objects={len(again['objects'])}（应不变）version={again['version']}")
    ok &= len(again["objects"]) == n1

    # ③ 8 个地点都被地图对象引用
    bound = {o["location_id"] for o in again["objects"] if o.get("location_id")}
    missing = LOCATION_IDS - bound
    print(f"③ 地点绑定：{len(bound & LOCATION_IDS)}/8  {'' if not missing else '缺失 ' + str(missing)}")
    ok &= not missing

    # ④ 各类对象齐全
    kinds: dict[str, int] = {}
    variants: dict[str, set[str]] = {}
    for o in again["objects"]:
        kinds[o["kind"]] = kinds.get(o["kind"], 0) + 1
        variants.setdefault(o["kind"], set()).add(o["variant"])
    print(f"④ 对象分布：{kinds}")
    for k, vs in sorted(variants.items()):
        print(f"    {k}: {sorted(vs)}")
    ok &= {"ground", "building", "prop"} <= set(kinds)
    ok &= {"water", "dirt", "grass"} <= variants.get("ground", set())
    ok &= {"tree", "rock", "bench"} <= variants.get("prop", set())

    # ⑤ 保存（整图替换）+ 版本递增
    v = await campus_map.save_map(
        [
            {"kind": "ground", "variant": "grass", "tx": 0, "ty": 0, "tw": 40, "th": 30, "layer": 0},
            {"kind": "building", "variant": "tower", "tx": 5, "ty": 5, "tw": 4, "th": 4,
             "height": 6, "layer": 20, "name": "测试楼", "location_id": "library"},
        ],
        "tester",
    )
    async with session_scope() as s:
        saved = await campus_map.load_map(s)
    print(f"⑤ 保存后：version={saved['version']} objects={len(saved['objects'])} "
          f"updated_by={saved['updated_by']}")
    ok &= v == 2 and len(saved["objects"]) == 2 and saved["updated_by"] == "tester"

    # ⑥ 非法输入应被 schema 拦住
    from pydantic import ValidationError
    from app.schemas.map import MapObjectInput, MapSaveRequest
    try:
        MapObjectInput(kind="building", variant="不存在的样式", tx=1, ty=1)
        print("⑥ 非法变体未被拦截 ✗")
        ok = False
    except ValidationError:
        print("⑥ 非法变体被正确拦截 ✓")

    await eng.dispose()
    print("\n结果：", "全部通过" if ok else "有失败项")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
