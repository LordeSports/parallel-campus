"""把默认校园地图渲染成自包含 HTML 预览（无需启动服务即可查看效果）。

用法：python scripts/export_map_preview.py
输出：../docs/campus-map-preview.html
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

TEMPLATE = BACKEND.parent / "docs" / "map_preview.template.html"
OUTPUT = BACKEND.parent / "docs" / "campus-map-preview.html"


def main() -> int:
    from app.campus_map import MAP_COLS, MAP_ROWS, build_default_objects

    objects = build_default_objects()
    payload = {
        "title": "平行校园",
        "cols": MAP_COLS,
        "rows": MAP_ROWS,
        "objects": [{"id": f"mo_default_{i:03d}", **o} for i, o in enumerate(objects)],
    }
    html = TEMPLATE.read_text(encoding="utf-8")
    if "__MAP_DATA__" not in html:
        print("模板缺少 __MAP_DATA__ 占位符")
        return 1
    html = html.replace("__MAP_DATA__", json.dumps(payload, ensure_ascii=False))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUTPUT}")
    print(f"  {len(objects)} 个对象 · {MAP_COLS}×{MAP_ROWS} tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
