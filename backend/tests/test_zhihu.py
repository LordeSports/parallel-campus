"""06 §2–§7：客户端归一化、配额、缓存、OAuth、证据包、mock 夹具。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.errors import QuotaExceeded, ZhihuError
from app.zhihu import user_data as ud_mod
from app.zhihu.client import cache_key
from app.zhihu.mock import MockZhihuClient
from app.zhihu.user_data import build_evidence, clean_text

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND / "app" / "seeds" / "mock_zhihu"

# ─────────────── §7 mock 夹具完整性 ───────────────


def _load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_fixture_counts_match_spec():
    assert len(_load("contents.json")) == 30
    assert len(_load("followees.json")) == 40
    assert len(_load("favlists.json")) == 4
    assert len(_load("collections.json")) == 20


def test_favlists_have_two_public():
    fav = _load("favlists.json")
    public = [f for f in fav if f.get("IsPublic") is True]
    assert len(public) >= 2


def test_favlist_contents_two_groups_of_ten():
    data = _load("favlist_contents.json")
    assert isinstance(data, dict)
    assert len(data) == 2
    for group in data.values():
        assert len(group) == 10


def test_hot_list_has_thirty():
    data = _load("hot_list.json")
    items = data.get("data") if isinstance(data, dict) else data
    assert len(items) == 30


def test_contents_cover_expected_topics():
    rows = _load("contents.json")
    types = {r.get("ContentType") for r in rows}
    assert types, "内容夹具必须带 ContentType"
    text = json.dumps(rows, ensure_ascii=False)
    for kw in ("机器学习", "独立游戏", "校园生活", "科幻", "摄影"):
        assert kw in text, f"夹具缺少主题：{kw}"


def test_zhida_fixture_has_default():
    data = _load("zhida.json")
    assert "_default" in data


# ─────────────── §2 cache key ───────────────


def test_cache_key_stable_and_param_order_insensitive():
    a = cache_key("hot_list", "/api/v1/hot", {"b": 2, "a": 1}, None)
    b = cache_key("hot_list", "/api/v1/hot", {"a": 1, "b": 2}, None)
    assert a == b


def test_cache_key_differs_by_api():
    a = cache_key("hot_list", "/api/v1/hot", {}, None)
    b = cache_key("zhihu_search", "/api/v1/hot", {}, None)
    assert a != b


def test_cache_key_differs_by_oauth_prefix():
    a = cache_key("user_data", "/api/v1/user/contents", {}, "abcdefgh-token")
    b = cache_key("user_data", "/api/v1/user/contents", {}, "zzzzzzzz-token")
    assert a != b


def test_cache_key_oauth_only_uses_first_eight():
    a = cache_key("user_data", "/p", {}, "abcdefgh-XXXX")
    b = cache_key("user_data", "/p", {}, "abcdefgh-YYYY")
    assert a == b


# ─────────────── §2 mock 客户端行为 ───────────────


@pytest.mark.asyncio
async def test_mock_client_hot_list_returns_items(session):
    from app.zhihu.client import bj_date

    client = MockZhihuClient(session, latency=0)
    data = await client.get("hot_list", "/api/v1/hot", {})
    assert data["Code"] == 0
    assert len(data["Data"]["Items"]) == 30
    assert bj_date()


@pytest.mark.asyncio
async def test_mock_client_counts_quota(session):
    from app.zhihu.client import bj_date, quota_count

    client = MockZhihuClient(session, latency=0)
    await client.get("hot_list", "/api/v1/hot", {})
    assert await quota_count(session, "hot_list", bj_date()) >= 1


@pytest.mark.asyncio
async def test_mock_client_quota_exceeded(session):
    from app.zhihu.client import bj_date, quota_count, quota_force_cap

    client = MockZhihuClient(session, latency=0)
    await quota_force_cap(session, "hot_list", bj_date())
    assert await quota_count(session, "hot_list", bj_date()) >= 24
    with pytest.raises(QuotaExceeded):
        await client.get("hot_list", "/api/v1/hot", {})


@pytest.mark.asyncio
async def test_mock_client_zhida(session):
    client = MockZhihuClient(session, latency=0)
    data = await client.post(
        "zhida", "/v1/chat/completions",
        {"messages": [{"role": "user", "content": "什么是独立游戏"}]},
    )
    assert data


@pytest.mark.asyncio
async def test_mock_client_user_data_router(session):
    """user_data 路径分发（06 §7）。"""
    client = MockZhihuClient(session, latency=0)
    contents = await client.get("user_data", "/api/v1/user/contents", {"Limit": 50},
                                oauth_token="tok-123456")
    assert contents["Code"] == 0
    assert len(contents["Data"]["Items"]) == 30

    followees = await client.get("user_data", "/api/v1/user/followees",
                                 {"Limit": 50, "Offset": 0}, oauth_token="tok-123456")
    assert len(followees["Data"]["Items"]) <= 50


@pytest.mark.asyncio
async def test_mock_search_matches_query(session):
    from app.zhihu.content import SEARCH_PATH

    client = MockZhihuClient(session, latency=0)
    data = await client.get("zhihu_search", SEARCH_PATH, {"Query": "独立游戏", "Count": 3})
    assert data["Code"] == 0
    assert isinstance(data["Data"]["Items"], list)


# ─────────────── §4.1 端点路径（回归：曾全线 404） ───────────────


def test_zhihu_endpoint_paths_match_official_docs():
    """端点必须与 `官方skill包/references/http-api.md` 一致。

    回归：曾写成 `/api/v1/search` 与 `/api/v1/hot_list`，线上稳定 404
    （正确路径带 `/content/` 段）。搜索的参数名也是 `Count`，传 `Limit` 会被忽略。
    """
    from app.zhihu.content import HOT_PATH, SEARCH_PATH, ZHIDA_PATH

    assert SEARCH_PATH == "/api/v1/content/zhihu_search"
    assert HOT_PATH == "/api/v1/content/hot_list"
    assert ZHIDA_PATH == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_zhihu_search_passes_documented_params(monkeypatch):
    """搜索：path 带 /content/，参数名为 Count；字符串形式的计数要能解析。"""
    from app.zhihu import content as content_mod

    seen: dict = {}

    class _FakeClient:
        async def get(self, api, path, params, **kw):  # noqa: ANN001, ANN003
            seen.update(api=api, path=path, params=params)
            return {
                "Code": 0,
                "Data": {
                    "Items": [
                        {"Title": "标题", "ContentText": "摘要", "Url": "https://x",
                         "AuthorName": "", "VoteUpCount": "7"},
                    ]
                },
            }

    monkeypatch.setattr(content_mod, "_client", lambda _session: _FakeClient())
    rows = await content_mod.zhihu_search("平行校园", 3, session=object())

    assert seen["api"] == "zhihu_search"
    assert seen["path"] == "/api/v1/content/zhihu_search"
    assert seen["params"] == {"Query": "平行校园", "Count": 3}
    assert rows[0]["vote_up_count"] == 7          # 字符串计数
    assert rows[0]["title"] == "标题"


def test_as_int_tolerates_garbage():
    from app.zhihu.content import _as_int

    assert _as_int("12") == 12
    assert _as_int(3) == 3
    assert _as_int("") == 0
    assert _as_int(None) == 0
    assert _as_int("n/a") == 0
    assert _as_int(" 8 ") == 8


# ─────────────── §4.2 证据包 ───────────────


def test_clean_text_strips_html_and_newlines():
    out = clean_text("<p>你好<br/>世界</p>\n\n第二段")
    assert "<" not in out
    assert "\n" not in out
    assert "你好" in out and "第二段" in out


def test_build_evidence_has_prefixes():
    pack = build_evidence(
        {
            "contents": [
                {"Title": "如何评价 Transformer？", "Excerpt": "我觉得可解释性……",
                 "LikeCount": 127, "CommentCount": 12, "ContentType": "回答"},
            ],
            "followees": [{"Name": "张三", "Headline": "算法工程师，写点机器学习"}],
            "favlists": [{"Title": "好玩的小游戏", "ItemCount": 12, "Description": "都是独立游戏"}],
            "collections": [{"Title": "独立游戏开发者如何起步", "Excerpt": "先做小的",
                             "ContentType": "回答"}],
        },
        failed=[],
    )
    assert "C1" in pack.text
    assert "F1" in pack.text
    assert "L1" in pack.text
    assert "S1" in pack.text


def test_build_evidence_thin_flag():
    thin_pack = build_evidence({"contents": [], "followees": [], "favlists": [], "saved_items": []},
                               failed=[])
    assert thin_pack.thin is True

    rich = build_evidence(
        {"contents": [{"Title": f"t{i}", "Excerpt": "s", "LikeCount": 1, "ContentType": "回答"}
                      for i in range(5)],
         "followees": [], "favlists": [], "collections": []},
        failed=[],
    )
    assert rich.thin is False


def test_build_evidence_strips_html():
    pack = build_evidence(
        {"contents": [{"Title": "<b>标题</b>", "Excerpt": "<p>正文</p>", "LikeCount": 3,
                       "ContentType": "回答"}],
         "followees": [], "favlists": [], "collections": []},
        failed=[],
    )
    assert "<b>" not in pack.text and "<p>" not in pack.text
    assert "标题" in pack.text


def test_build_evidence_respects_length_cap():
    """6000 字上限（06 §4.2）。"""
    pack = build_evidence(
        {
            "contents": [
                {"Title": "标题" * 30, "Excerpt": "摘" * 200, "LikeCount": 9,
                 "ContentType": "回答"}
                for _ in range(30)
            ],
            "followees": [{"Name": f"人{i}", "Headline": "标" * 60} for i in range(40)],
            "favlists": [{"Title": "夹" * 40, "ItemCount": 10, "Description": "描" * 80}
                         for _ in range(4)],
            "collections": [
                {"Title": "收藏项" * 20, "Excerpt": "摘" * 150, "ContentType": "回答"}
                for _ in range(20)
            ],
        },
        failed=[],
    )
    assert len(pack.text) <= ud_mod.EVIDENCE_MAX_CHARS


def test_build_evidence_tolerates_failed_entries():
    pack = build_evidence({"contents": [], "followees": [], "favlists": [], "saved_items": []},
                          failed=["followees:20001", "collections:timeout"])
    assert pack.thin is True
    assert len(pack.failed) == 2


# ─────────────── §3 OAuth ───────────────


def test_authorize_url_contains_required_params():
    from app.zhihu.oauth import authorize_url

    url = authorize_url("STATE123")
    assert "openapi.zhihu.com/authorize" in url
    assert "response_type=code" in url
    assert "state=STATE123" in url
    assert "app_id=" in url
    assert "redirect_uri=" in url


def test_authorize_url_encodes_redirect_uri():
    from app.zhihu.oauth import authorize_url

    url = authorize_url("s")
    assert "redirect_uri=" in url
    # 不能出现未编码的 :// 在 redirect_uri 值里
    assert "redirect_uri=http" not in url or "%3A%2F%2F" in url


def test_display_name_from_url_token():
    from app.zhihu.oauth import TokenResult, display_name_from

    assert display_name_from(TokenResult(access_token="t", url_token="xiaoming")) == "xiaoming"


def test_display_name_fallback_uses_token_hash():
    from app.zhihu.oauth import TokenResult, display_name_from

    name = display_name_from(TokenResult(access_token="abcdef1234567890"))
    assert name and "知乎用户" in name


# ─────────────── §1.3 会话与 token 加密 ───────────────


def test_session_sign_roundtrip():
    from app.security import sign_session, verify_session

    token = sign_session("u_1")
    assert verify_session(token) == "u_1"


def test_session_tampered_returns_none():
    from app.security import sign_session, verify_session

    token = sign_session("u_1")
    assert verify_session(token + "xx") is None


def test_oauth_state_roundtrip():
    """真实流程：cookie 与发给知乎的 state 是**同一个签名串**，知乎原样回显。

    回归点：曾有一段只把 cookie 内层 nonce 与 query（完整签名串）比对，
    导致线上永远 state_mismatch——所以这里必须断言 `verify(cookie, cookie)`。
    """
    from app.security import _serializer, OAUTH_STATE_SALT, sign_oauth_state, verify_oauth_state

    cookie = sign_oauth_state()
    payload = _serializer(OAUTH_STATE_SALT).loads(cookie)

    # ① 真实流程：完整签名串原样回显
    assert verify_oauth_state(cookie, cookie) is True
    # ② 兼容裸 nonce
    assert verify_oauth_state(cookie, payload["s"]) is True
    # ③ 另一份合法签名串（换了登录，nonce 不同）应拒绝
    assert verify_oauth_state(cookie, sign_oauth_state()) is False
    # ④ 篡改 / 缺失
    assert verify_oauth_state(cookie + "xx", cookie + "xx") is False
    assert verify_oauth_state(cookie, "wrong") is False
    assert verify_oauth_state(None, "x") is False
    assert verify_oauth_state(cookie, None) is False


def test_oauth_state_expires(monkeypatch):
    """超过 10 分钟的 state 必须失效（无论 query 是否原样回显）。"""
    import time

    from app.security import sign_oauth_state, verify_oauth_state

    cookie = sign_oauth_state()
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 601)
    assert verify_oauth_state(cookie, cookie) is False


def test_diagnose_oauth_state_reasons():
    """诊断结论要能区分「没带 cookie」「签名不过」「两边不一致」。"""
    from app.security import diagnose_oauth_state, sign_oauth_state

    assert diagnose_oauth_state(None, "x")["reason"] == "no_cookie"
    assert diagnose_oauth_state("x", None)["reason"] == "no_query_state"
    assert diagnose_oauth_state("x", "x")["reason"] == "cookie_signature_invalid_or_expired"

    cookie = sign_oauth_state()
    ok = diagnose_oauth_state(cookie, cookie)
    assert ok["reason"] == "ok" and ok["ok"] is True
    assert ok["cookie_signature_ok"] is True and ok["same_raw"] is True
    assert 0 <= ok["cookie_age_seconds"] < 10
    assert ok["state_max_age_seconds"] == 600

    bad = diagnose_oauth_state(cookie, sign_oauth_state())
    assert bad["reason"] == "cookie_query_mismatch"
    assert bad["cookie_signature_ok"] is True
    assert bad["same_raw"] is False


def test_admin_token_compare():
    from app.security import check_admin_token

    assert check_admin_token("test-admin") is True
    assert check_admin_token("wrong") is False
    assert check_admin_token(None) is False


def test_redact_hides_secret():
    from app.security import redact

    out = redact("Bearer sk-abcdefghijklmnop")
    assert "abcdefghijklmnop" not in out


# ─────────────── OAuth 回调端到端（回归：state 比较对象写错） ───────────────


async def test_zhihu_callback_accepts_echoed_state(engine, monkeypatch):
    """登录 → 知乎原样回显 state → 回调必须通过 state 校验。

    这条才是能抓到 bug 的测试：旧的单测直接把 cookie 内层 nonce 当 query 喂进去，
    掩盖了「真实流程回显的是完整签名串」这一事实，于是线上恒定 state_mismatch。
    """
    from urllib.parse import parse_qs, urlparse

    import httpx

    from app.api import auth as auth_mod
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "zhihu_oauth_app_id", "app-123")
    monkeypatch.setattr(settings, "zhihu_oauth_app_key", "key-456")
    monkeypatch.setattr(settings, "public_base_url", "https://campus.example.test")
    monkeypatch.setattr(
        settings,
        "zhihu_oauth_redirect_uri",
        "https://campus.example.test/api/auth/zhihu/callback",
    )

    async def _offline(_code: str):  # noqa: ANN202
        raise RuntimeError("offline-test")  # 测试不联网 → 停在换 token

    monkeypatch.setattr(auth_mod, "exchange_code", _offline)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://campus.example.test"
    ) as client:
        resp = await client.get("/api/auth/zhihu/login", follow_redirects=False)
        assert resp.status_code == 302
        state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
        # 发给知乎的 state 与 cookie 里的是同一份
        assert client.cookies.get("pc_oauth_state") == state

        cb = await client.get(
            f"/api/auth/zhihu/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )
        assert cb.status_code == 302
        location = cb.headers["location"]
        assert "reason=state_mismatch" not in location, location
        assert "reason=token_exchange_failed" in location, location


async def test_zhihu_callback_rejects_forged_state(engine, monkeypatch):
    """伪造 state（与 cookie 不同）必须被拒，且诊断原因准确。"""
    from app.api import auth as auth_mod
    from app.config import settings
    from app.main import app
    from app.oauth_log import oauth_log
    from app.security import sign_oauth_state

    monkeypatch.setattr(settings, "zhihu_oauth_app_id", "app-123")
    monkeypatch.setattr(settings, "zhihu_oauth_app_key", "key-456")
    monkeypatch.setattr(settings, "public_base_url", "https://campus.example.test")
    monkeypatch.setattr(
        settings,
        "zhihu_oauth_redirect_uri",
        "https://campus.example.test/api/auth/zhihu/callback",
    )
    oauth_log.clear()

    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="https://campus.example.test"
    ) as client:
        resp = await client.get("/api/auth/zhihu/login", follow_redirects=False)
        assert resp.status_code == 302
        # 客户端已持有合法 cookie，但 query 里塞一份攻击者自签的 state
        forged = sign_oauth_state()
        cb = await client.get(
            f"/api/auth/zhihu/callback?code=fake-code&state={forged}",
            follow_redirects=False,
        )
        assert "reason=state_mismatch" in cb.headers["location"]

    entries = oauth_log.recent()
    mismatch = [e for e in entries if e.get("event") == "callback_state_mismatch"]
    assert mismatch, entries
    latest = mismatch[0]  # recent() 最新在前
    assert latest["reason"] == "cookie_query_mismatch"
    assert latest["cookie_signature_ok"] is True
