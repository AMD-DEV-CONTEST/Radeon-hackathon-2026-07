---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 42a94a45815d4753c46a791703eadf62_1f9880e084ff11f1afee525400f8a581
    ReservedCode1: 8VvCa/O8070pl9NJ3brCI2QMGBVNXj2RO696qlYxnvBYrS4IU82c3SVrCWmEBebw1KE5hKl31CaPCRVkaUbFsZ0EuGSZK0ao+WrpbKUQTu+M4z3bRnnWAvnHrelKzd9ojUnl6M/apI9FUrV43f+uqryQAeiXv5lfvkkPBFvmhuyJuuqs1e6WiFTOnww=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 42a94a45815d4753c46a791703eadf62_1f9880e084ff11f1afee525400f8a581
    ReservedCode2: 8VvCa/O8070pl9NJ3brCI2QMGBVNXj2RO696qlYxnvBYrS4IU82c3SVrCWmEBebw1KE5hKl31CaPCRVkaUbFsZ0EuGSZK0ao+WrpbKUQTu+M4z3bRnnWAvnHrelKzd9ojUnl6M/apI9FUrV43f+uqryQAeiXv5lfvkkPBFvmhuyJuuqs1e6WiFTOnww=
---

# XAI 双核融合系统 — 用户指南

> 版本：v3（2026-07-21）
> 适用于：macOS 用户，单机单用户部署

---

## 1. 系统简介

XAI 是一个**本地私有、模型无关**的 AI Agent 操作系统。它围绕"双核融合"架构构建：

| 内核 | 定位 | 擅长领域 |
|------|------|----------|
| **Hermes** | 通用推理引擎 | 对话、分析、规划、联网搜索、GEPA 自进化 |
| **Grok Build** | 代码工程引擎 | 代码生成、构建、重构、安全扫描 |

两个内核**无层级关系，完全并列**。内置的 **Intent Router（意图路由器）** 会自动分析你的输入，将任务分发到最适合的内核执行。

### 核心特性

- **流式 SSE 对话** — 逐字推送，支持多轮上下文
- **可视化工作流画布** — 20+ 节点类型，拖拽连线上 DAG，拓扑排序执行
- **8 层元认知记忆** — SQLite 持久化，跨会话联想召回
- **Guardian 治理闸门** — P0/P1/P2 三级风险拦截，高危操作需人工审批
- **硬沙箱执行** — nsjail → firejail → sandbox-exec → setrlimit 四级回退
- **可观测性追踪** — 每次工具调用/模型推理的真实耗时与结果记录
- **CI/CD 集成** — GitHub Actions 自动跑后端 pytest + 前端 build
- **纯本地隐私** — 记忆/会话/项目全部本地 SQLite，除模型端口外无任何主动上传

### 系统架构总览

```
控制台（xai-frontend，7 模块: 对话/任务/专家团/自动化/定时/画布/管理）
    │
    ▼  HTTP/SSE (:8000)
server_xai.py (ThreadingHTTPServer)
    │
    ▼
XAIEngine (编排引擎)
    ├── IntentRouter   → 自动分类任务
    ├── Guardian       → 风险分级 + 审批
    ├── ControlLoop    → 认知控制环 (/loop)
    ├── HermesAdapter  → DeepSeek 通用推理
    ├── OpenClawAdapter → 文件/终端/浏览器/扫描
    └── GrokBuildBridge → grok 二进制子进程
```

---

## 2. 快速开始

### 2.1 启动服务

**推荐方式（自动注入 API Key）**：

```bash
cd /Users/Admin/Desktop/mask/xai
bash /tmp/start_xai.sh
```

**备选方式**：

```bash
cd /Users/Admin/Desktop/mask/xai
DEEPSEEK_API_KEY=sk-xxxxxxxx python3 server_xai.py
```

浏览器打开 **[http://localhost:8000](http://localhost:8000)**。

### 2.2 确认系统正常

在浏览器中访问 `/api/status`，或直接在对话中输入 `/status`，应返回各模块状态。

### 2.3 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEEPSEEK_API_KEY` | （无） | DeepSeek API Key；缺失时降级为 StubBackend（离线模式） |
| `XAI_HOME` | `~/.xai` | 所有数据的根目录 |
| `XAI_WORKSPACE` | `$XAI_HOME/workspace` | 文件操作工作区 |
| `XAI_PORT` | `8000` | HTTP 服务端口 |
| `XAI_HOST` | `localhost` | 绑定地址 |

### 2.4 第一次对话

在输入框中输入任意问题，按 `Cmd+Enter` 发送。例如：

```
帮我写一个 Python 冒泡排序函数
```

系统会自动识别这是代码工程任务，路由到 Grok Build 内核执行，并在交付物面板展示生成结果。

---

## 3. 双模编辑器（Chat / Studio 模式）

XAI 提供两种编辑模式，满足不同工作场景：

### 3.1 Chat 模式

**统一对话台**是日常使用的入口。你在这里进行自由对话、提问、代码生成、联网搜索。

**界面布局**（三栏）：

```
┌──────────┬─────────────────────┬────────────┐
│  会话栏   │      对话区域        │   成果区    │
│          │  - SSE 流式回复      │  - 拓扑     │
│ 切换/新建 │  - 斜杠命令芯片       │  - 执行过程  │
│          │  - 模型选择器         │  - 交付物    │
│          │  - 审批卡片           │  - 进化     │
└──────────┴─────────────────────┴────────────┘
```

**快捷操作**：

| 快捷键 | 功能 |
|--------|------|
| `Cmd+Enter` | 发送消息 |
| `Esc` | 中止生成 |
| `Cmd+K` | 聚焦输入框 |

**内核切换**：输入框上方的选择器可切换 `🧠 Hermes` / `⚙ Grok Build` / `自动`。

### 3.2 Studio 模式（画布）

**工作流画布**让你通过拖拽节点、连线编排复杂的自动化流程。

**节点类型**（20+）：

| 类别 | 节点 | 说明 |
|------|------|------|
| 基础 | `input`、`output` | 输入/输出 |
| 对话 | `chat` | 通用对话节点 |
| 代码 | `gb_gen`、`gb_refactor`、`gb_test` | Grok Build 代码生成/重构/测试 |
| 推理 | `react`、`router` | 推理链、路由分发 |
| 知识 | `kb`、`mem_query` | 知识库检索、记忆查询 |
| 执行 | `exec`、`file`、`scan`、`git` | 命令/文件/扫描/版本控制 |
| 工具 | `skill`、`mcp` | 技能调用、MCP 工具 |
| Agent | `agent_hermes`、`agent_grok`、`agent_pm` | 三 Agent 类型 |
| 控制流 | `condition`、`loop` | 条件分支、循环 |

**画布操作**：

- 从左侧面板**拖拽节点**到画布
- 连线构建 DAG（Kahn 拓扑排序执行）
- 右键节点：克隆 / 单独运行 / 删除
- 点击「运行」→ SSE 逐节点执行反馈
- 点击「保存」命名工作流，可在「我的工作流」面板管理

### 3.3 分屏与双向同步

**成果区 4 子面板**（Chat 模式右侧栏）：

1. **拓扑（topo）** — 对话驱动的 DAG 实时展示；Intent Router 分类结果自动绘制为可视化节点网络
2. **执行过程（process）** — 时间线：意图识别 → 安全审查 → 代码生成 → 交付物 → 完成
3. **交付物（deliver）** — 代码/文件卡片，支持 📂 打开 / 📋 复制 / ⬇️ 下载
4. **进化（evolve）** — GEPA 自蒸馏入口，可将对话经验固化为技能

**双向同步**：在 Chat 模式中通过 Intent Router 生成的结构可以直接推送到画布；画布中的执行结果也会回显到对话流中。

---

## 4. 记忆系统

### 4.1 8 层架构

XAI 的记忆系统基于 SQLite 持久化，共 8 个语义层：

| 层 | 名称 | 用途 | 生命周期 |
|----|------|------|----------|
| L1 | `working` | 当前任务的工作记忆 | 单次任务内 |
| L2 | `short_term` | 短期记忆（最近对话） | 会话级 |
| L3 | `long_term` | 长期记忆（consolidate 后固化） | 持久 |
| L4 | `anchor` | 知识锚点（关键事实/原则） | 持久 |
| L5 | `reflection` | 反思层（自我复盘内容） | 持久 |
| L6 | `causal` | 因果链（A 导致 B 的逻辑） | 持久 |
| L7 | `user_profile` | 用户画像（偏好/习惯） | 持久 |
| L8 | `failure_correction` | 失败修正记录 | 持久 |

**数据存储**：`~/.xai/memory.db`（单一 SQLite 文件，含全 8 层）。

### 4.2 记忆命令

在对话中直接使用以下斜杠命令管理记忆：

| 命令 | 功能 |
|------|------|
| `/remember <内容>` | 手动写入一条记忆 |
| `/recall <关键词>` | 搜索记忆 |
| `/diagnose` | 记忆系统健康体检 |

### 4.3 记忆仪表盘

API 端点 `GET /api/memory/stats` 返回各层统计：

```json
{
  "layers": {
    "working": 3,
    "short_term": 128,
    "long_term": 42,
    "anchor": 7,
    "reflection": 15,
    "causal": 9,
    "user_profile": 5,
    "failure_correction": 2
  }
}
```

**跨会话上下文召回**：`GET /api/memory/context?text=<query>` 返回 top-10 相关记忆，按子串匹配（40%）+ 关键词加权（40%）+ 时间衰减（20%）混合排序。

### 4.4 Project 隔离

每个 Project 拥有独立的记忆空间，切换项目后记忆召回自动过滤。Project 管理通过 `/api/projects` 系列端点操作。

---

## 5. 安全沙箱

### 5.1 Guardian 治理闸门

每次工具调用前，Guardian 自动评估风险等级：

| 等级 | 行为 | 示例 |
|------|------|------|
| **P0（致命）** | 拦截 → 入审批队列 → 需人工 `/approve` 后真正执行 | `rm -rf`、`force push`、`delete_file`、`secret_write` |
| **P1（高危）** | 记录 + 提示，可自动放行但留痕 | `run_command`、`network`、`install_pkg` |
| **P2（常规）** | 自动通过 | `read_file`、`compute` |

**内容级识别**：引擎会主动扫描用户输入中的危险模式：
- `rm -rf / sudo rm / mkfs / format / force push / drop table` → P0
- `删除文件 / del / shutil.rmtree / os.remove` → P0
- `执行命令 / exec / bash / powershell` → P1
- `联网 / http(s):// / curl / fetch` → P1

**审批流程**：P0 拦截后弹审批卡片，用户输入 `/approve <id>` 后，系统**真正重执行原意图**（非仅仅标记）。

### 5.2 硬沙箱（Hard Sandbox）

代码执行在四级沙箱中运行，按可用性自动回退：

```
nsjail（Linux 容器隔离）
  → firejail（Linux 用户态沙箱）
    → sandbox-exec（macOS Seatbelt）
      → setrlimit（软限制兜底）
```

**限制参数**（nsjail 模式）：
- 时间限制：60s
- 内存上限：512MB
- CPU 限制：50ms/s
- 网络隔离：clone_newnet = true

**状态查询**：`GET /api/system/sandbox` 返回当前沙箱模式与后端：

```json
{
  "mode": "soft",
  "backend": "setrlimit",
  "message": "无容器沙箱，使用 setrlimit 软限制"
}
```

> macOS 上默认走 sandbox-exec → setrlimit 软退路径。Linux 上安装 nsjail 后自动升级为 hard 模式。

### 5.3 路径穿越防护

多层防护确保文件操作不越界：

1. **OpenClawAdapter._safe_path**：所有文件路径必须位于 workspace 内，否则抛 `ValueError`
2. **server_xai 文件上传**：`os.path.basename()` 剥离路径，拒绝 `.` / `..`
3. **server_xai 文件保存**：扩展名仅允许 `[a-zA-Z0-9.]`，截断 12 字符；文件名用 `isalnum() + ._-` 净化

### 5.4 API Key 安全

- **存储**：`DEEPSEEK_API_KEY` 仅在 `~/.zshrc` 中（不落盘项目目录）
- **传输**：启动器 `xai_go.sh` 解析后 `export` 注入子进程
- **掩码**：`/api/models/list` 和 `/api/status` 永远返回掩码版 Key（如 `sk-d***fd55`）

---

## 6. 可观测性

### 6.1 Tracer 追踪管线

`core/observability.py` 提供了完整的追踪系统，记录每次工具调用和模型推理的：

- 工具名称（`tool_name`）
- 追踪 ID（`trace_id`）
- 开始/结束时间戳（`start_ts / end_ts`）
- 耗时（`duration_ms`）
- 成功/失败状态（`success`）
- 输出大小（`output_size`）
- 错误信息（`error_msg`）

### 6.2 错误追踪面板

前端内置**错误追踪面板**（`error-panel` 路由）：

- **五列表格**：时间 / 组件 / 类型 / 消息 / 追踪 ID
- **自动刷新**：每 5 秒
- **可展开详情行**
- **中文组件名映射**

**API 端点**：`GET /api/system/errors?limit=20`

```json
{
  "errors": [
    {
      "trace_id": "uuid",
      "tool_name": "deepseek_chat",
      "start_ts": 1753100000.0,
      "end_ts": 1753100005.0,
      "duration_ms": 5000.0,
      "success": false,
      "error_msg": "Connection timeout"
    }
  ],
  "total": 1,
  "filtered": 0
}
```

### 6.3 系统诊断

| 命令 | 功能 |
|------|------|
| `/status` | 系统综合状态（引擎/模型/记忆/审批/项目） |
| `/diagnose` | 系统体检（各模块健康状态） |

### 6.4 沙箱状态

`GET /api/system/sandbox` 返回当前沙箱模式，便于确认执行环境的隔离等级。

---

## 7. CI/CD

### 7.1 GitHub Actions 流水线

`.github/workflows/ci.yml` 定义了自动化 CI 流程：

```yaml
触发条件：
  - push 到 main 分支
  - 向 main 分支发起 Pull Request

作业步骤：
  1. Checkout 仓库
  2. 安装 Python 3.11 + pytest
  3. 运行后端测试：python3 -m pytest tests/ -q
  4. 安装 Node 18
  5. npm ci（xai-frontend）
  6. npx vite build（纯 Web 模式构建）
```

### 7.2 本地测试

```bash
# 单元测试（73 项，无需联网）
python3 -m pytest tests/ -q

# 端到端自测（需服务运行在 8000）
python3 tests/selftest_e2e.py          # 13 项核心流程
python3 tests/selftest_e2e_round2.py   # 13 项命令全量 + 边界 + 并发
python3 tests/selftest_files.py        # 文件上传/保存/打开
python3 tests/selftest_memory_core.py  # MemoryCore 8 层 CRUD
python3 tests/selftest_workflow.py     # 画布工作流端到端
```

### 7.3 Rust 组件测试

```bash
cd rust/xai-grok-guardian && cargo test   # Guardian 治理
cd rust/xai-grok-reason   && cargo test   # Reason 思考
cd rust/xai-grok-meta     && cargo test   # Meta 元认知（8 测通过）
cd rust/xai-grok-runner   && cargo test   # Runner 长任务（7 测通过）
```

---

## 8. 提问技巧

### 8.1 让 Intent Router 帮你分类

系统的 Intent Router 会自动识别以下意图类型：

| 意图类型 | 触发词/场景 | 路由目标 |
|----------|------------|----------|
| `code_dev` | 写代码、改 bug、重构、写测试 | Grok Build |
| `browser` | 搜索、查资料、最新消息 | 联网搜索 |
| `research` | 调研、对比分析、综述 | 联网搜索 |
| `memory` | 回忆、查找之前的内容 | 记忆系统 |
| `general` | 对话、问答、解释概念 | Hermes |

**高效提问建议**：明确说出你要做什么，系统会自动路由。例如：
- "帮我写一个快排" → `code_dev`
- "最新的 Python 3.13 有什么新特性" → `browser`
- "我之前问过的那个关于 XAI 架构的问题" → `memory`

### 8.2 斜杠命令速查

共 16 个内置斜杠命令，直接在对话中输入即可：

| 命令 | 功能 |
|------|------|
| `/help` | 命令列表 |
| `/status` | 系统状态 |
| `/diagnose` | 系统体检 |
| `/clear` | 清空当前会话 |
| `/models` | 模型列表 |
| `/skill <name>` | 调用已注册技能 |
| `/mcp` | MCP 工具列表 |
| `/task <描述>` | 创建任务 |
| `/automate <描述>` | 创建自动化 |
| `/remember <内容>` | 写入记忆 |
| `/recall <关键词>` | 召回记忆 |
| `/scan <路径>` | 安全扫描 |
| `/evolve` | GEPA 自进化 |
| `/channels` | 频道列表 |
| `/approve <id>` | 批准 P0 审批 |
| `/reject <id>` | 拒绝 P0 审批 |

### 8.3 文件引用

将文件拖拽到对话输入框，自动生成 `@file:` 引用，系统会读取文件内容并纳入上下文。

### 8.4 控制环（/loop）

如果你需要更深入的推理（思考预算 + Brier 校准 + L8 四维审计），使用 `/loop` 命令：

```
/loop 分析这个架构设计的潜在风险
```

这会触发完整的 6 步认知控制环：meta 外环 → reason 思考 → meta 校准 → guardian 审批 → execute 执行 → meta 审计。

---

## 9. FAQ

### Q1：对话没反应？

检查顶栏模型选择器是否显示绿色圆点（在线状态）。若无云端模型可用，请确认 `DEEPSEEK_API_KEY` 环境变量已正确设置。

### Q2：为什么有时候模型回答为空？

非流式端点 `/api/chat/send` 对通用对话可能返回空答案（已知限制）。建议始终使用默认的 SSE 流式对话（直接按 `Cmd+Enter` 发送）。

### Q3：画布节点报错？

查看右侧日志面板，失败节点会显示诊断建议和重试按钮。常见原因：节点配置参数缺失、连线断链（orange）、环路检测（red）。

### Q4：如何保存工作流？

画布顶部点击「保存」，输入名称。「我的工作流」面板可管理所有已保存的画布。

### Q5：XAI.app 双击启动后为什么没有模型？

这是已知问题：`xai_launcher.py` 不解析 `~/.zshrc`，GUI 环境下可能没有 `DEEPSEEK_API_KEY`。建议使用 `bash /tmp/start_xai.sh` 启动。

### Q6：记忆存在哪里？隐私安全吗？

所有记忆存储在 `~/.xai/memory.db`（本地 SQLite）。**除 DeepSeek API 端口外，系统无任何主动上传或同步。** 云模型仅连模型端口出网。

### Q7：如何切换模型？

- 前端：顶栏模型选择器下拉切换
- API：`GET /api/models/activate/<model_id>`
- 添加新模型：`POST /api/models/add`

注意：当前仅 DeepSeek 真实接入，Ollama 本地模型支持尚未完成集成。

### Q8：Grok Build 提示"不可用"怎么办？

Grok Build 依赖本机 `~/.grok/bin/grok` 二进制。如果没有安装，系统会自动降级到 Hermes 内核处理代码任务。代码生成质量略降但功能可用。

### Q9：如何查看系统错误？

在控制台中切换到「错误追踪」面板（`error-panel` 路由），或直接调用 `GET /api/system/errors?limit=20`。

### Q10：如何确认当前沙箱模式？

`GET /api/system/sandbox` 返回当前沙箱模式（hard/soft）和后端类型。macOS 默认为 `sandbox-exec → setrlimit` 软退路径。Linux 上安装 nsjail 后自动升级为 hard 模式。

### Q11：可以多人使用吗？

当前为单机单用户设计。企业多用户 / SSO / RBAC 尚未实现。

### Q12：支持哪些浏览器？

推荐 Chrome 90+ / Edge 90+ / Safari 15+ / Firefox 90+。需支持 `fetch` + `ReadableStream`（SSE 流式）。强刷：`Cmd+Shift+R`。

---

## 附录 A：安全审计摘要（2026-07-21）

> 来源：`from_mavis.log`

### NPM Audit（xai-frontend）

**初始**：9 个漏洞（1 moderate / 7 high / 1 critical）
**最终**：0 个漏洞（全部修复）

关键修复：
- `electron`：28.3.3 → 43.1.1（含 17 个安全公告）
- `tar`：修复 11 个 CRITICAL 级别公告（文件覆盖/路径穿越/符号链接投毒）
- `glob`：10.4.x → 10.5.0
- Vite：5.x → 8.1.5

### Pip Audit（Python 环境）

**初始**：10 个漏洞（pip 24.0 + setuptools 69.1.0）
**最终**：0 个漏洞（pip 26.1.2 + setuptools 83.0.0）

### 硬沙箱（P0-K3b）

- `core/execution/action_bus.py`：nsjail → firejail → sandbox-exec → setrlimit 四级回退
- `core/execution/nsjail.cfg`：容器配置（60s 限时 / 512MB / 50ms/s CPU / 网络隔离）
- `server_xai.py`：`GET /api/system/sandbox` 端点
- macOS 上无 nsjail/firejail，自动回退到 sandbox-exec → setrlimit 软退路径

### 错误追踪面板（P2-O2）

- `core/observability.py`：全局 Tracer，deque 环形缓冲区（maxlen=1000）
- `xai-frontend`：ErrorPanel 五列表格 + 5s 自动刷新 + 可展开详情
- API：`GET /api/system/errors?limit=20`

---

## 附录 B：文件布局

```
~/.xai/
├── memory.db              # 8 层元认知记忆
├── memory/memos.db        # MemOS 兼容记忆（双轨）
├── sessions.db            # 会话历史
├── projects.db            # 项目管理
├── models.json            # 模型注册表
├── loop_safety.json       # Loop Safety 配置
├── server.pid             # 运行时 PID
└── workspace/             # 工作区
    ├── uploads/           # 用户上传
    ├── artifacts/         # 生成产物
    ├── knowledge/         # 本地知识库
    ├── hermes_skills/     # Hermes 技能
    ├── hermes_evo/        # GEPA 待复审变异
    └── cron/              # 定时任务
```

---

## 附录 C：斜杠命令完整列表

| 命令 | 参数 | 功能 | 审批 |
|------|------|------|------|
| `/help` | — | 显示命令列表 | 无 |
| `/status` | — | 系统综合状态 | 无 |
| `/diagnose` | — | 系统体检 | 无 |
| `/clear` | — | 清空当前会话 | 无 |
| `/models` | — | 模型列表 | 无 |
| `/channels` | — | 频道列表 | 无 |
| `/skill` | `<name>` | 调用技能 | 无 |
| `/mcp` | — | MCP 工具列表 | 无 |
| `/task` | `<描述>` | 创建任务 | 无 |
| `/automate` | `<描述>` | 创建自动化 | 无 |
| `/remember` | `<内容>` | 写入记忆 | 无 |
| `/recall` | `<关键词>` | 召回记忆 | 无 |
| `/scan` | `<路径>` | 安全扫描 | P2 |
| `/evolve` | — | GEPA 自进化 | 无 |
| `/approve` | `<审批ID>` | 批准 P0 审批 | — |
| `/reject` | `<审批ID>` | 拒绝 P0 审批 | — |

---

*文档结束。如有问题请在对话中直接询问。*
*（内容由AI生成，仅供参考）*
