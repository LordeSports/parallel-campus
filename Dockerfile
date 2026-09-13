# 平行校园 · 后端镜像（多阶段，spec/09 §2）
#
# stage 1：构建前端静态产物
# stage 2：Python 运行时，托管 API + 静态文件
#
# `--workers 1` 是硬约束：单 Ticker + SQLite 单写者。

# ── stage 1：前端构建 ──
# 用 slim（glibc）而非 alpine（musl）：rollup/esbuild 的原生模块对 glibc
# 的兼容面更稳，lock 文件在 Windows 上生成也不会缺 musl 变体。
FROM node:20-slim AS frontend

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── stage 2：后端运行时 ──
FROM python:3.12-slim

# 数据落 VOLUME /data。compose 的 environment / .env 可再覆盖；
# 四个斜杠 = 绝对路径 /data/pc.db（见 config.sqlite_path 的解析）。
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DATABASE_URL=sqlite+aiosqlite:////data/pc.db

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl gosu \
 && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
COPY backend/scripts ./scripts
RUN pip install -e .

# 前端产物挂到 /app/static（main.py 会从这里托管）
COPY --from=frontend /frontend/dist ./static
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN useradd --create-home --uid 10001 app \
 && mkdir -p /data \
 && chown -R app:app /app /data \
 && chmod +x /usr/local/bin/docker-entrypoint.sh

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
