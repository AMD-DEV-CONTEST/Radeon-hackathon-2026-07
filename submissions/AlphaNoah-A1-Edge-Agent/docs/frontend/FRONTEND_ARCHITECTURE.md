# AlphaNoah A1 Edge Agent Frontend Architecture

## 1. 文档状态

- 任务：Frontend Task F00
- 审计基线：`3d16acd`（`feat: add web adapter boundary for demo runtime`）
- 审计日期：2026-07-28
- 性质：架构与边界设计，不是实现说明

本文只记录仓库事实、前端边界和后续实施建议。本任务没有修改 Runtime、
SQLite Schema、状态机、现有 API 行为或依赖。

## 2. 结论摘要

推荐在仓库根目录新增独立 `frontend/` 源码目录，使用 React、TypeScript、
Vite、React Router、Motion、Lucide 和原生 CSS/CSS Modules。Node.js 只用于
本地开发、测试和构建；生产环境由 Python HTTP 服务托管构建产物，因此 Node.js
不是生产运行时依赖。

推荐生产拓扑为同源单端口：

```text
Browser
  |
  | GET /, /assets/*             GET/POST /api/*
  v
Python HTTP boundary on 127.0.0.1:8090
  |                                  |
  | static asset resolver            | existing request handler
  |                                  v
  |                       RestaurantAirconWebAdapter
  |                                  |
  +----------------------------------v
                         RestaurantAirconGoldenPath
                                    |
                                    v
                         Runtime / state machine / SQLite
```

静态资源解析属于 HTTP 层。`RestaurantAirconWebAdapter` 必须继续保持
JSON-neutral，不应读取文件、解析前端路由、持有 UI 状态或直接访问 SQLite。

## 3. 当前仓库审计

### 3.1 当前 Web 入口

仓库中有两个独立的标准库 HTTP 入口。

| 入口 | 文件 | 默认地址 | 当前职责 |
|---|---|---|---|
| QR 申报 Demo | `src/alphanoah_a1/web.py` | `127.0.0.1:8080` | 在 `/report` 提供内联 HTML/CSS 表单，提交 Event |
| JSON Web Adapter | `src/alphanoah_a1/web_api.py` | `127.0.0.1:8090` | 在 `/api/*` 提供 7 个 JSON endpoint |

两者都使用 `BaseHTTPRequestHandler` 和 `ThreadingHTTPServer`，都强制绑定
`127.0.0.1`，都限制请求体为 16 KiB、socket 读取超时为 5 秒，并关闭默认请求
日志。两个入口使用不同默认数据库文件：

- QR Demo：`tmp/alphanoah_qr_demo.sqlite3`
- JSON API：`tmp/alphanoah_web_api.sqlite3`

因此，即使两个进程同时启动，它们默认也不会共享事件数据。后续若保留两个入口
并要求看到同一现场状态，必须显式传入同一个 `--db`；不能由前端自行合并两个
数据源。

### 3.2 Web Adapter 实现方式

`RestaurantAirconWebAdapter` 位于
`src/alphanoah_a1/web_adapter.py`，是一个 JSON-neutral 应用适配器。当前调用链
是：

```text
WebAdapterRequestHandler
  -> RestaurantAirconWebAdapter
  -> RestaurantAirconGoldenPath
  -> existing Runtime / Store / Audit
```

其边界特征：

- HTTP handler 负责路由、JSON 解码、请求大小、Content-Type 和安全错误响应；
- Adapter 负责精确输入字段、字符串上限、安全输出投影和领域错误映射；
- 所有业务写入通过现有 Golden Path/Runtime 方法完成；
- Web 模块中没有直接 SQL，也不直接调用 Provider；
- GET analysis 只读取已持久化结果，不触发模型分析；
- 输出会过滤本机路径、常见 secret 形态和不安全引用；
- 每个 Event 目前只接受最多一个 Decision、每个 Decision 最多一个 Task；发现
  不一致关系时返回 `INTERNAL_ERROR`，不会在前端猜测。

当前 API 只覆盖 Restaurant A08 空调演示场景。它不是通用 Workspace API。

### 3.3 HTTP 服务启动与关闭

原生启动方式：

```powershell
$env:PYTHONPATH = "src"
python -m alphanoah_a1.web_api --db tmp/alphanoah_web_api.sqlite3
```

```bash
PYTHONPATH=src python3 -m alphanoah_a1.web_api \
  --db tmp/alphanoah_web_api.sqlite3
```

可使用 `--port` 覆盖默认端口；CLI 接受 `1..65535`。测试通过
`create_server(..., port=0)` 让操作系统分配临时端口。

主进程在当前线程调用 `serve_forever()`。收到 `KeyboardInterrupt` 后进入
`finally` 并调用 `server_close()`。测试中的短生命周期服务运行在单独线程，
关闭顺序是 `shutdown()`、等待 server 线程退出、再 `server_close()`。
`daemon_threads=False` 且 `block_on_close=True`，所以关闭时会等待活动请求线程。

当前 CLI 没有进程信号协调、systemd/Windows Service 包装或生产级 graceful
shutdown 契约。

### 3.4 静态资源托管能力

当前没有通用静态资源托管能力：

- `web.py` 只返回 Python 字符串中内联的 HTML/CSS；
- `web_api.py` 所有非已知 API 路径均返回 JSON 404；
- 仓库没有 `frontend/`、`static/`、`package.json`、Vite 配置或构建产物；
- 没有 MIME 映射、静态缓存策略、路径穿越防护或 SPA route fallback。

因此不能把“已有一个 HTML 表单”等同于“已有 SPA 静态托管”。

### 3.5 当前公开 API

当前 JSON 服务公开以下 endpoint，完整字段见
`docs/frontend/API_CONTRACT_DRAFT.md`：

| Method | Path | 性质 |
|---|---|---|
| POST | `/api/events` | 创建限定场景 Event |
| GET | `/api/events/{event_id}` | Event/Analysis/Decision 安全摘要 |
| GET | `/api/events/{event_id}/analysis` | 已持久化分析、Skill 和知识来源 |
| POST | `/api/events/{event_id}/review` | 人工 approve/reject |
| GET | `/api/events/{event_id}/task` | 读取关联 Task 摘要 |
| POST | `/api/tasks/{task_id}/evidence` | 提交纯文本 Evidence |
| GET | `/api/events/{event_id}/timeline` | 安全 Audit 时间线 |

没有 Event 列表、通知列表、完整行动卡、健康检查、管理页读取 API、静态资源路由、
WebSocket 或 conversation API。

### 3.6 Runtime 数据边界

Runtime 的持久化对象包括 Event、Decision、HumanReview、Task、Evidence、
Review、Notification 和 AuditRecord。`AnalysisResult` 是 Provider/Runtime
之间的结构化分析契约，不是独立 SQLite 实体；成功分析后，字段分别进入 Event
和 Decision。SQLite 每类对象保存索引列和 JSON payload。

前端不得：

- 根据动画或页面步骤写回自创业务状态；
- 直接读取 SQLite；
- 把 Pulse 的展开/关闭状态解释为 Event 已处理；
- 把 Notification 的 UI 已读状态解释为 `DELIVERED`；
- 在 GET 请求中触发分析、Task 创建、Task 开始或最终复查；
- 从 Event 状态反推不存在的 Decision、Task 或 Evidence。

### 3.7 测试、静态检查与启动命令

仓库当前事实：

- Python 要求 `>=3.11`；
- `pyproject.toml` 的项目依赖为空；
- 正式回归命令是标准库 `unittest`；
- `pyproject.toml` 保留 pytest testpaths 配置，但仓库没有声明 pytest 依赖；
- 没有正式配置 ruff、mypy、pyright 或其他 lint/type-check 命令。

现有验证命令：

```text
python -m unittest discover -s tests -v
python -m compileall -q src tests
git diff --check
```

主要入口：

```text
python -m alphanoah_a1
python -m alphanoah_a1.demo
python -m alphanoah_a1.web
python -m alphanoah_a1.web_api
```

### 3.8 Docker 与原生环境

仓库没有 Dockerfile、Compose 文件或容器启动脚本。Docker 相关内容只存在于
历史审计/待确认文档，不能视为本仓库可运行能力。

当前受支持的仓库运行边界是 Windows/Linux 原生 Python。路径处理使用
`pathlib.Path`，启动文档分别使用 PowerShell 的 `$env:PYTHONPATH` 和
Linux/macOS 的 `PYTHONPATH=src`。前端构建边界必须继续使用跨平台 npm scripts，
不得依赖 bash-only 的复制或删除命令。

## 4. 前端接入不能破坏的边界

1. **Runtime 是唯一业务状态机。** UI 只显示 Runtime 状态和派生呈现状态。
2. **Human Review 必须显式。** approve/reject 继续调用现有 review endpoint；
   不允许 Pulse 自动批准。
3. **读请求不得产生业务副作用。** 页面刷新、轮询和预加载不能触发模型、
   Notification 创建、Task 创建或状态迁移。
4. **Adapter 保持 JSON-neutral。** 静态文件和 SPA fallback 不能进入
   `RestaurantAirconWebAdapter`。
5. **SQLite 只经 Store/Runtime 访问。** 不为前端加入旁路查询或新 schema。
6. **安全投影继续生效。** 不向浏览器返回 prompt、原始模型输出、secret、
   本机路径、完整 Audit details 或任意 metadata。
7. **限定场景不能伪装成通用能力。** 当前 API 只支持 A08/air_conditioner。
8. **Notification 不是已送达消息。** 当前 outbox 只持久化 `CREATED` intent，
   没有外部投递。
9. **Provider discovery 是只读探测。** Management UI 不得自动安装服务、
   下载模型或静默切换 Provider。
10. **同一数据库必须显式。** 多个 HTTP 入口不应各自展示为同一实时系统。

## 5. CORS、路由、静态路径和端口风险

### 5.1 CORS 与 CSRF

当前 API 不发送 `Access-Control-Allow-Origin`，`OPTIONS` 返回 405。浏览器从
Vite 默认端口直接请求 8090 会被 same-origin policy 阻止。

推荐：

- 开发环境由 Vite dev server 把 `/api` 代理到 `127.0.0.1:8090`；
- 生产环境由 Python 在同一 origin 托管 SPA 和 `/api`；
- F01 不启用宽泛 CORS；
- 若未来必须跨 origin，再独立设计 origin allowlist、认证和 CSRF，不使用 `*`。

### 5.2 SPA 路由回退

当前任意未知 GET 都是 JSON 404。后续静态边界应按以下顺序处理：

1. `/api` 和 `/api/*` 永远进入 API router；未知 API 保持 JSON 404；
2. 已存在静态文件按精确路径返回；
3. 只有无文件扩展名的浏览器导航 GET 才 fallback 到 `index.html`；
4. 缺失的 `.js`、`.css`、图片、source map 不得 fallback 成 HTML；
5. POST/PUT/PATCH/DELETE/OPTIONS/HEAD 不使用 SPA fallback。

### 5.3 静态路径

静态 resolver 必须：

- 使用显式、只读的 build root；
- URL decode 后拒绝绝对路径、`..`、NUL、反斜杠逃逸和 root 外 symlink；
- 不列目录，不返回 dotfile；
- 为 HTML 使用 `no-cache`，为带内容 hash 的 assets 使用
  `public, max-age=31536000, immutable`；
- 设置正确 MIME、`nosniff`、CSP、Referrer-Policy 和 frame policy；
- 生产构建默认不发布 source map。

### 5.4 端口

已知默认端口：

- 8080：QR HTML Demo；
- 8090：JSON Web Adapter；
- 8000：示例 vLLM endpoint；
- 11434：示例 Ollama endpoint；
- 5173：Vite 常见开发端口，当前仓库未占用。

绑定冲突当前会直接产生 `OSError`，没有友好恢复。生产建议使用 8090 作为统一
SPA/API 入口，并继续允许 `--port` 覆盖。不要让 Vite dev server 成为部署入口。

## 6. 推荐目录结构

仓库当前没有 JavaScript 工程，也没有需要共置的 Python package 前端资源，
所以独立 `frontend/` 是最清晰的所有权边界：

```text
frontend/
  index.html
  package.json
  package-lock.json
  tsconfig.json
  tsconfig.app.json
  vite.config.ts
  src/
    main.tsx
    app/
      App.tsx
      router.tsx
      providers.tsx
    components/
      primitives/
      layout/
      feedback/
    features/
      workspace/
        components/
        models/
        routes/
      noah-pulse/
        components/
        policy/
      action-panel/
        components/
        models/
      management/
        digital-roles/
        skills/
        providers/
        edge-nodes/
        system-health/
    api/
      client.ts
      current-contracts.ts
      errors.ts
      mappers.ts
    hooks/
    styles/
      tokens.css
      globals.css
    test/
      fixtures/
      setup.ts
  public/
  tests/
  dist/                  # 生成物，不手工编辑
```

约束：

- `api/current-contracts.ts` 只描述已实现的 HTTP contract；
- 建议 contract 必须放在文档或带 `draft` 命名的文件中，不能让 UI 当作可调用；
- feature model 可以组合后端对象，但不能复制 Event/Decision/Task 状态机；
- `dist/` 是构建产物，不是源码；是否进入 release artifact 在 F01 决定；
- 不从 Python package import JSON schema 作为构建时捷径，避免 Node/Python 双运行时
  耦合。

## 7. 推荐技术栈

| 领域 | 选择 | 边界 |
|---|---|---|
| UI | React + TypeScript | TypeScript strict；不建立第二业务状态机 |
| Build | Vite | 只用于开发、测试和生成静态文件 |
| Routing | React Router | 两个一级空间；支持 Event deep link |
| Motion | Motion | 只做状态过渡；遵守 reduced motion |
| Icons | Lucide | 图标必须配文字或可访问名称 |
| Style | 原生 CSS variables + CSS Modules | 不引入完整企业 UI 框架 |
| Data access | 小型 typed fetch client | 不在第一版加入重型全局状态库 |
| Server state | feature hooks + request cache policy | 先轮询/手动刷新，不使用 WebSocket |
| Tests | Vitest + Testing Library | 后续 F01 才添加依赖 |

第一版不推荐 Redux、完整 design-system package、复杂 schema codegen 或
CSS-in-JS runtime。若后续请求一致性和缓存复杂度明显上升，再单独评估轻量
server-state library。

## 8. 静态托管建议边界

F01 可在 Python HTTP 层增加独立 `StaticAssetResolver`（名称仅为建议），并由
`web_api` 组合它。推荐 CLI 形态：

```text
python -m alphanoah_a1.web_api \
  --db tmp/alphanoah_web_api.sqlite3 \
  --static-root frontend/dist
```

是否把 static root 作为默认值，应在打包策略明确后决定。关键要求：

- 没有有效 build root 时 API 仍可独立启动；
- static root 无效时启动失败并给出不泄漏敏感路径的错误；
- Python 只读取构建产物，不执行 npm；
- release pipeline 先构建，再把产物作为明确 artifact 交给 Python；
- Runtime、Adapter 和 SQLite 不感知前端文件。

## 9. 实时性策略

第一版明确不使用 WebSocket。“现场实时状态”应定义为可见页面中的有限轮询：

- 页面可见且 Workspace 活跃时请求；
- 页面隐藏、设备离线或用户正在执行确认时降低/暂停轮询；
- 同一 Event 的写操作完成后立即重新读取；
- 失败使用有上限的退避，不能无限快速重试；
- UI 显示“最后更新于”和 stale 状态，不伪装成实时推送；
- 轮询请求必须是无副作用 GET。

轮询需要 Event 列表/Workspace read API；当前 API 尚不具备。

## 10. 明确不在第一版实施

- 用户系统、复杂权限后台；
- 3D 工厂；
- WebSocket；
- 小程序、Tauri；
- Skill 编辑器、Prompt 可视化编排；
- 多 Agent 群聊；
- 大型数据分析 Dashboard；
- 浏览器直接连接 Ollama/vLLM；
- 自动设备控制；
- Node.js 生产服务；
- 用前端状态替代 Runtime、Audit 或 HumanReview。
