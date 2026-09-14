"""构建指纹：确认线上跑的到底是哪一版代码。

排查「改了代码但行为没变」时最费时的就是确认容器有没有真的重建。
这里不依赖 git（镜像里没有 `.git`），也不依赖文件 mtime（COPY 行为不稳定），
而是对后端源码**内容**做哈希——**代码一改指纹就变**。

用法：
    本地  python -c "from app.version import build_fingerprint; print(build_fingerprint())"
    线上  curl -s /api/health | python -c "import json,sys; print(json.load(sys.stdin)['build'])"
两者不一致 → 容器没重建。
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=1)
def build_fingerprint() -> str:
    """后端源码内容哈希（12 位）。进程内缓存，只算一次。"""
    digest = hashlib.sha1()
    for path in sorted(APP_DIR.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(APP_DIR).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()[:12]


__all__ = ["build_fingerprint", "APP_DIR"]
