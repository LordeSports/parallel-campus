"""决策门控（spec/04 §5）。

排序：player 优先 → salience 降序 → 随机；截断 MAX_DECISIONS_PER_TICK。
每角色两次决策间隔 ≥1 tick。
"""

from __future__ import annotations

import logging
import random

from ..config import settings
from ..models import Character
from ..schemas.domain import Stimulus

log = logging.getLogger("pc.gate")


def should_decide(
    c: Character,
    stims: list[Stimulus],
    world,
    *,
    rng: random.Random | None = None,
) -> bool:
    r = rng or random
    top = max((s.salience for s in stims), default=0)
    high = top >= 8

    # 精力过低：非高显著刺激不决策，直接休息（04 §5）
    if c.energy < 20 and not high:
        return False

    if high:                                                          # 耳语/私信/被提及 必决策
        return True

    schedule = world.schedule_of(c)
    if schedule and schedule.at_boundary(world.minute):
        return True                                                   # 日程边界
    if stims and r.random() < settings.stimulus_decide_prob:
        return True                                                   # 有刺激 60%
    return r.random() < settings.spontaneity                           # 0.15


def select_deciders(
    awake: list[Character],
    stimuli: dict[str, list[Stimulus]],
    world,
    *,
    rng: random.Random | None = None,
) -> list[Character]:
    r = rng or random
    candidates: list[Character] = []
    for c in awake:
        if world.tick - c.last_decided_tick < 1:
            continue
        if should_decide(c, stimuli.get(c.id, []), world, rng=r):
            candidates.append(c)

    # 排序：player 优先 → salience 降序 → 随机
    candidates.sort(
        key=lambda c: (
            0 if c.kind == "player" else 1,
            -max((s.salience for s in stimuli.get(c.id, [])), default=0),
            r.random(),
        )
    )
    limit = settings.max_decisions_per_tick
    if len(candidates) > limit:
        log.debug("门控截断：%d → %d", len(candidates), limit)
    return candidates[:limit]


__all__ = ["should_decide", "select_deciders"]
