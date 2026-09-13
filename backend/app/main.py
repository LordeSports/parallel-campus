"""主应用：FastAPI + lifespan。

启动顺序（09 §1 校验 → 建表 → seeds → 预置评委 → Ticker）。
"""

from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .config import BACKEND_DIR, settings
from .db import dispose_db, init_db, session_scope, write_lock
from .errors import AppError
from .routers import register_routers

log = logging.getLogger("pc.main")


def _setup_logging() -> None:
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format='{"ts":"%(asctime)s","lvl":"%(levelname)s","logger":"%(name)s","msg":%(message)s}',
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    from .admin_settings import load_runtime_settings, reload_clients

    load_runtime_settings()
    await reload_clients()
    settings.validate_runtime()
    log.info('{"event":"startup","env":"%s","dev_mode":%s}', settings.app_env, settings.dev_mode)

    await init_db()

    # seeds + 评委预置 + 首发世界
    from .seed_runtime import bootstrap_world

    await bootstrap_world()

    # Ticker
    from .sim.ticker import ticker

    await ticker.start()
    try:
        yield
    finally:
        await ticker.stop()
        from .llm.gateway import get_llm

        await get_llm().aclose()
        await dispose_db()
        log.info('{"event":"shutdown"}')


app = FastAPI(
    title="平行校园 Parallel Campus",
    version=__version__,
    description="知乎黑客松 2026 · 校园新锐季。公开数据 → 可编辑人格 → 分身在虚拟校园里替你先活一天。",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

if settings.dev_mode:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ─────────────────────────── 异常处理 ───────────────────────────


@app.exception_handler(AppError)
async def _app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    headers = {}
    if getattr(exc, "retry_after_seconds", None):
        headers["Retry-After"] = str(exc.retry_after_seconds)
    return JSONResponse(status_code=exc.status_code, content=exc.to_body(), headers=headers)


@app.exception_handler(RequestValidationError)
async def _validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    fields = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "")} for e in exc.errors()][:10]
    return JSONResponse(
        status_code=400,
        content={"error": {"code": "validation_error", "message": "参数校验失败",
                           "detail": {"fields": fields}}},
    )


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    log.exception("未处理异常 %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "internal_error", "message": "服务内部错误"}},
    )


# ─────────────────────────── 路由 ───────────────────────────

register_routers(app)


# ─────────────────────────── 前端静态（SPA fallback）───────────────────────────

_STATIC_CANDIDATES = [
    Path(settings.static_dir) if settings.static_dir else None,
    BACKEND_DIR.parent / "frontend" / "dist",
    BACKEND_DIR / "static",
]

_static_dir = next((p for p in _STATIC_CANDIDATES if p is not None and p.is_dir()), None)

if _static_dir is not None:
    assets = _static_dir / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"error": {"code": "not_found", "message": "接口不存在"}},
            )
        candidate = _static_dir / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        index = _static_dir / "index.html"
        if index.is_file():
            return FileResponse(str(index))
        return JSONResponse(
            status_code=404,
            content={"error": {"code": "not_found", "message": "前端未构建"}},
        )
else:
    @app.get("/", include_in_schema=False)
    async def _no_frontend():
        return JSONResponse(
            {
                "status": "ok",
                "hint": "前端尚未构建。开发时请运行 `npm run dev`（frontend/），或先 `npm run build`。",
                "api_docs": "/api/docs",
                "health": "/api/health",
            }
        )


__all__ = ["app"]
