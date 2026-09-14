# 平行校园 · Parallel Campus

> 知乎黑客松 2026 · 校园新锐季 · 赛道：灵魂匹配局（社区 × 社交）

把你的知乎公开创作、关注与收藏，炼成一份**可编辑的人格文件**，投进一个**会自己运转的虚拟校园**。
你的分身在这里上课、吃饭、聊天、发帖；你只能通过「耳语」给它递话，看它怎么决定。
48 个虚拟小时之后，校园墙与匹配报告会把「另一个你可能认识的人」推回到真人面前。

---

## 一、它是什么

| 层 | 做什么 |
|---|---|
| **人格层** | 读知乎公开数据 → 证据包 → LLM 提炼 `PersonaFile`（原型、MBTI-like、大五、兴趣、立场、说话风格）。可编辑、可重生成。 |
| **世界层** | 8 个地点、26 个分身（8 个 NPC + 真人分身 + 校园广播）。1 tick = 30 虚拟分钟，1 虚拟日 = 48 tick。日程驱动 + 刺激驱动的决策门控。 |
| **校园地图** | **等距手绘风（isometric）可编辑地图**：建筑有屋顶与立面、地面有草地/土路/水域/跑道，树木、石块、长椅等摆件可独立摆放。管理员在后台拖动、缩放、增删，保存后经 SSE 实时同步给所有玩家。 |
| **社交层** | 十种动作（move/talk/post/comment/like/dm/attend/do/search_zhihu/idle）；对话单次生成、逐轮推送；记忆打分检索；好感关系演化。 |
| **回流层** | 校园墙（校园墙/树洞/公告）· 日记（心情曲线 + 时间线 + 夜间反思）· 耳语（每天 3 次）· 匹配报告（Top3 + 关系图）。 |
| **实时层** | SSE 单向广播事件；连接数 = 观众数 → Ticker 速率自适应（online 20s / idle 300s / fast_forward 0s）。 |

> 两个视图的分工（都在 `/campus`）：
> 玩家端 `/campus` 只呈现**校园地图**：管理员可改、所有人可见，角色按绑定的地点站在建筑前。
> 地图支持**滚轮缩放、拖动平移**（右上角显示缩放百分比，可一键重置）。
> 原来的平面场景视图（「校园活动」页）已移除。

**预览**：`docs/campus-map-preview.html`（自包含，直接双击打开即可看默认地图效果，支持拖动与缩放）。

**核心设计取舍**：分身不是「被遥控的号」，是一个有记忆、会拒你的角色。耳语是**建议**而非**命令**——它会评估、可能采纳，也可能拒绝并给出理由。

---

## 二、架构

```
┌──────────────────────────────────────────────────────────────┐
│  [可选 Caddy: 443 自动 HTTPS，SSE 不缓冲]                     │
│      └─► uvicorn --workers 1  （默认直接暴露 8000）           │
│            ├── FastAPI REST  /api/*                          │
│            ├── SSE  /api/stream  ── 事件总线扇出             │
│            ├── Ticker（单例，状态机）── 每 tick 跑一轮世界      │
│            └── SQLite WAL（/data/pc.db，单写者 + BEGIN IMMEDIATE）│
└──────────────────────────────────────────────────────────────┘
            │                                    ▲
            │ LLM (OpenAI 兼容)                   │ 知乎开放接口
            ▼                                    │ (Bearer + 时间戳签名)
     9 个 Jinja2 模板                      hot_list / zhihu_search
     temperature 0.4–0.9                   / zhida / user_data
```

### 一个 tick 里发生什么

1. `advance()` 推进时间（跨日时 `minute_of_day` 归 360，`tick` 单调递增）
2. `stimuli.compute()` 给每个角色算刺激（whisper 10 / dm_unread 8 / mention 8 / new_face 7 / …）
3. `gate` 决定谁需要决策：salience ≥ 8 必决策；日程边界必决策；有刺激 60% 决策；另有 15% 随机自发性
4. 排序（player 优先 → salience 降序 → 随机），取前 `MAX_DECISIONS_PER_TICK=10`，并发度 ≤ `MAX_CONCURRENT_LLM=8`
5. `char_agent.decide()` 调 LLM → `Decision`；超时/解析失败 → 退化为 `follow_schedule`
6. `actions.apply_all()` 落地十种动作并校验（`talk` 必须带在场角色的 `target_id`）
7. `dialogue.run_all()` 配对在场角色 → 单次生成整段对话 → 逐轮推 `dialogue_turn`
8. `memory` / 关系 / 好感更新
9. **tick 末一次事务提交**（崩溃丢当前 tick，不回退）

---

## 三、本地运行

### 后端

```bash
cd backend
python -m venv .venv && . .venv/Scripts/activate     # Windows
# source .venv/bin/activate                          # macOS / Linux
pip install -e ".[dev]"
cp .env.example .env                                  # 至少填 LLM_API_KEY
uvicorn app.main:app --reload --port 8000
```

可通过命令行 `--port` 自定义后端端口；Docker Compose 使用 `APP_PORT` 自定义宿主机端口（容器内仍为 8000）。

首次启动自动建表、加载 seeds、创建 NPC 与校园广播。
`DEV_MODE=true` 时可用 `POST /api/auth/dev-login`（走 mock 知乎数据）直接登录。

### 前端

```bash
cd frontend
npm install
npm run dev                                           # http://localhost:5173，代理 /api → :8000
```

前端开发端口可设置 `VITE_PORT=5174`，后端代理地址可设置 `VITE_API_TARGET=http://localhost:18000`。

### 测试与契约

```bash
cd backend

# 全量测试（128 passed）
# ⚠️ 必须指定项目内的 basetemp/cache_dir：默认的 %TEMP%\pytest-of-* 目录
#    在清理时会触发沙箱的批量删除守卫，导致 pytest 的 stdout 被吞掉。
pytest -q --basetemp=./_pt -o cache_dir=./_pc

# 单文件
pytest tests/test_sim_loop.py -q

# 起真实 uvicorn 打 9 个接口（冒烟）
python scripts/smoke_serve.py

# 写会话语义（write_session / session_scope / rollback）
python scripts/verify_write.py

# OpenAPI 与 spec/03 逐路径核对（33 paths / 56 schemas）
python scripts/verify_contract.py

# 重新生成前端类型
python scripts/dump_openapi.py && python scripts/gen_ts_types.py
```

**已验收（spec/10 §1 阶段 0）**

| 项 | 结果 |
|---|---|
| `pytest` 全量 | 128 passed |
| `test_e2e_fast_forward_meets_acceptance`（48 tick → ≥10 帖、≥5 对话） | 通过 |
| `scripts/smoke_serve.py`（9 接口） | 9/9 通过 |
| `scripts/verify_contract.py` | 33 paths 全覆盖 |
| `scripts/verify_write.py` | 4/4 通过 |
| 前端 `eslint` / `tsc --noEmit` / `vite build` | 0 错 / 0 错 / 通过 |
| 单 tick 耗时（8 NPC） | 0.44s |

> 契约以 `spec/*.md` 为准。与 `docs/` 或旧计划冲突时，**以 spec 为准**。
>
> 注意：`GET /api/persona` 对尚未生成人格的用户返回 **404**（spec/03 §3），
> 前端据此跳转 `/persona` 编辑器——这是预期行为，不是错误。

### 校园地图：接口与需求演进

| 端点 | 说明 |
|---|---|
| `GET /api/world/map` | 所有登录玩家读取地图（含 `version`），前端按版本失效 |
| `GET /api/admin/map` | 管理员读取（同一份数据） |
| `PUT /api/admin/map` | 整图覆盖保存，`version + 1`，广播 `map_updated` |

数据落在两张新表：`campus_map`（版本、网格尺寸）+ `campus_map_objects`（每个建筑/摆件/地面块）。
坐标用 **tile**（浮点），前端做等距投影（`frontend/src/map/iso.ts`，2:1 菱形网格）。

相对 spec 的三处演进（**新增，未修改既有约定**）：

1. SSE 事件多了一个 `map_updated`（spec/04 §4 原列 20 类；此前实现已有 `world_changed` 作为第 21 类）。
2. 新增管理员「校园地图」编辑页；原「场景布置」更名为「校园活动」（仅保留管理端入口）。
3. 玩家端 `/campus` 只保留校园地图（支持缩放 / 拖动），不再提供平面场景视图。
4. 登录页在 `DEV_MODE` 下显示 **OAuth 调试面板**（数据来自 `GET /api/auth/oauth-log`），
   直接回显生效中的 `redirect_uri` / `cookie_secure` / 凭证状态，以及最近的登录失败环节。
5. 新增 **LLM 总开关**（`llm_enabled`）：关闭后完全不调用模型，角色退回日程与规则行动。
6. **移除评委（judge）功能**：删除 `judge-login` 端点、`JUDGE_ACCOUNTS` 配置、`judges.json`
   与 `User.is_judge` / `judge_username` 字段；登录页只留「知乎登录 / 开发登录」。

`CampusLocation`（地点语义、容量、氛围）与地图对象（视觉层）**解耦**：建筑通过 `location_id`
回指地点，用来把角色画在对应建筑前；管理员重画地图不影响模拟逻辑。

### 知乎 OAuth 登录：流程与排查

```
GET /api/auth/zhihu/login
  ├─ state = sign_oauth_state()            # 签名串，含随机 nonce + 时间戳
  ├─ Set-Cookie pc_oauth_state = state     # ← 同一个串
  └─ 302 openapi.zhihu.com/authorize?…&state=state   # ← 同一个串，知乎原样回显
GET /api/auth/zhihu/callback?code=…&state=…
  └─ verify_oauth_state(cookie, query)     # 双提交校验（CSRF）
```

**关键点：cookie 与发给知乎的 `state` 是同一个签名串**，回调时知乎把它原样带回来，
所以正常情况下 `query_state == cookie_value`。校验必须拿**完整串**比对——
历史上这里错拿 cookie 内层 nonce 去比，导致线上恒定 `state_mismatch`
（cookie 有、query 有、state 也刚签发，却永远不通过）。已修复，并有端到端回归测试覆盖。

**失败诊断**（`DEV_MODE` 下看登录页「OAuth 调试日志」，或
`docker compose logs app | grep -i oauth`）。日志里的 `reason` 直接指明环节：

| `reason` | 含义 | 修法 |
|---|---|---|
| `no_cookie` | cookie 没回到后端 | 让浏览器地址、`PUBLIC_BASE_URL`、`ZHIHU_OAUTH_REDIRECT_URI`、知乎后台登记地址**四处 host/协议完全一致**；`cookie_secure=true` 时链路上不能有 http 跳 |
| `no_query_state` | 回调没带 state | 知乎后台的回调地址填错（应填 `…/api/auth/zhihu/callback`） |
| `cookie_signature_invalid_or_expired` | 签名验不过或超 10 分钟 | 看日志里的 `cookie_age_seconds`：① 很小却验不过 → 签发与校验用的不是同一个 `SESSION_SECRET`（多实例/多 worker 各自随机生成）② 很大 → 在授权页停留过久 |
| `cookie_query_mismatch` | 两边值不同 | 同一浏览器提交了两次登录（旧 cookie 被新的覆盖），重新走一遍即可 |

`reason=missing_code`（知乎没返回授权码）则要看 `app_id` 是否是知乎分配的**真实 App ID**——
拿 `app_id=666` 这类占位值会被知乎直接打发回来。
另外凭证需要的是 **App ID + App Key**；`ZHIHU_ACCESS_SECRET` 是调开放接口用的，
**不能**用来换登录 token。拿不到 App Key 就用登录页的「开发登录」。

#### 先确认「线上跑的到底是哪一版代码」

排查改了代码却没生效时，**第一步永远是确认容器有没有真的重建**。两个办法：

```bash
# ① 代码指纹：源码内容哈希，代码一改就变（不含 git，不受 mtime 影响）
curl -s http://localhost:8000/api/health | python -c "import json,sys; print(json.load(sys.stdin)['build'])"
cd backend && python -c "from app.version import build_fingerprint; print(build_fingerprint())"
# 两个值一致 → 线上就是本地这版；不一致 → 容器没重建（用 docker compose up -d --build，不要只 restart）

# ② dev 调试面板里的「代码指纹」一行，附带「后台配置覆盖」提示
```

> 日志格式也是指纹：修复后 `callback_state_mismatch` 会带 `reason=` / `cookie_signature_ok=`
> / `cookie_age_seconds=` 字段。**只有 `why=` 而没有 `reason=`，说明跑的是修复前的代码。**

#### 配置到底来自 `.env` 还是后台？

管理后台保存的值加密存在数据卷 `admin-settings.enc`，**优先级高于 `.env`，且重建容器不会清掉**——
这是「我明明改了 `.env` 却没生效」的常见原因。dev 调试面板会显示每个凭证的 `来源`，
以及 `overridden_fields`（被后台覆盖的字段清单）。

注意事项：

1. **改完 `.env` 必须 `docker compose up -d`（重建），`restart` 不会重读 `env_file`。**
2. `PUBLIC_BASE_URL` / `ZHIHU_OAUTH_REDIRECT_URI` **后台改不了**，只能来自 `.env`。
3. `SESSION_SECRET` 同时管会话 cookie 签名 + `admin-settings.enc` 的加密密钥，
   改过它会让旧的后台配置解不开（并导致启动失败，见下）。

---

## 四、环境变量

完整清单见 `.env.example`。生产必填（`APP_ENV=prod` 时启动校验，缺项拒绝启动）：

| 变量 | 说明 |
|---|---|
| `SESSION_SECRET` | 会话 cookie 签名（`openssl rand -hex 32`） |
| `TOKEN_ENC_KEY` | Fernet 密钥，加密存知乎 token |
| `ADMIN_TOKEN` | 运维接口凭证 |
| `LLM_API_KEY` | OpenAI 兼容网关密钥 |
| `DATABASE_URL` | 默认 `sqlite+aiosqlite:////data/pc.db` |
| `ZHIHU_ACCESS_SECRET` / `ZHIHU_OAUTH_APP_ID` / `ZHIHU_OAUTH_APP_KEY` | 知乎开放接口与 OAuth |

`DEV_MODE` 在 prod 必须为 `false`（否则拒绝启动）。

---

## 五、知乎能力清单

| 能力 | 接口 | 用途 | 配额 |
|---|---|---|---|
| 热榜 | `hot_list` | 转译为校园事件（讲座/比赛/讨论），挂原文链接 | 24/日 |
| 搜索 | `zhihu_search` | 分身主动「查资料」；生成话题帖 | 200/日 |
| 知乎直答 | `zhida` | 事件背景说明、角色观点补充 | 50/日 |
| 用户数据 | `user_data`（contents / followees / favlists / saved_items） | 人格证据包 | 无硬限 |

鉴权：`Authorization: Bearer <secret>` + `X-Request-Timestamp`。
带响应缓存（key 含路径、排序参数与 token 前缀），**失败不重试**，日志脱敏。

---

## 六、目录

```
parallel-campus/
├── backend/
│   ├── app/
│   │   ├── api/          REST 路由
│   │   ├── models/       SQLModel 表
│   │   ├── schemas/      请求/响应 + SSE payload
│   │   ├── campus_map.py 可编辑校园地图：默认布局 + 读写
│   │   ├── sim/          模拟引擎（世界/Ticker/门控/动作/对话/记忆/报告/总线）
│   │   ├── llm/          LLM 网关 + 9 个 Jinja2 模板
│   │   ├── zhihu/        知乎适配层（client / oauth / content / user_data / mock）
│   │   ├── persona/      人格提取管线
│   │   └── seeds/        seeds JSON + mock_zhihu 夹具
│   ├── scripts/          OpenAPI 导出 / TS 类型生成 / 地图预览 / 验证脚本
│   └── tests/
├── frontend/
│   └── src/
│       ├── api/          client · sse · endpoints · types（生成）
│       ├── map/          iso.ts（等距投影与配色）
│       ├── store/        session · world · wall · avatar · map（zustand）
│       ├── components/   AppShell · IsoMap · MapEditor · MapCanvas · LiveFeed
│       │                 CharacterDrawer · PersonaEditor · DeployForm · MoodChart · RelationGraph
│       └── pages/        Login · Persona · Campus · Wall · Diary · Report · Admin
├── docs/                 校园地图预览（自包含 HTML）
├── ops/                  部署与备份脚本
├── Dockerfile            多阶段：前端构建 → Python 运行时
├── docker-compose.yml    app（默认，直接 8000）+ caddy（可选 profile）
├── Caddyfile             SSE flush_interval -1（启用 caddy profile 时使用）
└── spec/                 11 份实现契约（00–10）
```

---

## 七、部署

默认**不用 Caddy**——uvicorn 直接对外（前端静态 + API + SSE 同源同端口）：

```bash
cp .env.example .env      # 填值（APP_ENV=dev 可先跑通）
docker compose up -d --build
curl http://localhost:8000/api/health
# 浏览器打开 http://localhost:8000
```

> 容器内数据库固定落卷：compose 会强制 `DATABASE_URL=sqlite+aiosqlite:////data/pc.db`
> （`environment` 优先级高于 `.env`），宿主机 `./data/` 就是数据目录，备份它即可。
> Windows / WSL2 挂载无权限问题；原生 Linux 宿主若报只读，`chmod -R o+rw ./data` 或改属主 UID 10001。

需要自动 HTTPS / 80+443 反代（有域名、公网部署）时，Caddy 作为**可选 profile** 启用：

```bash
docker compose --profile caddy up -d --build
curl https://<域名>/api/health
curl -N https://<域名>/api/stream -H "Cookie: pc_session=…"   # 15s 内应见 heartbeat
```

预热：`POST /api/admin/hot-pull` → `POST /api/admin/fast-forward?ticks=144` → `GET /api/admin/status` 确认 `fail_streak==0`。

**镜像构建常见坑**

- `sh: tsc: Permission denied`（exit 126）：构建上下文把本机 `node_modules` COPY 进了镜像、
  覆盖 `npm ci` 的 Linux 版本。已由根目录 `.dockerignore`（`**/node_modules` 等）解决，勿删。
- 本机 node_modules/dist/.env/数据库文件都不会进构建上下文（见 `.dockerignore`）。

---

## 八、管理员控制台

访问 `/admin`（登录页「其他方式 → 管理员入口」，或校园导航「管理」）。管理员独立于普通用户，不需要生成或投放分身。
在项目 `.env` 中设置 `ADMIN_USERNAME=admin` 和自己的 `ADMIN_PASSWORD`，然后执行 `docker compose up -d --build`。密码留空时登录禁用。
同时配置独立、保密且稳定的 `SESSION_SECRET`，用于会话签名及管理配置加密。修改管理员用户名/密码后，旧管理会话失效。

- **总览**：Agent/NPC/真人分身数量、在线人数、世界数据、今日 Token、按模型汇总与最近调用。
- **校园地图**：等距手绘地图编辑器。左侧素材面板（地面 / 建筑 / 摆件）点选后在地图上点一下放置；拖动移动（半格吸附）、滚轮缩放、空白拖动平移；右侧属性面板可改样式、尺寸、高度、名称与**绑定地点**；支持撤销（Ctrl+Z）、复制、删除（Delete）、网格与适应视图。点「保存并同步」后版本号 +1，并向所有在线玩家广播 `map_updated`，玩家端自动重新拉取。
- **模拟与环境**：自动/慢速/实时/暂停/快进；自定义每步间隔，修改立即唤醒等待中的循环（在途步骤先完成）。自动模式无人观看时约 5 秒一步，1 位观众按实时间隔运行，观众越多会逐步放慢，最多 180 秒一步；每步 30 个虚拟分钟，模型响应耗时可能限制实际速度。
- **时间与天气**：向未来跳转并暂停、天气类型/温度/描述。跳时不补算沿途活动与报告，要补算请用快进；天气下一虚拟日重新生成。
- **NPC**：新增、完整人格编辑、位置/活动/心情/精力/休息/启停。停用保留历史，不允许把普通用户改成管理员或修改其分身。
- **校园活动**（原「场景布置」）：在现有地点布置活动，设置描述、标签与时长，支持提前结束。
- **API 配置**：**LLM 总开关**、LLM 地址、强/经济模型、API Key，知乎 Access Secret 和 OAuth app ID/key。密钥不回显，留空保留，勾选清除才移除。更换 LLM 地址须重新输入 Key。关闭 LLM 开关后角色只按日程与规则行动（对话、反思、匹配报告跳过），适合省额度或离线演示。

后台设置加密保存在数据卷 `admin-settings.enc`，重启自动恢复，并优先于环境中的同名设置。备份数据卷时保留该文件及 `SESSION_SECRET`；更换 SESSION_SECRET 后原文件无法解密。开发模式下知乎仍使用 Mock，真实接入需配置 `DEV_MODE=false`。
现有 `X-Admin-Token` 运维脚本继续可用。普通用户没有世界控制权限；管理会话 8 小时过期，Cookie 写操作仅接受同源。

## 九、运行约束

- **`--workers 1` 是硬约束**：单 Ticker + SQLite 单写者。多 worker 会得到两个互相覆盖的世界。
- SQLite 用 WAL + `NullPool` + 读写事务分离；写事务使用 `BEGIN IMMEDIATE`。不要在 session 上手动 `BEGIN IMMEDIATE`——会让 `commit()` 退化成 rollback。
- 一个页面 = 一个 SSE 连接 = 一个观众；观众数直接影响 Ticker 速率。
- LLM 预算 ≤ 300 次/虚拟日；`fail_streak` 超阈值触发 `degraded`（角色退回日程行动）。
- 耳语每天 3 次，≤80 字；分身可以拒绝。
