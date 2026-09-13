"""api 包入口。"""

from . import admin, auth, avatar, health, persona, stream, wall, world  # noqa: F401

__all__ = ["admin", "auth", "avatar", "health", "persona", "stream", "wall", "world"]
