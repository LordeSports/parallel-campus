from app.config import settings
from app.sim.ticker import tick_period


def test_auto_speed_accelerates_without_observers(monkeypatch):
    monkeypatch.setattr(settings, "tick_seconds_online", 20)
    monkeypatch.setattr(settings, "tick_seconds_idle", 300)
    assert tick_period("idle", 0) == 5


def test_auto_speed_slows_as_observers_increase(monkeypatch):
    monkeypatch.setattr(settings, "tick_seconds_online", 20)
    assert tick_period("online", 1) == 20
    assert tick_period("online", 3) == 40
    assert tick_period("online", 20) == 180


def test_fixed_admin_idle_keeps_configured_interval(monkeypatch):
    monkeypatch.setattr(settings, "tick_seconds_idle", 300)
    assert tick_period("idle") == 300
