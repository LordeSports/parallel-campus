"""路由注册（main.py 调用）。

所有 API 挂在 `/api` 前缀下；`stream` 与 `health` 无子前缀。
"""

from __future__ import annotations

from fastapi import APIRouter, FastAPI

from .api import admin, admin_console, auth, avatar, health, persona, stream, wall, world


def register_routers(app: FastAPI) -> None:
    api = APIRouter(prefix="/api")
    api.include_router(auth.router)
    api.include_router(persona.router)
    api.include_router(world.router)
    api.include_router(wall.router)
    api.include_router(avatar.router)
    api.include_router(admin.router)
    api.include_router(admin_console.router)
    api.include_router(stream.router)
    api.include_router(health.router)
    app.include_router(api)


__all__ = ["register_routers"]
