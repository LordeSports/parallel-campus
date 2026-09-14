"""起一个真实 uvicorn，打几个接口，确认服务能活。

用法：python scripts/smoke_serve.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
PY = sys.executable
PORT = int(os.environ.get("SMOKE_PORT", "8123"))
BASE = f"http://127.0.0.1:{PORT}"


def get(path: str, cookie: str | None = None, extra: dict[str, str] | None = None) -> tuple[int, str]:
    req = urllib.request.Request(BASE + path)
    if cookie:
        req.add_header("Cookie", cookie)
    for k, v in (extra or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def put(path: str, body: dict | None = None, extra: dict[str, str] | None = None) -> tuple[int, str]:
    data = json.dumps(body or {}).encode()
    headers = {"Content-Type": "application/json"}
    headers.update(extra or {})
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def post(path: str, body: dict | None = None) -> tuple[int, str, str | None]:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        BASE + path, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Set-Cookie")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), None


def main() -> int:
    env = dict(os.environ)
    # 每次用全新库：地图保存测试会改数据，避免污染上一次的冒烟库。
    # （文件名带 pid，且 data/ 已在 .gitignore 里）
    db_path = BACKEND / "data" / f"smoke_{os.getpid()}.db"
    env.update(
        {
            "APP_ENV": "dev",
            "DEV_MODE": "true",
            "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}",
            "SESSION_SECRET": "smoke-secret",
            "ADMIN_TOKEN": "smoke-admin",
            "LOG_LEVEL": "warning",
        }
    )
    (BACKEND / "data").mkdir(exist_ok=True)

    proc = subprocess.Popen(
        [
            PY, "-m", "uvicorn", "app.main:app",
            "--host", "127.0.0.1", "--port", str(PORT),
            "--workers", "1", "--log-level", "warning",
        ],
        cwd=BACKEND,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    try:
        # 等就绪
        ready = False
        for _ in range(60):
            if proc.poll() is not None:
                print("✗ 进程提前退出：")
                print(proc.stdout.read() if proc.stdout else "")
                return 1
            try:
                code, _ = get("/api/health")
                if code == 200:
                    ready = True
                    break
            except Exception:
                time.sleep(0.5)
        if not ready:
            print("✗ 60 次探测内未就绪")
            return 1

        print("✓ 服务已就绪")

        # 开发登录（DEV_MODE=true）→ 拿会话 cookie
        code, body, set_cookie = post("/api/auth/dev-login", {"name": "冒烟同学"})
        cookie = None
        if set_cookie:
            cookie = set_cookie.split(";", 1)[0]
        print(f"  {'✓' if code == 200 else '✗'} POST /api/auth/dev-login → {code}")
        if code != 200:
            print(body[:200])

        checks = [
            ("/api/health", 200, False),
            ("/api/openapi.json", 200, False),
            ("/api/world/state", 200, False),
            ("/api/world/locations", 200, True),
            ("/api/world/characters", 200, True),
            ("/api/wall/posts?board=wall&limit=5", 200, True),
            ("/api/auth/me", 200, True),
            # spec/03 §3：GET /persona 对「尚未生成人格」的新用户返回 404
            # （前端据此跳转 /persona 编辑器）。dev-login 刚建的用户必然没有人格。
            ("/api/persona", (200, 404), True),
        ]
        failed = 0
        for path, want, need_auth in checks:
            code, body = get(path, cookie if need_auth else None)
            want_tuple = want if isinstance(want, tuple) else (want,)
            ok = code in want_tuple
            failed += 0 if ok else 1
            extra = ""
            if ok and path == "/api/world/state":
                try:
                    d = json.loads(body)
                    extra = f"  day={d.get('day')} tick={d.get('tick')} mode={d.get('speed_mode')}"
                except Exception:
                    pass
            if ok and path == "/api/world/characters":
                try:
                    extra = f"  {len(json.loads(body))} 个角色"
                except Exception:
                    pass
            if ok and path == "/api/world/locations":
                try:
                    extra = f"  {len(json.loads(body))} 个地点"
                except Exception:
                    pass
            if ok and path == "/api/persona":
                extra = "  （新用户尚未生成人格，符合 spec）" if code == 404 else ""
            want_label = " 或 ".join(str(w) for w in want_tuple)
            print(f"  {'✓' if ok else '✗'} {path} → {code}（期望 {want_label}）{extra}")

        # ── 校园地图（读 / 管理员读写 + 版本递增）──
        print("\n-- 校园地图 --")
        admin = {"X-Admin-Token": env["ADMIN_TOKEN"]}
        code, body = get("/api/world/map", cookie)
        v1, n1 = None, 0
        if code == 200:
            try:
                d = json.loads(body)
                v1, n1 = d.get("version"), len(d.get("objects") or [])
            except Exception:
                pass
            print(f"  ✓ GET /api/world/map → 200  version={v1} objects={n1}")
            if not (isinstance(n1, int) and n1 > 0):
                failed += 1
        else:
            failed += 1
            print(f"  ✗ GET /api/world/map → {code} {body[:120]}")

        code, body = get("/api/admin/map", None, admin)
        if code == 200:
            print("  ✓ GET /api/admin/map → 200（管理员读）")
        else:
            failed += 1
            print(f"  ✗ GET /api/admin/map → {code} {body[:120]}")

        # 保存一张最小合法地图（草地 + 一栋楼），再读回确认版本 +1
        save_body = {
            "title": "冒烟校园",
            "objects": [
                {"kind": "ground", "variant": "grass", "tx": 0, "ty": 0, "tw": 40, "th": 30, "layer": 0},
                {"kind": "building", "variant": "tower", "tx": 8, "ty": 8, "tw": 6, "th": 5,
                 "height": 5, "layer": 20, "name": "测试塔", "location_id": "library"},
            ],
        }
        code, body = put("/api/admin/map", save_body, admin)
        if code == 200:
            try:
                d = json.loads(body)
                v2, n2 = d.get("version"), len(d.get("objects") or [])
            except Exception:
                v2, n2 = None, 0
            ok = isinstance(v2, int) and isinstance(v1, int) and v2 == v1 + 1 and n2 == 2
            failed += 0 if ok else 1
            print(f"  {'✓' if ok else '✗'} PUT /api/admin/map → 200  version {v1}→{v2} objects={n2}（应 2）")
        else:
            failed += 1
            print(f"  ✗ PUT /api/admin/map → {code} {body[:160]}")

        # 非法变体必须被拒（schema 白名单）
        bad = {"objects": [{"kind": "building", "variant": "nope", "tx": 1, "ty": 1}]}
        code, _ = put("/api/admin/map", bad, admin)
        ok = code == 400
        failed += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} PUT /api/admin/map（非法变体）→ {code}（期望 400）")

        # 无管理员凭据必须 401
        code, _ = put("/api/admin/map", save_body)
        ok = code == 401
        failed += 0 if ok else 1
        print(f"  {'✓' if ok else '✗'} PUT /api/admin/map（无凭据）→ {code}（期望 401）")

        return 0 if failed == 0 else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
