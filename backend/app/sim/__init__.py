"""sim 包入口 —— 逐模块显式导入，避免循环依赖。

注意：`ticker` 与 `world` 会互相引用，这里不提前 import ticker，由 main.py 显式加载。
"""

from . import bus, filter  # noqa: F401
from .bus import bus as event_bus  # noqa: F401
from .world import World, get_world, peek_world, reset_world, set_world  # noqa: F401

__all__ = [
    "bus", "filter", "event_bus",
    "World", "get_world", "peek_world", "reset_world", "set_world",
]
