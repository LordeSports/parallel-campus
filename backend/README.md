# 平行校园 · Backend

FastAPI + SQLModel + asyncio。单进程（`--workers 1`），SQLite WAL，一个 Ticker 驱动整个虚拟校园。

## 快速开始（本地）

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env                                   # 填 LLM_API_KEY 等
uvicorn app.main:app --reload --port 8000
```

后端端口由 Uvicorn 的 `--port` 参数控制，可替换为任意可用端口。

第一次启动会自动建表、加载 seeds、创建 NPC 与 `sys_broadcast`。
若 `DEV_MODE=true`，`POST /api/auth/dev-login` 可直接用名字登录（走 mock 知乎数据）。

## 目录

```
app/
  config.py          环境变量（pydantic-settings）
  db.py              async engine / session / write_lock
  main.py            FastAPI app + lifespan（建表、seeds、Ticker）
  security.py        会话 cookie 签名、Fernet token 加密
  models/            SQLModel 表（见 spec/02）
  schemas/           Pydantic 请求/响应（PersonaFile、Decision、Dialogue、SSE payload…）
  api/               REST 路由（auth/persona/world/wall/avatar/admin/stream/health）
  sim/               模拟引擎（04）
    world.py         世界状态与快照
    ticker.py        心跳状态机
    stimuli.py       刺激计算
    gate.py          决策门控
    char_agent.py    decide() 单角色决策
    actions.py       十种动作落地
    dialogue.py      对话配对与单次生成
    memory.py        记忆写入/检索/观察/反思
    env_agent.py     新一天/热榜转译/简报
    report.py        匹配报告
    filter.py        内容安全
    bus.py           进程内事件总线（SSE 扇出）
  llm/
    gateway.py       OpenAI 兼容网关 + JSON 修复链
    prompts/*.j2     9 个 Jinja2 模板
  zhihu/             知乎适配层（06）
  persona/           人格提取管线
  seeds/             seeds JSON + mock_zhihu 夹具
tests/               pytest
```

## 关键约束

- **`--workers 1` 是硬约束**：单 Ticker、SQLite 单写者。多 worker 会得到两个互相覆盖的模拟。
- 契约以 `spec/*.md` 为准；与 `docs/`、`.zcf/plan` 冲突时以 spec 为准。
- 所有落库在 tick 末一次事务提交，崩溃丢当前 tick 不回退。
