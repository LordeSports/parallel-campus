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
    client = MockZhihuClient(session, latency=0)
    data = await client.get("zhihu_search", "/api/v1/search", {"Query": "独立游戏"})
    assert data["Code"] == 0
    assert isinstance(data["Data"]["Items"], list)


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
    from app.security import sign_oauth_state, verify_oauth_state

    cookie = sign_oauth_state()
    # verify_oauth_state(cookie_value, query_state)：query_state 必须与 cookie 内一致
    from app.security import _serializer, OAUTH_STATE_SALT

    payload = _serializer(OAUTH_STATE_SALT).loads(cookie)
    assert verify_oauth_state(cookie, payload["s"]) is True
    assert verify_oauth_state(cookie, "wrong") is False
    assert verify_oauth_state(None, "x") is False


def test_admin_token_compare():
    from app.security import check_admin_token

    assert check_admin_token("test-admin") is True
    assert check_admin_token("wrong") is False
    assert check_admin_token(None) is False


def test_redact_hides_secret():
    from app.security import redact

    out = redact("Bearer sk-abcdefghijklmnop")
    assert "abcdefghijklmnop" not in out
