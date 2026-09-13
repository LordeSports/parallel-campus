"""从本地 openapi.json 生成前端 TS 类型（离线等价于 openapi-typescript）。

用法：
    python scripts/gen_ts_types.py

输入 `backend/openapi.json`（由 `scripts/dump_openapi.py` 产生），
输出 `frontend/src/api/types.ts`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
SPEC = BACKEND / "openapi.json"
OUT = ROOT / "frontend" / "src" / "api" / "types.ts"

PY_TO_TS = {
    "string": "string",
    "integer": "number",
    "number": "number",
    "boolean": "boolean",
    "null": "null",
    "object": "Record<string, unknown>",
}


def _ident(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


def ts_type(schema: dict | None, *, indent: int = 0) -> str:
    """把 JSON Schema 片段转成 TS 类型表达式。"""
    if not schema:
        return "unknown"

    if "$ref" in schema:
        ref = schema["$ref"].rsplit("/", 1)[-1]
        return _ident(ref)

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            parts = [ts_type(s, indent=indent) for s in schema[key]]
            parts = [p for p in parts if p != "null"]
            body = " | ".join(dict.fromkeys(parts)) or "unknown"
            if any(s.get("type") == "null" for s in schema[key]):
                body = f"{body} | null"
            return body

    if "enum" in schema:
        return " | ".join(json.dumps(v, ensure_ascii=False) for v in schema["enum"])

    if "const" in schema:
        return json.dumps(schema["const"], ensure_ascii=False)

    stype = schema.get("type")

    if stype == "array":
        item = ts_type(schema.get("items"), indent=indent)
        if "|" in item and not item.startswith("("):
            item = f"({item})"
        return f"{item}[]"

    if stype == "object" or "properties" in schema:
        props = schema.get("properties") or {}
        add = schema.get("additionalProperties")
        if not props:
            if isinstance(add, dict):
                return f"Record<string, {ts_type(add, indent=indent)}>"
            return "Record<string, unknown>"
        pad = "  " * (indent + 1)
        close = "  " * indent
        lines = []
        for name, sub in props.items():
            optional = name not in (schema.get("required") or [])
            lines.append(
                f"{pad}{json.dumps(name, ensure_ascii=False)}"
                f"{'?' if optional else ''}: {ts_type(sub, indent=indent + 1)};"
            )
        return "{\n" + "\n".join(lines) + f"\n{close}}}"

    if isinstance(stype, list):
        parts = [ts_type({**schema, "type": t}, indent=indent) for t in stype if t != "null"]
        body = " | ".join(dict.fromkeys(parts)) or "unknown"
        if "null" in stype:
            body += " | null"
        return body

    return PY_TO_TS.get(stype or "", "unknown")


def main() -> None:
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    schemas = spec.get("components", {}).get("schemas", {})

    chunks: list[str] = [
        "/**",
        " * 本文件由 `backend/scripts/gen_ts_types.py` 从 `backend/openapi.json` 生成。",
        " * 等价于 `npx openapi-typescript http://localhost:8000/api/openapi.json -o src/api/types.ts`。",
        " * 请勿手改；后端契约变更后重新生成。",
        " */",
        "",
        "/* eslint-disable */",
        "",
    ]

    for name in sorted(schemas):
        body = ts_type(schemas[name])
        chunks.append(f"export type {_ident(name)} = {body};")
        chunks.append("")

    chunks.append("export interface paths {")
    for path, item in sorted(spec.get("paths", {}).items()):
        chunks.append(f"  {json.dumps(path, ensure_ascii=False)}: {{")
        for method, op in sorted(item.items()):
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            chunks.append(f"    {method}: {json.dumps(op.get('operationId') or '', ensure_ascii=False)};")
        chunks.append("  };")
    chunks.append("}")
    chunks.append("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(chunks), encoding="utf-8")
    print(f"wrote {OUT} ({len(chunks)} lines)")


if __name__ == "__main__":
    main()
