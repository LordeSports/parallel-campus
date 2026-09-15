"""档位与间隔：已移除「自动倍速」，间隔是固定的显式档位。"""
from app.config import settings
from app.sim.ticker import decide_mode, tick_period


def test_online_uses_configured_interval(monkeypatch):
    monkeypatch.setattr(settings, "tick_seconds_online", 20)
    assert tick_period("online") == 20


def test_idle_uses_configured_interval(monkeypatch):
    monkeypatch.setattr(settings, "tick_seconds_idle", 300)
    assert tick_period("idle") == 300


def test_paused_and_fast_forward_do_not_wait():
    assert tick_period("paused") == 0
    assert tick_period("fast_forward") == 0


def test_interval_does_not_depend_on_observers(monkeypatch):
    """回归：旧实现按观众数在 20~180 秒之间自适应（自动档），现已删除。"""
    monkeypatch.setattr(settings, "tick_seconds_online", 20)
    monkeypatch.setattr(settings, "tick_seconds_idle", 300)
    assert tick_period("online") == 20
    assert tick_period("idle") == 300
    # 签名里不再有 observers —— 传了会直接 TypeError
    import pytest

    with pytest.raises(TypeError):
        tick_period("online", 5)  # type: ignore[call-arg]


def test_decide_mode_is_explicit():
    assert decide_mode("paused", 0) == "paused"
    assert decide_mode("online", 0) == "online"
    assert decide_mode("idle", 0) == "idle"
    assert decide_mode("fast_forward", 10) == "fast_forward"
    # 剩余步数 > 0 时一律快进（即使 override 被清掉）
    assert decide_mode(None, 5) == "fast_forward"
    # 未指定档位（启动初值）默认慢速，不再按观众数决定
    assert decide_mode(None, 0) == "idle"


def test_decide_mode_ignores_unknown_override():
    assert decide_mode("auto", 0) == "idle"      # 已删除的档位不再被识别
    assert decide_mode("bogus", 0) == "idle"
