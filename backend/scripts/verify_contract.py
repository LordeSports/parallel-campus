"""阶段 0 验收：uvicorn 起得来 + OpenAPI 含 spec/03 全部路径。

不连数据库、不启 Ticker——只做「能导入、能生成 schema」这一步。
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402

SPEC_03 = BACKEND.parent.parent / "spec" / "03-api.md"


def spec_paths() -> set[str]:
    """从 spec/03-api.md 抽出所有具体 `/api/...` 端点。

    只取带方法前缀表格里的路径（形如 `GET /api/xxx`），跳过文中的裸前缀
    （`/api/auth`）——它们不是端点，会误报成「未实现」。
    """
    text = SPEC_03.read_text(encoding="utf-8")
    found: set[str] = set()
    for m in re.finditer(
        r"`(?:GET|POST|PUT|PATCH|DELETE)\s+(/api/[A-Za-z0-9_\-{}/.]*)`", text
    ):
        found.add(m.group(1).rstrip(".,;:）)"))
    return found


def main() -> int:
    schema = app.openapi()
    paths = set(schema["paths"].keys())
    print(f"OpenAPI: {len(paths)} paths · {len(schema['components']['schemas'])} schemas")

    missing = sorted(p for p in spec_paths() if p not in paths and "{" not in p)
    if missing:
        print("\n⚠ 以下 spec/03 路径未实现：")
        for p in missing:
            print(f"  - {p}")
    else:
        print("✓ spec/03 全部静态路径均已实现")

    out = BACKEND / "openapi.json"
    out.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"✓ 已写出 {out.relative_to(BACKEND.parent)}")

    required_prefixes = ["/api/auth", "/api/persona", "/api/world", "/api/wall", "/api/avatar", "/api/admin", "/api/stream", "/api/health"]
    for pre in required_prefixes:
        ok = any(p.startswith(pre) for p in paths)
        print(f"  {'✓' if ok else '✗'} {pre}")
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
