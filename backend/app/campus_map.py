"""可编辑校园地图：默认布局生成 + 读写（等距手绘地图的数据层）。

**坐标系统**：全部用 tile 单位（浮点，允许半格），前端做等距投影：
    screenX = (tx - ty) * TILE_W / 2
    screenY = (tx + ty) * TILE_H / 2

**与 CampusLocation 的关系**：地点语义（角色归属 / 容量 / 氛围）仍由
`CampusLocation` + seeds 决定，本模块只负责**视觉层**。`building` 对象用
`location_id` 回指地点，前端据此把角色画到对应建筑门口。
管理员重画地图**不会**影响模拟逻辑。
"""

from __future__ import annotations

import random
from typing import Any

from sqlmodel import select

from .db import session_scope, write_session
from .models import CampusMap, CampusMapObject, now_utc

# 网格尺寸（tile）。40×30 在等距投影下约 2240×1120 px，信息密度合适。
MAP_COLS = 40
MAP_ROWS = 30

# 绘制层级：地面在下，摆件其次，建筑最上（同层内前端再按深度排序）
LAYER_GROUND = 0
LAYER_PROP = 10
LAYER_BUILDING = 20

GROUND_VARIANTS = ("grass", "dirt", "water", "field_track", "plaza", "sand")
BUILDING_VARIANTS = ("main", "tower", "hall", "canteen", "dorm", "shop")
PROP_VARIANTS = ("tree", "pine", "rock", "bench", "lamp", "flower", "board")


def _obj(
    kind: str,
    variant: str,
    tx: float,
    ty: float,
    tw: float,
    th: float,
    *,
    height: float = 0.0,
    layer: int = LAYER_GROUND,
    name: str = "",
    location_id: str | None = None,
    props: dict[str, Any] | None = None,
    sort_order: int = 0,
) -> dict[str, Any]:
    return {
        "kind": kind,
        "variant": variant,
        "tx": float(tx),
        "ty": float(ty),
        "tw": float(tw),
        "th": float(th),
        "height": float(height),
        "layer": int(layer),
        "name": name,
        "location_id": location_id,
        "props": props or {},
        "sort_order": int(sort_order),
    }


# ── 8 个地点的落位（tx/ty 为建筑左上角 tile）──
# 用一张「手绘草稿」式的布局：上排教学楼 / 图书馆 / 活动室，
# 中间一条主路，下排食堂 / 操场 / 湖 / 宿舍 / 奶茶店。
BUILDING_SPECS: list[dict[str, Any]] = [
    {"location_id": "teaching_a", "name": "教学楼 A", "variant": "main",    "tx": 4,  "ty": 5,  "tw": 8, "th": 6, "height": 4.0},
    {"location_id": "library",    "name": "图书馆",   "variant": "tower",   "tx": 16, "ty": 4,  "tw": 7, "th": 6, "height": 5.5},
    {"location_id": "club_room",  "name": "社团活动室", "variant": "hall",  "tx": 28, "ty": 6,  "tw": 6, "th": 5, "height": 3.0},
    {"location_id": "canteen",    "name": "第一食堂",  "variant": "canteen", "tx": 4,  "ty": 17, "tw": 7, "th": 5, "height": 3.0},
    {"location_id": "dorm",       "name": "宿舍区",   "variant": "dorm",    "tx": 3,  "ty": 24, "tw": 9, "th": 5, "height": 4.0},
    {"location_id": "milktea",    "name": "校门口奶茶店", "variant": "shop", "tx": 30, "ty": 24, "tw": 5, "th": 4, "height": 2.0},
]

# 露天地点用地面块表达（不建楼）
FIELD_SPEC = {"location_id": "field", "name": "操场", "tx": 13, "ty": 16, "tw": 9, "th": 8}
LAKE_SPEC = {"location_id": "lakeside", "name": "未名湖", "tx": 27, "ty": 16, "tw": 9, "th": 7}

# 土路：主干道 + 支路（宽 2 tile，带一点错位让它像手画的）
ROAD_SPECS: list[tuple[float, float, float, float]] = [
    (1, 13.0, 38, 2.0),    # 东西主干道
    (6, 11.0, 2.0, 2.5),   # 支路 → 教学楼
    (19, 10.0, 2.0, 3.5),  # 支路 → 图书馆
    (30, 11.0, 2.0, 2.5),  # 支路 → 活动室
    (6, 15.0, 2.0, 2.5),   # 支路 → 食堂
    (6, 22.0, 2.0, 2.5),   # 支路 → 宿舍
    (31, 15.0, 2.0, 2.5),  # 支路 → 湖边
    (20, 15.0, 2.0, 3.0),  # 支路 → 操场
    (31, 22.0, 2.0, 2.5),  # 支路 → 奶茶店
    (1, 20.0, 6.0, 1.5),   # 西侧小路
]


def build_default_objects() -> list[dict[str, Any]]:
    """生成默认校园布局。纯函数 + 固定随机种子 → 幂等，便于测试。"""
    rng = random.Random(20260913)
    objs: list[dict[str, Any]] = []

    # ① 草地打底
    objs.append(_obj("ground", "grass", 0, 0, MAP_COLS, MAP_ROWS,
                     layer=LAYER_GROUND, name="校园草地",
                     props={"tone": 0.0, "seed": 11}))

    # ② 水域 + 沙滩边
    objs.append(_obj("ground", "water", LAKE_SPEC["tx"] - 0.5, LAKE_SPEC["ty"] - 0.5,
                     LAKE_SPEC["tw"] + 1, LAKE_SPEC["th"] + 1,
                     layer=LAYER_GROUND + 1, name="未名湖",
                     location_id="lakeside", props={"seed": 23, "ripple": True}))
    objs.append(_obj("ground", "sand", LAKE_SPEC["tx"] - 1.5, LAKE_SPEC["ty"] - 1.5,
                     LAKE_SPEC["tw"] + 3, LAKE_SPEC["th"] + 3,
                     layer=LAYER_GROUND + 1, name="湖岸",
                     props={"seed": 29}))

    # ③ 操场（含跑道圈）
    objs.append(_obj("ground", "field_track", FIELD_SPEC["tx"], FIELD_SPEC["ty"],
                     FIELD_SPEC["tw"], FIELD_SPEC["th"],
                     layer=LAYER_GROUND + 2, name="操场",
                     location_id="field", props={"seed": 37}))

    # ④ 小广场（奶茶店门口 / 食堂门口）
    objs.append(_obj("ground", "plaza", 29.5, 23.0, 6, 6,
                     layer=LAYER_GROUND + 2, name="校门口", props={"seed": 41}))
    objs.append(_obj("ground", "plaza", 3.0, 16.0, 9, 7,
                     layer=LAYER_GROUND + 2, name="食堂前坪", props={"seed": 43}))

    # ⑤ 道路
    for idx, (tx, ty, tw, th) in enumerate(ROAD_SPECS):
        objs.append(_obj("ground", "dirt", tx, ty, tw, th,
                         layer=LAYER_GROUND + 3, name="",
                         props={"seed": 50 + idx}))

    # ⑥ 建筑（8 个地点里 6 个用楼房表达）
    for idx, spec in enumerate(BUILDING_SPECS):
        objs.append(_obj("building", spec["variant"], spec["tx"], spec["ty"],
                         spec["tw"], spec["th"], height=spec["height"],
                         layer=LAYER_BUILDING, name=spec["name"],
                         location_id=spec["location_id"],
                         props={"seed": 70 + idx, "hue": round(rng.uniform(-0.03, 0.03), 3)}))

    # ⑦ 摆件：湖边 6 张长椅（"六张长椅，最东边那张视野最好"）
    for i in range(6):
        tx = LAKE_SPEC["tx"] - 1.2
        ty = LAKE_SPEC["ty"] + 0.6 + i * 1.0
        objs.append(_obj("prop", "bench", tx, ty, 1.6, 0.7,
                         layer=LAYER_PROP, name="长椅",
                         location_id="lakeside", props={"seed": 100 + i, "facing": "east"}))

    # ⑧ 摆件：路灯光（沿主干道等距）
    for i, tx in enumerate(range(3, 38, 5)):
        objs.append(_obj("prop", "lamp", tx, 12.3, 0.8, 0.8,
                         layer=LAYER_PROP, props={"seed": 120 + i}))

    # ⑨ 摆件：树（湖边 + 操场旁 + 宿舍区，避开建筑与路面）
    tree_spots = [
        (2.0, 11.0), (13.0, 11.5), (25.0, 12.0), (36.5, 12.5),
        (2.5, 22.0), (12.5, 24.0), (25.0, 20.5), (36.0, 20.0),
        (26.5, 15.0), (35.5, 16.5), (14.5, 25.5), (21.0, 25.5),
        (9.0, 3.5), (24.0, 3.5), (0.8, 7.0), (37.0, 8.0),
    ]
    for i, (tx, ty) in enumerate(tree_spots):
        variant = "pine" if i % 3 == 2 else "tree"
        objs.append(_obj("prop", variant, tx, ty, 1.4, 1.4,
                         layer=LAYER_PROP, props={"seed": 140 + i}))

    # ⑩ 摆件：石块
    rock_spots = [(11.5, 13.5), (23.5, 13.0), (34.0, 24.5), (8.0, 26.5), (18.5, 22.0), (1.5, 15.5)]
    for i, (tx, ty) in enumerate(rock_spots):
        objs.append(_obj("prop", "rock", tx, ty, 1.0, 0.9,
                         layer=LAYER_PROP, props={"seed": 160 + i}))

    # ⑪ 摆件：花坛 + 公告板
    for i, (tx, ty) in enumerate([(5.0, 13.6), (20.0, 13.6), (33.0, 13.6)]):
        objs.append(_obj("prop", "flower", tx, ty, 1.2, 1.2,
                         layer=LAYER_PROP, props={"seed": 180 + i}))
    objs.append(_obj("prop", "board", 12.5, 13.2, 1.6, 0.7,
                     layer=LAYER_PROP, name="公告板",
                     location_id="teaching_a", props={"seed": 190}))

    return objs


# ─────────────────────────── 读写 ───────────────────────────


def _row_to_dict(row: CampusMapObject) -> dict[str, Any]:
    return {
        "id": row.id, "kind": row.kind, "variant": row.variant,
        "tx": row.tx, "ty": row.ty, "tw": row.tw, "th": row.th,
        "height": row.height, "layer": row.layer, "name": row.name,
        "location_id": row.location_id, "props": dict(row.props or {}),
        "sort_order": row.sort_order,
    }


async def ensure_default_map() -> None:
    """首次启动写入默认地图；已有则不动。幂等。"""
    async with session_scope() as session:
        meta = await session.get(CampusMap, 1)
        if meta is not None:
            return
    async with write_session() as session:
        meta = await session.get(CampusMap, 1)
        if meta is not None:
            return
        session.add(CampusMap(id=1, version=1, cols=MAP_COLS, rows=MAP_ROWS,
                              updated_at=now_utc(), updated_by="system"))
        for idx, obj in enumerate(build_default_objects()):
            session.add(CampusMapObject(id=f"mo_default_{idx:03d}", **{**obj, "sort_order": idx}))


async def load_map(session) -> dict[str, Any]:
    """读取地图（元信息 + 全部对象）。"""
    meta = await session.get(CampusMap, 1)
    if meta is None:
        # 兜底：库被动清空时也能返回可用地图（不写库）
        return {
            "version": 0, "cols": MAP_COLS, "rows": MAP_ROWS, "title": "平行校园",
            "updated_at": None, "updated_by": None,
            "objects": [{**o, "id": f"mo_default_{i:03d}"} for i, o in enumerate(build_default_objects())],
        }
    rows = (
        await session.exec(
            select(CampusMapObject).order_by(CampusMapObject.layer, CampusMapObject.sort_order)
        )
    ).all()
    return {
        "version": meta.version,
        "cols": meta.cols,
        "rows": meta.rows,
        "title": meta.title,
        "updated_at": meta.updated_at,
        "updated_by": meta.updated_by,
        "objects": [_row_to_dict(r) for r in rows],
    }


async def save_map(
    objects: list[dict[str, Any]], updated_by: str | None, title: str | None = None
) -> int:
    """整图覆盖保存，返回新版本号。

    整体替换（删旧插新）而不是 diff：地图对象数量小（默认 ~70 个），
    这样语义最简单，也避免 id 复用带来的幽灵对象。
    """
    async with write_session() as session:
        meta = await session.get(CampusMap, 1)
        if meta is None:
            meta = CampusMap(id=1, version=0, cols=MAP_COLS, rows=MAP_ROWS)
        if title:
            meta.title = title[:24]
        # 删除旧对象
        for row in (await session.exec(select(CampusMapObject))).all():
            await session.delete(row)
        # 插入新对象（保留传入 id；无 id 的分配新 id）
        for idx, obj in enumerate(objects):
            oid = str(obj.get("id") or "").strip() or None
            if not oid or not oid.startswith("mo_"):
                from .models import new_id as _new_id

                oid = _new_id("mo_")
            session.add(CampusMapObject(
                id=oid, sort_order=idx,
                kind=str(obj.get("kind", "prop")),
                variant=str(obj.get("variant", "tree")),
                tx=float(obj.get("tx", 0)), ty=float(obj.get("ty", 0)),
                tw=float(obj.get("tw", 1)), th=float(obj.get("th", 1)),
                height=float(obj.get("height", 0)), layer=int(obj.get("layer", LAYER_PROP)),
                name=str(obj.get("name") or "")[:24],
                location_id=(str(obj["location_id"]) if obj.get("location_id") else None),
                props=dict(obj.get("props") or {}),
            ))
        meta.version = (meta.version or 0) + 1
        meta.updated_at = now_utc()
        meta.updated_by = (updated_by or None)
        session.add(meta)
        return int(meta.version)


__all__ = [
    "MAP_COLS", "MAP_ROWS", "LAYER_GROUND", "LAYER_PROP", "LAYER_BUILDING",
    "GROUND_VARIANTS", "BUILDING_VARIANTS", "PROP_VARIANTS",
    "build_default_objects", "ensure_default_map", "load_map", "save_map",
]
