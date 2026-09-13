"""导出 OpenAPI 到 `backend/openapi.json`（离线，不启服务）。

用法：
    python scripts/dump_openapi.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.main import app  # noqa: E402

OUT = BACKEND / "openapi.json"

spec = app.openapi()
OUT.write_text(json.dumps(spec, ensure_ascii=False, indent=1), encoding="utf-8")
print(f"wrote {OUT} — {len(spec['paths'])} paths, {len(spec['components']['schemas'])} schemas")
