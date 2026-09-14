"""构建指纹与配置来源：确认线上跑的是哪一版代码、配置被谁覆盖。"""
from __future__ import annotations

from app.version import build_fingerprint


def test_build_fingerprint_is_stable_and_short():
    first = build_fingerprint()
    assert first == build_fingerprint()          # 进程内缓存 + 内容决定，稳定
    assert len(first) == 12
    assert all(ch in "0123456789abcdef" for ch in first)


def test_build_fingerprint_tracks_source_changes(tmp_path, monkeypatch):
    """改一个源码文件的内容，指纹必须变——否则无法用来判断容器是否重建。"""
    from app import version

    sandbox = tmp_path / "pkg"
    sandbox.mkdir()
    (sandbox / "a.py").write_text("x = 1\n", encoding="utf-8")
    monkeypatch.setattr(version, "APP_DIR", sandbox)
    version.build_fingerprint.cache_clear()
    before = version.build_fingerprint()

    (sandbox / "a.py").write_text("x = 2\n", encoding="utf-8")
    version.build_fingerprint.cache_clear()
    after = version.build_fingerprint()

    version.build_fingerprint.cache_clear()
    assert before != after


def test_overridden_fields_without_file_is_empty(monkeypatch, tmp_path):
    """没有后台配置文件时返回空集（不抛异常），凭证就该来自 .env。"""
    from app import admin_settings
    from app.config import settings

    monkeypatch.setattr(settings, "admin_settings_file", str(tmp_path / "missing.enc"))
    assert admin_settings.overridden_fields() == set()


def test_overridden_fields_reports_saved_keys(monkeypatch, tmp_path):
    """后台保存过的字段必须能被识别出来——它优先级高于 .env。"""
    from app import admin_settings

    fake = tmp_path / "admin-settings.enc"
    monkeypatch.setattr(admin_settings, "settings_path", lambda: fake)
    monkeypatch.setattr(
        admin_settings,
        "_read",
        lambda: {"zhihu_oauth_app_id": "666", "llm_enabled": True},
    )
    assert admin_settings.overridden_fields() == {"zhihu_oauth_app_id", "llm_enabled"}


def test_overridden_fields_never_raises_on_broken_file(monkeypatch, tmp_path):
    """配置文件解密失败只影响这一项诊断，不能把接口带崩。"""
    from app import admin_settings

    def _boom() -> dict:
        raise RuntimeError("管理员配置无法解密")

    monkeypatch.setattr(admin_settings, "_read", _boom)
    assert admin_settings.overridden_fields() == set()
