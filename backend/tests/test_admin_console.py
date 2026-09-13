"""管理员真实路由回归：权限隔离、持久化、世界操作和 Ticker 唤醒。"""
from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import pytest_asyncio

from app import admin_settings
from app.config import settings
from app.db import session_scope, write_session
from app.models import Character, LlmUsage, Memory, WorldEvent, WorldState
from app.security import ADMIN_COOKIE, SESSION_COOKIE, sign_session
from app.sim import world as world_mod
from app.sim.ticker import Ticker, decide_mode


@pytest_asyncio.fixture
async def admin_client(world, monkeypatch, tmp_path):
    from app.main import app
    from app.api import admin, admin_console
    from app.sim import ticker as ticker_mod

    for name in admin_settings.FIELDS:
        monkeypatch.setattr(settings, name, getattr(settings, name))
    monkeypatch.setattr(settings, "admin_username", "operator")
    monkeypatch.setattr(settings, "admin_password", "test-admin-password")
    monkeypatch.setattr(settings, "public_base_url", "http://testserver")
    monkeypatch.setattr(settings, "app_env", "dev")
    monkeypatch.setattr(settings, "admin_settings_file", str(tmp_path / "admin-settings.enc"))
    monkeypatch.setattr(settings, "admin_token", "test-admin-token")
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "https://llm.example.test/v1")
    world_mod.set_world(world)
    ticker = Ticker()
    ticker.world = world
    monkeypatch.setattr(ticker_mod, "ticker", ticker)
    monkeypatch.setattr(admin, "ticker", ticker)
    admin_console._login_failures.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        yield client
    await ticker.stop()


async def login(client):
    response = await client.post("/api/admin/login", json={"username": "operator", "password": "test-admin-password"})
    assert response.status_code == 200, response.text
    return response


@pytest.mark.asyncio
async def test_account_login_cookie_and_logout(admin_client, monkeypatch):
    info = await admin_client.get("/api/admin/session")
    assert info.json() == {"enabled": True, "authenticated": False, "username": None}
    response = await login(admin_client)
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/admin" in cookie
    assert (await admin_client.get("/api/admin/overview")).status_code == 200
    monkeypatch.setattr(settings, "admin_password", "rotated-password")
    assert (await admin_client.get("/api/admin/overview")).status_code == 401
    await admin_client.post("/api/admin/logout")
    assert ADMIN_COOKIE not in admin_client.cookies


@pytest.mark.asyncio
async def test_disabled_account_and_login_rate_limit(admin_client, monkeypatch):
    monkeypatch.setattr(settings, "admin_password", "")
    assert not (await admin_client.get("/api/admin/session")).json()["enabled"]
    assert (await admin_client.post("/api/admin/login", json={"username": "admin", "password": "admin"})).status_code == 403
    monkeypatch.setattr(settings, "admin_password", "test-admin-password")
    for _ in range(5):
        assert (await admin_client.post("/api/admin/login", json={"username": "operator", "password": "wrong"})).status_code == 401
    blocked = await admin_client.post("/api/admin/login", json={"username": "operator", "password": "test-admin-password"})
    assert blocked.status_code == 429 and blocked.headers["retry-after"] == "60"


@pytest.mark.asyncio
async def test_every_management_endpoint_denies_normal_cookie(admin_client):
    admin_client.cookies.set(SESSION_COOKIE, sign_session("operator"))
    routes = [("GET", "overview"), ("GET", "npcs"), ("GET", "locations"), ("GET", "scenes"), ("GET", "settings"),
              ("PUT", "simulation"), ("PUT", "clock"), ("PUT", "weather"), ("PUT", "settings"),
              ("POST", "npcs"), ("PUT", "npcs/npc_1"), ("POST", "scenes"), ("POST", "scenes/e_1/end"),
              ("POST", "pause"), ("POST", "resume"), ("POST", "fast-forward"), ("GET", "status")]
    for method, path in routes:
        response = await admin_client.request(method, f"/api/admin/{path}", json={} if method != "GET" else None)
        assert response.status_code in (401, 403), (method, path, response.text)
    header = {"X-Admin-Token": "test-admin-token"}
    assert (await admin_client.get("/api/admin/overview", headers=header)).status_code == 200


@pytest.mark.asyncio
async def test_cookie_writes_reject_cross_origin(admin_client):
    await login(admin_client)
    for headers in ({"Origin": "https://other.example"}, {"Sec-Fetch-Site": "cross-site"}):
        assert (await admin_client.post("/api/admin/pause", headers=headers)).status_code == 403
    assert (await admin_client.post("/api/admin/pause", headers={"Origin": "http://testserver"})).status_code == 200


@pytest.mark.asyncio
async def test_simulation_intervals_and_mode_persist(admin_client, world):
    await login(admin_client)
    response = await admin_client.put("/api/admin/simulation", json={"mode": "online", "tick_seconds_online": 2, "tick_seconds_idle": 60})
    assert response.status_code == 200, response.text
    assert decide_mode(0, world.state.admin_override, 0) == "online"
    async with session_scope() as session:
        row = await session.get(WorldState, 1)
        assert row.admin_override == "online"
    settings.tick_seconds_online = 20
    admin_settings.load_runtime_settings()
    assert settings.tick_seconds_online == 2
    assert (await admin_client.post("/api/admin/pause")).json()["mode"] == "paused"
    assert (await admin_client.post("/api/admin/resume")).status_code == 200
    assert world.state.admin_override is None
    assert (await admin_client.put("/api/admin/simulation", json={"mode": "online", "tick_seconds_online": 0})).status_code == 400


@pytest.mark.asyncio
async def test_time_jump_and_weather_persist_without_rewinding(admin_client, world):
    await login(admin_client)
    before = world.tick
    response = await admin_client.put("/api/admin/clock", json={"day": 2, "minute_of_day": 600})
    assert response.status_code == 200, response.text
    assert world.tick > before and world.day == 2 and world.minute == 600
    assert world.state.admin_override == "paused"
    assert all(c.schedule_day == 2 for c in world.active_characters())
    assert (await admin_client.put("/api/admin/clock", json={"day": 1, "minute_of_day": 600})).status_code == 409
    assert (await admin_client.put("/api/admin/clock", json={"day": 3, "minute_of_day": 601})).status_code == 400
    weather = {"kind": "rainy", "temp_c": 16, "text": "湖边下起小雨"}
    assert (await admin_client.put("/api/admin/weather", json=weather)).status_code == 200
    async with session_scope() as session:
        state = await session.get(WorldState, 1)
        assert state.day == 2 and state.minute_of_day == 600 and state.weather == weather


@pytest.mark.asyncio
async def test_npc_create_edit_disable_and_player_guard(admin_client, world):
    await login(admin_client)
    template = (await admin_client.get("/api/admin/npcs")).json()[0]
    payload = {"name": "测试 NPC", "persona": template["persona"], "location_id": "lakeside", "energy": 88}
    created = await admin_client.post("/api/admin/npcs", json=payload)
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert world.characters[cid].location_id == "lakeside"
    async with write_session() as session:
        session.add(Memory(id="mem_admin_test", character_id=cid, text="保留的记忆", kind="observation"))
        session.add(Character(id="pl_test", kind="player", name="真人"))
    changed = await admin_client.put(f"/api/admin/npcs/{cid}", json={**payload, "is_active": False, "location_id": "canteen"})
    assert changed.status_code == 200 and not world.characters[cid].is_active
    async with session_scope() as session:
        assert await session.get(Memory, "mem_admin_test") is not None
    assert (await admin_client.put("/api/admin/npcs/pl_test", json=payload)).status_code == 404
    assert (await admin_client.post("/api/admin/npcs", json={**payload, "avatar_key": "invalid"})).status_code == 400


@pytest.mark.asyncio
async def test_scenes_are_active_persistent_and_endable(admin_client, world):
    await login(admin_client)
    created = await admin_client.post("/api/admin/scenes", json={"title": "湖畔读书会", "location_id": "lakeside", "tags": ["阅读"], "duration_ticks": 4})
    assert created.status_code == 201, created.text
    eid = created.json()["id"]
    assert any(e.id == eid for e in world.active_events)
    async with session_scope() as session:
        assert (await session.get(WorldEvent, eid)).end_tick == world.tick + 4
    assert (await admin_client.post(f"/api/admin/scenes/{eid}/end")).json()["status"] == "ended"
    assert all(e.id != eid for e in world.active_events)
    assert (await admin_client.post("/api/admin/scenes", json={"title": "错误", "location_id": "invalid"})).status_code == 400


@pytest.mark.asyncio
async def test_api_settings_encrypted_redacted_and_restored(admin_client):
    await login(admin_client)
    payload = {"llm_base_url": "https://llm.example.test/v1", "llm_model_strong": "strong-test", "llm_model_cheap": "cheap-test", "llm_api_key": "secret-test-key-123", "zhihu_access_secret": "secret-zhihu-123"}
    response = await admin_client.put("/api/admin/settings", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["llm_api_key_configured"]
    assert "secret-test-key" not in response.text and "secret-zhihu" not in response.text
    disk = admin_settings.settings_path().read_bytes()
    assert b"secret-test-key" not in disk and b"secret-zhihu" not in disk
    settings.llm_api_key = ""
    admin_settings.load_runtime_settings()
    assert settings.llm_api_key == payload["llm_api_key"]
    blank = {**payload, "llm_api_key": "", "zhihu_access_secret": ""}
    assert (await admin_client.put("/api/admin/settings", json=blank)).status_code == 200
    assert settings.llm_api_key == payload["llm_api_key"]
    unsafe = await admin_client.put("/api/admin/settings", json={**blank, "llm_base_url": "https://different.example/v1"})
    assert unsafe.status_code == 400
    clear = await admin_client.put("/api/admin/settings", json={**blank, "clear_llm_api_key": True})
    assert not clear.json()["llm_api_key_configured"]
    assert (await admin_client.put("/api/admin/settings", json={**blank, "llm_base_url": "https://user:pass@example.test/v1"})).status_code == 400


@pytest.mark.asyncio
async def test_usage_counts_tokens_even_failed_calls_without_error_leak(admin_client):
    await login(admin_client)
    async with write_session() as session:
        session.add(LlmUsage(model="model-a", prompt_tokens=12, completion_tokens=3, ok=True))
        session.add(LlmUsage(model="model-a", prompt_tokens=7, completion_tokens=2, ok=False, error="sensitive-key-in-provider-error"))
    response = await admin_client.get("/api/admin/overview")
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["usage_by_model"][0]["prompt_tokens"] == 19
    assert data["usage_by_model"][0]["calls"] == 2
    assert "sensitive-key" not in json.dumps(data)
    assert data["counts"]["agents"] > 0


@pytest.mark.asyncio
async def test_ticker_control_wakes_idle_loop(admin_client, world, monkeypatch):
    from app.sim import ticker as ticker_mod

    ticker = ticker_mod.ticker
    ticked = asyncio.Event()

    async def tick_once(_world):
        ticked.set()

    monkeypatch.setattr(ticker, "tick", tick_once)
    monkeypatch.setattr(settings, "tick_seconds_idle", 300)
    await ticker.start()
    await asyncio.wait_for(ticked.wait(), 2)
    ticked.clear()
    await ticker.configure("online")
    await asyncio.wait_for(ticked.wait(), 2)
    await ticker.stop()


@pytest.mark.asyncio
async def test_changed_world_can_run_next_tick(admin_client, world):
    from app.sim import ticker as ticker_mod

    await login(admin_client)
    assert (await admin_client.put("/api/admin/clock", json={"day": 2, "minute_of_day": 600})).status_code == 200
    assert (await admin_client.put("/api/admin/weather", json={"kind": "cloudy", "temp_c": 22})).status_code == 200
    await ticker_mod.ticker.configure("fast_forward", 1)
    ticker_mod.ticker.running = True
    await ticker_mod.ticker.tick(world)
    assert world.state.remaining_ticks == 0
    async with session_scope() as session:
        saved = await session.get(WorldState, 1)
        assert saved.tick == world.tick and saved.remaining_ticks == 0 and saved.admin_override is None


@pytest.mark.asyncio
async def test_restored_settings_rebuild_llm_client(admin_client):
    from app.llm.gateway import get_llm

    await login(admin_client)
    payload = {"llm_base_url": "https://restore.example.test/v1", "llm_model_strong": "strong-restore", "llm_model_cheap": "cheap-restore", "llm_api_key": "restore-secret"}
    assert (await admin_client.put("/api/admin/settings", json=payload)).status_code == 200
    old = get_llm()
    assert old.api_key == "restore-secret"
    settings.llm_api_key = "old-env-value"
    admin_settings.load_runtime_settings()
    await admin_settings.reload_clients()
    assert get_llm() is not old and get_llm().api_key == "restore-secret"
    assert get_llm().base_url == "https://restore.example.test/v1"
