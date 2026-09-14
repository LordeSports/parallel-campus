"""健康检查（spec/03 §9）。"""

from __future__ import annotations

from fastapi import APIRouter

from .. import __version__
from ..config import settings
from ..schemas.views import HealthView
from ..sim.world import get_world
from ..version import build_fingerprint
from .deps import OptionalUser, SessionDep

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthView)
async def health(session: SessionDep, user: OptionalUser) -> HealthView:
    try:
        world = await get_world()
        tick = world.tick
        mode = world.state.speed_mode
    except Exception:
        tick = 0
        mode = "idle"
    return HealthView(
        status="ok",
        version=__version__,
        build=build_fingerprint(),
        tick=tick,
        mode=mode,
        dev_mode=settings.dev_mode,
    )


__all__ = ["router"]
