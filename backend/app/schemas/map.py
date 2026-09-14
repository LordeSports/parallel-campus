"""可编辑校园地图的输入 / 视图 schema。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .views import View

MapObjectKind = Literal["ground", "building", "prop"]

# 每类对象的变体白名单（spec 无约束，属需求演进；见 docs 的地图章节）
GROUND_VARIANTS = ("grass", "dirt", "water", "field_track", "plaza", "sand")
BUILDING_VARIANTS = ("main", "tower", "hall", "canteen", "dorm", "shop")
PROP_VARIANTS = ("tree", "pine", "rock", "bench", "lamp", "flower", "board")

MAX_OBJECTS = 1200
MAX_MAP_TILES = 128


class MapObjectView(View):
    """地图对象（读）。坐标单位为 tile。"""

    id: str
    kind: MapObjectKind
    variant: str
    tx: float
    ty: float
    tw: float
    th: float
    height: float = 0.0
    layer: int = 0
    name: str = ""
    location_id: str | None = None
    props: dict[str, Any] = Field(default_factory=dict)


class CampusMapView(View):
    """整图（读）。玩家端只在 `version` 变化时重建。"""

    version: int
    cols: int
    rows: int
    title: str = "平行校园"
    updated_at: datetime | None = None
    updated_by: str | None = None
    objects: list[MapObjectView] = Field(default_factory=list)


class MapObjectInput(BaseModel):
    """地图对象（写）。`id` 可省略 → 服务端分配。"""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, max_length=32)
    kind: MapObjectKind
    variant: str = Field(min_length=1, max_length=24)
    tx: float = Field(ge=-4, le=MAX_MAP_TILES, allow_inf_nan=False)
    ty: float = Field(ge=-4, le=MAX_MAP_TILES, allow_inf_nan=False)
    tw: float = Field(default=1, ge=0.25, le=64, allow_inf_nan=False)
    th: float = Field(default=1, ge=0.25, le=64, allow_inf_nan=False)
    height: float = Field(default=0, ge=0, le=16, allow_inf_nan=False)
    layer: int = Field(default=0, ge=-10, le=100)
    name: str = Field(default="", max_length=24)
    location_id: str | None = Field(default=None, max_length=32)
    props: dict[str, Any] = Field(default_factory=dict)

    @field_validator("variant")
    @classmethod
    def _known_variant(cls, v: str, info) -> str:
        """变体必须在白名单内（按 kind 分表）。未知变体退回该类的首个变体。"""
        kind = (info.data or {}).get("kind")
        table = {
            "ground": GROUND_VARIANTS,
            "building": BUILDING_VARIANTS,
            "prop": PROP_VARIANTS,
        }.get(str(kind), ())
        if table and v not in table:
            raise ValueError(f"未知的 {kind} 变体: {v}")
        return v

    @field_validator("props")
    @classmethod
    def _props_small(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(v) > 24:
            raise ValueError("props 最多 24 个键")
        return v


class MapSaveRequest(BaseModel):
    """整图保存请求。"""

    model_config = ConfigDict(extra="forbid")

    objects: list[MapObjectInput] = Field(default_factory=list, max_length=MAX_OBJECTS)
    title: str | None = Field(default=None, max_length=24)

    @model_validator(mode="after")
    def _shapes_within_grid(self) -> "MapSaveRequest":
        # 至少要有地面，否则地图一片空白容易是误操作
        if self.objects and not any(o.kind == "ground" for o in self.objects):
            raise ValueError("地图至少需要一个地面块")
        return self


__all__ = [
    "MapObjectKind", "GROUND_VARIANTS", "BUILDING_VARIANTS", "PROP_VARIANTS",
    "MAX_OBJECTS", "MapObjectView", "CampusMapView", "MapObjectInput", "MapSaveRequest",
]
