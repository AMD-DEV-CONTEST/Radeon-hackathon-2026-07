# XAI 统一操作台 — 真实开源项目调研与差距改进报告

> 调研对象：`/Users/Admin/Desktop/mask/xai/vendor/` 下 5 个真实开源项目（OpenClaw / Hermes Agent / MemOS / OllamaFlow / OCTO_VEC）
> 对标基准：Open-WebUI / LibreChat / Dify / n8n / LangGraph / AutoGen / CrewAI（GitHub 明星项目）
> 目标：为本地 AI Agent 中台「XAI 统一操作台」提供结构化对比，产出按模块的差距与改进清单。
> 说明：本报告只做调研对比与建议，**不写实现代码**。所有结论引用真实文件路径 / 类名 / API。

---

## 0. 总览速读

| 维度 | XAI 现状 | 真实项目的「上市级」做法 | 最大差距 |
|---|---|---|---|
| 执行网关桥接 | `subprocess.run(["openclaw", ...])` 调 CLI | OpenClaw 真实提供 **Gateway HTTP/WebSocket RPC** + 官方 SDK | 用 CLI 而非 Gateway RPC，无结构化返回、无流式、无鉴权 |
| AI 推理桥接 | `hermes -z ... --yolo` 子进程 + 20s 超时 | Hermes 真实提供 **ACP HTTP Server**（`acp_adapter/server.py`） | 子进程脆弱、无结构化/流式、无凭证轮转 |
| 记忆系统 | 自研 SQLite（关键词检索） | MemOS 真实提供 **本地插件**（FTS5+向量混合检索、Cube、MemScheduler 异步） | 未用真实 MemOS，无向量、无 Cube、无异步、无巩固 |
| 前端画布 | 原生 JS 线性拖拽（无图） | OllamaFlow 用 **React Flow + Zustand + 拓扑执行 + 流式高亮** | 画布是摆设，非 DAG、无状态管理、无高亮 |
| 多 Agent 协作 | `/task` 返回静态计划文案 | OCTO_VEC 用 **PM 任务队列(FIFO) + 每 Agent 收件箱 + ATP SQLite** | 无真实编排、无消息队列、无成本追踪 |
| 前端 UX | `textContent` 直接写、无 Markdown | 标杆全部 **Markdown+LaTeX+代码高亮+流式+停止/重试+会话列表+移动端** | 输出不可读、无富文本、无会话管理 |
| 治理 / 可观测 | 内存字典审批队列（重启即丢） | Dify RBAC+审计日志+SSO；Open-WebUI OpenTelemetry；n8n 审计轨迹 | 无持久化审批、无追踪、无埋点 |

**一句话结论**：XAI 的 5 个 adapter 目前大多是「壳」——用 subprocess 调 CLI 或自研 SQLite 重写，并未真正接入 vendor 项目暴露的**生产级接口**（Gateway RPC / ACP Server / MemOS Plugin / React 画布引擎 / ATP 协调层）。这是 P0 级的结构性差距。

---

## 1. XAI 现状基线（先对齐现状）

### 1.1 桥接层现状（core/adapters/）

| 文件 | 桥接方式 | 真实能力 | 现状判断 |
|---|---|---|---|
| `core/adapters/openclaw_adapter.py` | `subprocess.run(["openclaw", tool, ...])` + 本地 Python 回退 | OpenClaw 是 Gateway 控制面，暴露 HTTP/WS RPC | 仅 CLI 外壳；本地回退绕过了真实 OpenClaw |
| `core/adapters/hermes_adapter.py` | `subprocess.Popen(["hermes","-z",...,"--yolo"])` + 20s 超时，失败回退 `model_backend` | Hermes 提供 ACP Server（`acp_adapter/server.py`）+ 凭证池 | 子进程脆弱、无流式/结构化、CLI 退出码易误判 |
| `core/adapters/memory_adapter.py` | **自研 SQLite 直连**（与 MemOS 无关，仅命名借用了 MemOS） | MemOS 提供本地插件（SDK/JSON-RPC/REST），混合检索 | 完全未用真实 MemOS，等于重写了一个弱版本 |
| `core/engine_xai.py` | SSE 事件生成器 `chat()`；规则关键词意图路由 `_classify_intent()`；内存审批队列 `_pending_approvals` | — | 事件级 SSE（intent/guard/progress/answer/done），**非 token 级流式** |

关键代码锚点：
- `openclaw_adapter.py:181 _execute_real()` → `subprocess.run(cmd_parts, ...)`（real 模式调 CLI）
- `hermes_adapter.py:91 _infer_real()` → `subprocess.Popen(args, ...)` + `communicate(timeout=20)`
- `memory_adapter.py:67 _init_db()` → 自建 `memories`/`memory_index` 表，关键词索引
- `engine_xai.py:126 chat()` → 事件生成器；`engine_xai.py:238 _classify_intent()` → 纯规则匹配（无任何 LLM/embedding）

### 1.2 前端现状（web/app.js + index.html）

- **SSE 消费**：`web/app.js:99` 用 `fetch` + `getReader()` 读 `data:` 事件，但只解析 `intent/guard/progress/answer/done`；`answer` 事件整段追加（`aiMsg.textContent += msg`），**无增量流式渲染、无 Markdown**。
- **代码块**：`appendCodeBlock()`（`web/app.js:355`）用 `div.textContent = code`，**无语法高亮、无复制语言标注**。
- **画布**：`dropNode()` / `drawConnections()`（`web/app.js:492`）仅做线性连线（节点 i 连 i+1），**非 DAG、无端口、无执行**。
- **无**：会话列表、移动端适配、停止按钮（仅前端 45s 超时）、Markdown/LaTeX、错误态骨架、加载骨架。
- 服务端：`server_xai.py` 用**标准库 http.server + SSE**（零依赖，但无并发/无鉴权/无背压）。

---

## 2. 5 个 vendor 项目逐项目调研

### 2.1 OpenClaw（执行网关 MCP/Skill/Git/扫描/命令）

**真实提供的能力**
- **Local-first Gateway（控制面）**：`src/gateway/server.ts` 起 HTTP + WebSocket RPC 服务（默认 `openclaw gateway --port 18789`）。这是接入它的**正确方式**，而非 CLI。
- **OpenAI 兼容 HTTP API**：`src/gateway/openai-http.ts`、`openresponses-http.ts` —— 可直接用 OpenAI SDK 调 OpenClaw。
- **官方 SDK**：`packages/sdk/src/client.ts`（`client.ts`/`event-hub.ts`/`transport.ts`）—— 程序化集成首选。
- **Gateway 协议校验**：`packages/gateway-protocol/src/`（schema/validators）。
- **生产级子能力（我们严重缺失）**：
  - **重试/退避**：`packages/retry/src/index.ts` → `RetrySupervisor`、`retryAsync`、`computeBackoff`、`RetryConfig`。
  - **凭证/密钥管理**：`src/gateway/credentials.ts`、`src/secrets/`（密钥隔离、轮换、secret-ref 契约 `gateway-protocol/src/secret-ref-contract.ts`）。
  - **沙箱隔离**：`src/gateway/input-allowlist.ts`、`node-command-policy.ts`（allow/deny 工具清单）、`mcp-app-sandbox-http.ts`。
  - **限流**：`src/gateway/control-plane-rate-limit.ts`、`auth-rate-limit.ts`。
  - **流式**：`src/gateway/server-chat.stream-text-merge.ts`。
  - **插件热加载**：`src/gateway/server-plugins.ts`、`server-reload-handlers.ts`。
  - **鉴权/作用域**：`src/gateway/auth.ts`、`method-scopes.ts`、`role-policy.ts`、`operator-approvals`（人工审批 + 运行时令牌）。
  - **MCP HTTP**：`src/gateway/mcp-http.ts`（原生 105+ MCP 源）。
  - **多 Agent 路由**：workspace + per-agent session 隔离。

**我们 adapter 桥接方式是否合理**
- 现状：用 `subprocess.run(["openclaw", tool, ...])` 调 CLI，其余用本地 Python 重写（`_register_local_tools`）。
- 判断：**不合理**。CLI 调用（1）拿不到结构化结果、（2）无法流式、（3）无法利用 Gateway 的鉴权/限流/沙箱、（4）`--yolo` 之类参数易变、易误判退出码。本地回退则完全绕过了真实 OpenClaw 的 MCP/Skill/渠道能力。
- **推荐集成方式**：以 **Gateway HTTP/WebSocket RPC**（或 `packages/sdk` 客户端）为唯一真实通道；SDK 调用 `client.ts`；通过 OpenAI 兼容端点复用现有推理链路。本地模式仅作为离线降级，不应成为主路径。

**应借鉴的生产级特性（按优先级）**
- P0：Gateway RPC/SDK 接入替代 CLI；流式输出；结构化错误。
- P1：鉴权 + 限流 + 沙箱 allow/deny 工具清单（直接复用 `input-allowlist`/`node-command-policy` 思路）。
- P1：`packages/retry` 的重试/退避逻辑（我们完全没有重试）。
- P2：插件热加载、secret-ref 凭证隔离、operator 审批运行时令牌。

### 2.2 Hermes Agent（记忆 + 进化 + 多平台渠道）

**真实提供的能力**
- **CLI + 消息网关**：`hermes gateway` 起 Telegram/Discord/Slack/WhatsApp/Signal/Email 网关；`hermes -z` 一次性推理。
- **ACP Server（正确集成方式）**：`acp_adapter/server.py` → `class HermesACPAgent(acp.Agent)`。基于 ACP（Agent Client Protocol）的 HTTP 服务，自带会话管理（`SessionManager`）、审批回调（`make_approval_callback`）、编辑审批策略（`_edit_approval_policy_for_state`）、`on_connect`。这是**程序化调用的生产级入口**。
- **Agent 主循环（健壮）**：`agent/conversation_loop.py` → `run_conversation()`，含**供应商故障转移**（`_sync_failover_system_message`）、计费/配额引导、上下文恢复。
- **凭证池（生产级）**：`agent/credential_pool.py` → `class CredentialPool`、`PooledCredential`；支持**多密钥轮转**、`get_pool_strategy`、`_exhausted_ttl`（衰竭退避）、`_extract_retry_delay_seconds`（从错误中提取重试延迟）。
- **技能/记忆系统**：`agent/skill_bundles.py`、`skill_commands.py`、`memory_manager.py`、`memory_provider.py`（持久记忆 + 用户画像 + 程序化记忆）。
- **错误分类**：`agent/error_classifier.py`。
- **上下文压缩**：`agent/context_engine.py`、`conversation_compression.py`。

**我们 adapter 桥接方式是否合理**
- 现状：`subprocess.Popen(["hermes","-z",prompt,"-m","deepseek-chat","--yolo"])` + 20s 超时，失败回退 `model_backend`（DeepSeek/Stub）。本地「进化」只是字符串拼接（`hermes_adapter.py:170`）。
- 判断：**不合理**。子进程（1）无法流式、（2）退出码非 0 就误判失败（README 明确说 `hermes` 某些场景会卡 TTY），（3）拿不到结构化/工具调用结果，（4）完全没用上 ACP Server、凭证池、故障转移、上下文压缩。
- **推荐集成方式**：启动 `hermes acp` 服务，XAI 通过 ACP HTTP 客户端调用 `HermesACPAgent`；复用其凭证池与故障转移。把 XAI 的 `model_backend`（DeepSeek）作为 Hermes 的一个 provider 接入，而非反过来用 subprocess 包 Hermes。

**应借鉴的生产级特性**
- P0：ACP Server/HTTP 接入替代 subprocess；结构化工具调用结果。
- P1：`CredentialPool` 多密钥轮转 + 衰竭退避（我们无凭证管理）。
- P1：`run_conversation()` 的供应商故障转移（`_sync_failover_system_message`）。
- P2：错误分类 `error_classifier`、上下文压缩、程序化技能/记忆、审批回调。

### 2.3 MemOS（记忆操作系统）

**真实提供的能力（4 个入口）**
- **Cloud API（托管）**：REST `https://memos.memtensor.cn/api/openmem/v1`（`/add/message`、`/search/memory`）。
- **Self-Host REST**：`uvicorn memos.api.server_api:app`（默认 `localhost:8000`），REST 客户端 `src/memos/api/client.py`；核心 `src/memos/api/server_api.py`。
- **OpenClaw Cloud / Local Plugin**：`apps/memos-local-plugin` —— **100% 本地 SQLite**，混合检索 **FTS5 + 向量**，智能去重、分层技能进化、多 Agent 协作、记忆查看器。含 `bridge`（JSON-RPC bridge）、`server`、`core`、`viewer`。
- **核心模块（生产级）**：
  - **混合检索**：`src/memos/search/`（FTS5 + 向量），而非关键词。
  - **MemScheduler 异步 ingestion**：`src/memos/mem_scheduler`（毫秒级延迟、高并发）。
  - **记忆巩固/反思**：`src/memos/dream`（类似「梦境」整理记忆，对应我们弱化的 `reflect()`）。
  - **记忆层级/Cube**：`src/memos/memories`、`mem_cube`、`multi_mem_cube`（多知识库隔离/共享）。
  - **重排**：`src/memos/reranker`。
  - **记忆反馈修正**：自然语言反馈纠正/补充/替换。
  - **MCP 暴露**：`src/memos/api/mcp_serve.py`。
  - **多模态**：文本/图像/工具轨迹/人格。

**我们 adapter 桥接方式是否合理**
- 现状：`memory_adapter.py` 是**自研 SQLite**（与 MemOS 源码无依赖关系），仅命名借用了「MemOS」；关键词检索、单层表、无 Cube、无向量、无异步、无重排、无巩固。
- 判断：**不合理（且名不副实）**。等于在 MemOS 之外重写了一个弱化版；既没用 `memos-local-plugin`，也没用 REST/SDK。
- **推荐集成方式**：优先接入 `apps/memos-local-plugin`（本地零云依赖、SQLite+向量，最贴合 XAI 本地私有定位），通过它的 JSON-RPC bridge 或 REST；或自托管 `memos.api.server_api:app` 走 SDK `client.py`。把现有 `memory_adapter.py` 退化为「桥接层」，保留 7 层语义映射。

**应借鉴的生产级特性**
- P0：接入真实 MemOS（本地插件/REST/SDK）；替换关键词检索为 **FTS5+向量混合检索**。
- P1：`MemScheduler` 异步写入（我们同步写，会阻塞对话流）。
- P1：多 Cube 隔离（对应多引擎/多用户，我们只有单表 `engine` 字段）。
- P2：`dream` 记忆巩固、`reranker` 重排、记忆反馈修正、MCP 暴露、多模态。

### 2.4 OllamaFlow（前端画布）

**真实提供的能力（生产级前端工程）**
- **画布引擎**：React + `@xyflow/react` v12（React Flow）+ 自研 `WorkflowExecutor`（`src/renderer/engine/executor.ts:252`）→ `getExecutionOrder()`（**拓扑排序**）、`executeBranchChain()`、`registerNodeExecutor()`（**插件化节点**）。
- **状态管理**：`zustand` + `immer` + `zundo`（**撤销/重做**）；多 store：`workflow-store`、`execution-store`、`agent-store`、`agent-analytics-store`（**可观测**）、`settings-store`、`workspace-store`。
- **流式 + 上下文压缩**：`agent-executor.ts` → `callOpenAIStream()`（流式）、`compressMessagesIfNeeded()`。
- **并发**：`engine/workers/worker-pool.ts`、`ExecutionManager`（`execution-manager.ts`，支持 running/paused/cancelled）。
- **富文本渲染**：`react-markdown` + `rehype-highlight` + `rehype-katex` + `remark-gfm` + `remark-math` + `highlight.js` + `katex` + `mermaid`；**XSS 净化** `dompurify`。
- **Agent 执行**：`AgentController`（`agent-controller.ts`）、`IntelligentAgentExecutor`（`agent-executor.ts`）、`agent-worker-system.ts`。

**我们 adapter / 前端桥接方式是否合理**
- 现状：`web/app.js` 画布是原生 JS 线性拖拽（`dropNode`/`drawConnections`，节点 i 连 i+1），无状态库、无执行引擎、无拓扑、无高亮、无撤销。
- 判断：**不合理**。XAI 的「OllamaFlow 前端画布」目前只是装饰性拖拽，与真实 OllamaFlow 的执行引擎完全脱节。
- **推荐集成方式**：把真实 OllamaFlow 的 `renderer/` 作为 XAI 前端（Electron 或 web），复用其 `WorkflowExecutor` + `worker-pool` + stores；至少借鉴其画布/渲染/状态管理范式，替换 `web/app.js` 的脚本式实现。

**应借鉴的生产级特性**
- P0：React Flow 画布 + 拓扑执行（`getExecutionOrder`）；Markdown/LaTeX/代码高亮渲染 + `dompurify` 净化。
- P1：`zustand`/`immer`/`zundo` 状态与撤销重做；`worker-pool` 并发；`ExecutionManager` 暂停/取消。
- P1：`agent-analytics-store` 执行可观测。
- P2：`registerNodeExecutor` 插件化节点；`compressMessagesIfNeeded` 上下文压缩。

### 2.5 OCTO_VEC（多 Agent 协作，参考）

**真实提供的能力**
- **PM 协调模型**：`src/tower.ts` 用 `MessageQueue`（PM FIFO 队列）+ `AgentMessageQueue`（每 Agent 收件箱，含 `registerInboxWaker`/`popForAgent`/`push`）；PM Agent（`src/agents/pmAgent.ts`）自动拆解任务并委派专家。
- **Agent Task Protocol（ATP）** 模块 `src/atp/`：
  - `messageQueue.ts`（PM 队列）、`agentMessageQueue.ts`（Agent 收件箱）
  - `agentRuntime.ts`、`agentGroups.ts`（Agent 组/团队）
  - `agentInterrupt.ts`（**运行中中断/转向**）
  - `agentStreamBus.ts`（流式事件总线）
  - `tokenTracker.ts`（**每 Agent token + USD 成本追踪**）
  - `eventLog.ts`（事件日志/可观测）、`database.ts`（ATP SQLite：tasks/employees/events/messages）
  - `postTaskHooks.ts`（任务后钩子，如安全扫描）
- **24 角色模板 + 三层记忆**（短/长/超长）+ 日落/日出生命周期 + 自动压缩。
- **17 渠道**、仪表盘 10 视图（SSE 实时）、移动端、QR 配对。
- **安全扫描**：每次编码任务后跑 Semgrep/Gitleaks/Trivy，报告落 `reports/`。

**我们协作现状**
- 现状：`engine_xai.py` 的 `/task` 命令（`_cmd_task`）只返回**静态四步计划文案**，不真正拆解/调度/追踪；`core/coordination.py`、`orchestrator.py` 未见真实消息队列。

**应借鉴的生产级特性**
- P0：PM 任务队列（FIFO）+ 每 Agent 收件箱（`MessageQueue`/`AgentMessageQueue` 范式）替代静态计划。
- P1：`tokenTracker` 成本追踪、`eventLog` 事件可观测、`agentInterrupt` 运行中干预。
- P1：Agent 组/团队（`agentGroups`）+ 角色模板。
- P2：任务后钩子触发安全扫描（Semgrep/Gitleaks/Trivy）；三层记忆 + 日落/日出生命周期。

---

## 3. GitHub 明星项目「上市级」特性

### 3.1 前端 UX（流式 / Markdown / 停止重试 / 错误态 / 加载态 / 代码块 / 会话列表 / 移动端）

| 项目 | 关键 UX 能力 |
|---|---|
| **Open-WebUI**（143K★） | 完整 Markdown+LaTeX；工件 KV 存储；响应式 PWA（移动端类原生）；流式；多模型同聊；原生 Python 函数工具 |
| **LibreChat**（MIT） | **对话分支/分叉（Fork）**、消息编辑重发、**Artifacts（React/HTML/Mermaid）**、**可恢复流式（断线续传）**、多标签/多设备同步、会话搜索（Meilisearch）、Reasoning UI（思维链）、代码解释器（沙箱多语言） |
| **Dify**（148K★） | 可视化 Workflow/Agent；工件；发布为 webapp/API/MCP；Analytics |

**对标 XAI 前端（`web/app.js`）**：无 Markdown、无代码高亮、无分支/重试态、无会话列表、无移动端、无加载/错误骨架、无断线续传。差距是「能用」到「上市级」的代差。

### 3.2 Agent 编排画布

| 项目 | 画布范式 |
|---|---|
| **n8n**（fair-code，≈70K★） | 节点画布，工作流即 **JSON（可 git diff/导入导出）**；item-based 执行（自动批处理）；400+/500+ 集成；**AI Agent 节点**（LangChain 工具调用循环）；2.0 **任务运行器（代码节点沙箱隔离）**；版本化+diff；审计轨迹；子工作流；人工审批暂停；重试；运行历史 |
| **LangGraph**（Microsoft） | **状态机图**（State/Node/Edge，条件边、循环）；**状态持久化**；语义搜索长期记忆 + 跨线程记忆（LangMem）；**human-in-the-loop 中断-恢复**；节点级缓存；MCP 端点 |
| **Dify** | Workflow Studio（拖拽节点 + 变量 + 代码沙箱节点 + DSL 导出 + 发布为 MCP） |

**对标 XAI 画布**：线性拖拽 vs 真实 DAG+拓扑执行+变量+沙箱+版本化+审计。差一个时代。

### 3.3 工具市场 / 权限治理 / 可观测性

| 维度 | 标杆做法 |
|---|---|
| **工具市场** | Dify **Plugin Marketplace（200+ 工具/MCP）**、n8n 400+ 集成 + 社区节点、Open-WebUI 函数工具 + 社区、LibreChat **Agent Marketplace + Skills(SKILL.md) + Subagents** |
| **权限治理** | Dify **RBAC（4 角色）+ 审计日志 + SSO/SAML + 沙箱代码节点**；Open-WebUI **RBAC + 用户组 + SSO/LDAP/SCIM**；LibreChat **SSO/OAuth/SAML/LDAP/2FA + 审核 moderation + token 限额** |
| **可观测性** | Open-WebUI **OpenTelemetry（traces/metrics/logs）** + Langfuse；Dify **Analytics（用量/延迟/成本/错误）** + LLMOps；AutoGen **tracing/metrics（OpenTelemetry）**；CrewAI **observability hooks**；n8n **运行历史/审计轨迹**；OCTO_VEC `tokenTracker`/`eventLog` |
| **安全** | n8n 代码节点**沙箱隔离**；OCTO_VEC 编码后 **SAST/SCA/密钥扫描**；Dify 沙箱代码节点 + AES-256 + 审计 |

---

## 4. 差距与改进清单（按模块）

> 优先级：P0 = 结构性/阻断性（不解决则系统不可靠或名不副实）；P1 = 重要生产特性；P2 = 增强项。
> 每项格式：**现状 → 标杆 → 建议**。

### 4.1 执行网关（OpenClaw 桥接）
- **现状**：`openclaw_adapter.py` 用 `subprocess.run(["openclaw", tool, ...])` 调 CLI，本地模式用 Python 重写 `exec/file_read/...`，无流式、无重试、无鉴权。
- **标杆**：OpenClaw `src/gateway/server.ts`（HTTP/WS RPC）、`packages/sdk/src/client.ts`、`openai-http.ts`（OpenAI 兼容）、`packages/retry`（`RetrySupervisor`/`retryAsync`）、`input-allowlist.ts`+`node-command-policy.ts`（沙箱）、`control-plane-rate-limit.ts`（限流）。
- **建议**：
  - P0：以 **Gateway RPC / SDK** 替代 CLI 调用；本地模式仅作离线降级，不作为主路径。
  - P1：接入 `packages/retry` 式**重试/退避**；接入**沙箱 allow/deny 工具清单**与**限流**。
  - P2：复用插件热加载、secret-ref 凭证隔离。

### 4.2 AI 推理 / 进化（Hermes 桥接）
- **现状**：`hermes_adapter.py` 用 `subprocess.Popen(["hermes","-z",...,"--yolo"])` + 20s 超时，失败回退 `model_backend`；本地「进化」仅字符串拼接。
- **标杆**：Hermes `acp_adapter/server.py`（`HermesACPAgent` ACP Server）、`agent/conversation_loop.py`（`run_conversation` + 供应商故障转移）、`agent/credential_pool.py`（`CredentialPool` 多密钥轮转+衰竭退避）、`error_classifier.py`、`memory_manager.py`。
- **建议**：
  - P0：以 **ACP Server/HTTP** 替代 subprocess；拿到结构化工具调用结果。
  - P1：引入 `CredentialPool` 式**凭证轮转 + 衰竭退避**；引入供应商**故障转移**。
  - P2：`error_classifier` 错误分类；程序化技能/记忆；审批回调。

### 4.3 记忆（MemOS 桥接）
- **现状**：`memory_adapter.py` 自研 SQLite（关键词检索、单表、无向量/异步/巩固），仅命名借用 MemOS。
- **标杆**：MemOS `apps/memos-local-plugin`（FTS5+向量混合、SQLite、零云）、`memos.api.server_api:app`（REST）、`mem_scheduler`（异步）、`dream`（巩固）、`mem_cube`/`multi_mem_cube`（Cube 隔离）、`reranker`、`memory feedback`。
- **建议**：
  - P0：接入真实 MemOS（本地插件/REST/SDK），替换关键词检索为 **FTS5+向量混合检索**。
  - P1：`MemScheduler` **异步写入**；**多 Cube 隔离**（多引擎/多用户）。
  - P2：`dream` 巩固、`reranker` 重排、记忆反馈修正、MCP 暴露。

### 4.4 前端 UX / 画布（OllamaFlow 参考）
- **现状**：`web/app.js` 用 `textContent` 直写（无 Markdown）、代码块无高亮、画布线性拖拽（非 DAG）、无会话列表/移动端/加载态/错误态/停止重试。
- **标杆**：OllamaFlow（React Flow + `WorkflowExecutor.getExecutionOrder` 拓扑 + `worker-pool` 并发 + `ExecutionManager` 暂停/取消 + `react-markdown`/`rehype-highlight`/`dompurify` + `zustand`/`zundo` + `agent-analytics-store`）；LibreChat（分支/Artifacts/可恢复流式）；Open-WebUI（PWA/Markdown+LaTeX）。
- **建议**：
  - P0：输出渲染改用 **Markdown+LaTeX+代码高亮** 并过 `dompurify`；画布升级为 **React Flow + 拓扑执行**。
  - P1：`zustand`/`immer`/`zundo` 状态管理 + **撤销重做**；**停止/重试/错误态/加载态**；**会话列表**；`worker-pool` 并发执行；`agent-analytics-store` 可观测。
  - P2：**移动端/PWA**；对话分支 Fork；Artifacts 预览。

### 4.5 多 Agent 协作（OCTO_VEC 参考）
- **现状**：`/task` 返回静态计划文案，无真实拆解/调度/追踪；无消息队列、无成本追踪。
- **标杆**：OCTO_VEC `tower.ts` + `atp/messageQueue.ts`（PM FIFO）+ `atp/agentMessageQueue.ts`（Agent 收件箱）+ `atp/tokenTracker.ts`（成本）+ `atp/eventLog.ts`（事件）+ `atp/agentInterrupt.ts`（中断）+ `atp/agentGroups.ts`（团队）+ 编码后安全扫描。
- **建议**：
  - P0：引入 **PM 任务队列 + 每 Agent 收件箱** 替代静态计划（`MessageQueue`/`AgentMessageQueue` 范式）。
  - P1：`tokenTracker` **成本追踪**；`eventLog` **事件可观测**；`agentInterrupt` **运行中干预**；Agent 组/角色模板。
  - P2：任务后钩子触发 **SAST/SCA/密钥扫描**（Semgrep/Gitleaks/Trivy）。

### 4.6 治理（权限 / 审批 / 审计）
- **现状**：`engine_xai.py` 审批队列是**内存字典** `_pending_approvals`（进程重启即丢）；Guardian 仅 P0/P1/P2 三级文案，无持久化、无 RBAC、无审计日志、无 SSO。
- **标杆**：Dify **RBAC(4 角色)+审计日志+SSO/SAML+沙箱代码节点**；Open-WebUI **RBAC+用户组+SSO/LDAP/SCIM**；LibreChat **SSO/OAuth/SAML/LDAP/2FA+moderation+token 限额**；OpenClaw `operator-approvals`（运行时审批令牌）。
- **建议**：
  - P0：审批队列**持久化**（落 SQLite/ATP 式 store），进程重启不丢。
  - P1：引入 **RBAC 角色 + 审计日志**（谁、何时、调了什么工具、结果）；敏感操作需 SSO/二次确认。
  - P2：沙箱代码执行节点（参照 n8n/Dify）；凭证集中管理 + 轮换。

### 4.7 可观测性
- **现状**：仅 `/api/diagnose` 一次性体检 + `status()`；无 traces/metrics/logs、无成本、无执行轨迹。
- **标杆**：Open-WebUI **OpenTelemetry(traces/metrics/logs)** + Langfuse；Dify **Analytics(用量/延迟/成本/错误)**；AutoGen **OpenTelemetry tracing**；OCTO_VEC `tokenTracker`+`eventLog`；OllamaFlow `agent-analytics-store`。
- **建议**：
  - P0：统一**事件日志**（每次工具调用/LLM 调用留 trace_id + 耗时 + 输入摘要）。
  - P1：接入 **OpenTelemetry** 或轻量 traces；前端 `agent-analytics-store` 式执行看板（用量/延迟/成本/错误率）。
  - P2：LLM 调用 **token + USD 成本追踪**（复用 OCTO_VEC `tokenTracker` 思路）。

### 4.8 安全 / 沙箱
- **现状**：`openclaw_adapter._safe_path()` 仅做路径越界检查；`vulnerability_scan()` 是轻量正则启发式；无沙箱执行、无 SAST/SCA、无密钥扫描、无速率限制、server 无鉴权。
- **标杆**：n8n **代码节点沙箱隔离（task runners）**；OCTO_VEC **Semgrep/Gitleaks/Trivy 编码后扫描**；OpenClaw **沙箱 allow/deny + 限流 + secret-ref**；Dify **AES-256 + 沙箱 + 审计**。
- **建议**：
  - P0：命令/代码执行**沙箱隔离**（容器/Seatbelt/最小权限）；server 加**基础鉴权**（XAI 本地私有但需防误暴露）。
  - P1：把正则扫描升级为 **Semgrep/Gitleaks** 真实 SAST/密钥扫描；接入**限流**。
  - P2：依赖扫描（Trivy/SCA）；凭证集中保管 + 不落盘明文。

### 4.9 流式与可靠性（横切）
- **现状**：`engine_xai.py:chat()` 是**事件级 SSE**（intent/guard/progress/answer/done），LLM 整段塞进单个 `answer` 事件 → **无 token 级流式**；`server_xai.py` 用标准库 http.server（无并发/背压）。
- **标杆**：OpenClaw `server-chat.stream-text-merge.ts`；OllamaFlow `callOpenAIStream`；LibreChat **可恢复流式（断线续传）**；n8n 运行历史/重试。
- **建议**：
  - P0：LLM 输出改为 **token 级 SSE 流式**（前端增量渲染），对齐 Open-WebUI/LibreChat 体验。
  - P1：服务端换为支持并发/背压的栈（如现有 `server.py`/`server_xai.py` 已用？建议统一）；前端断线续传。
  - P2：工具调用结果**结构化流式**（边执行边回传进度事件，已有 progress 雏形，需标准化）。

---

## 5. 优先级汇总（行动地图）

### P0（结构性，先做）
1. OpenClaw 接入 **Gateway RPC/SDK** 替代 subprocess CLI。
2. Hermes 接入 **ACP Server/HTTP** 替代 subprocess。
3. MemOS 接入**真实本地插件/REST/SDK**，检索升级 **FTS5+向量混合**。
4. 前端输出**Markdown+LaTeX+代码高亮(+dompurify)**；画布升级 **React Flow + 拓扑执行**。
5. 多 Agent 协作引入 **PM 任务队列 + Agent 收件箱**（替代静态 `/task`）。
6. 审批队列**持久化**；LLM **token 级流式**。

### P1（重要生产特性）
7. 重试/退避（`packages/retry` 范式）、沙箱 allow/deny、限流（OpenClaw）。
8. 凭证轮转 + 衰竭退避（`CredentialPool`）、供应商故障转移（Hermes）。
9. MemScheduler 异步写入、多 Cube 隔离（MemOS）。
10. 状态管理 + 撤销重做 + 停止/重试/错误态 + 会话列表 + 并发（OllamaFlow）。
11. RBAC + 审计日志 + SSO（Dify/Open-WebUI/LibreChat）。
12. OpenTelemetry / 执行看板 / token 成本追踪（OCTO_VEC/LibreChat）。
13. 沙箱执行 + Semgrep/Gitleaks 扫描（n8n/OCTO_VEC）。

### P2（增强）
14. 插件热加载、secret-ref 凭证隔离（OpenClaw）。
15. 错误分类、程序化技能/记忆（Hermes）。
16. `dream` 记忆巩固、reranker、记忆反馈（MemOS）。
17. 移动端/PWA、对话分支 Fork、Artifacts（LibreChat/Open-WebUI）。
18. Agent 组/角色模板、任务后安全扫描钩子（OCTO_VEC）。
19. 依赖扫描 Trivy/SCA、凭证集中保管（Dify/OCTO_VEC）。

---

## 附：引用清单（真实路径/类/API）

**vendor/**
- OpenClaw：`vendor/openclaw/src/gateway/server.ts`、`openai-http.ts`、`packages/sdk/src/client.ts`、`packages/retry/src/index.ts`（`RetrySupervisor`/`retryAsync`）、`src/gateway/input-allowlist.ts`、`node-command-policy.ts`、`control-plane-rate-limit.ts`、`credentials.ts`、`src/gateway/server-plugins.ts`
- Hermes：`vendor/hermes-agent/acp_adapter/server.py`（`HermesACPAgent`）、`agent/conversation_loop.py`（`run_conversation`）、`agent/credential_pool.py`（`CredentialPool`/`PooledCredential`）、`agent/error_classifier.py`、`agent/memory_manager.py`
- MemOS：`vendor/MemOS/apps/memos-local-plugin`、`src/memos/api/server_api.py`、`mem_scheduler`、`dream`、`mem_cube`/`multi_mem_cube`、`reranker`、`src/memos/api/mcp_serve.py`
- OllamaFlow：`vendor/OllamaFlow/src/renderer/engine/executor.ts`（`WorkflowExecutor`/`getExecutionOrder`）、`engine/workers/worker-pool.ts`、`engine/execution-manager.ts`、`store/agent-analytics-store.ts`、`agent-executor.ts`（`callOpenAIStream`）
- OCTO_VEC：`vendor/OCTO_VEC/src/tower.ts`、`src/atp/messageQueue.ts`、`agentMessageQueue.ts`、`tokenTracker.ts`、`eventLog.ts`、`agentInterrupt.ts`、`agentGroups.ts`、`src/agents/pmAgent.ts`

**XAI 现状锚点**
- `core/adapters/openclaw_adapter.py:181 _execute_real()`、`_register_local_tools`
- `core/adapters/hermes_adapter.py:91 _infer_real()`、`hermes_adapter.py:170`（字符串进化）
- `core/adapters/memory_adapter.py:67 _init_db()`、`memory_adapter.py:123 write()`
- `core/engine_xai.py:126 chat()`、`engine_xai.py:238 _classify_intent()`、`engine_xai.py:481 _create_approval()`
- `web/app.js:99`（SSE 消费）、`web/app.js:355 appendCodeBlock()`、`web/app.js:492 dropNode()`、`web/app.js:557 drawConnections()`
- `server_xai.py:161 _sse_response()`（事件级 SSE）

**GitHub 明星项目（特性索引）**
- Open-WebUI（143K★）：Markdown+LaTeX、工件 KV、OpenTelemetry、RBAC、PWA、Python 函数工具、SSO/LDAP/SCIM、Plugin 管线
- LibreChat（MIT）：对话分支/Fork、Artifacts、可恢复流式、Code Interpreter 沙箱、MCP、Agent Marketplace、Skills、SSO/SAML/LDAP/2FA、会话搜索
- Dify（148K★）：Workflow Studio、Agent 节点、Plugin Marketplace(200+)、发布为 API/MCP、Analytics、RBAC+审计+SSO、沙箱代码节点、DSL 导出、LLMOps
- n8n（fair-code）：JSON 工作流、item-based 执行、400+/500+ 集成、AI Agent 节点、2.0 沙箱任务运行器、版本化+diff、审计轨迹、子工作流、人工审批、重试
- LangGraph（Microsoft）：状态机图、状态持久化、语义/跨线程记忆(LangMem)、human-in-the-loop 中断-恢复、MCP、节点级缓存
- AutoGen（Microsoft，MIT，维护模式）：Actor 运行时、AgentChat GroupChat、OpenTelemetry tracing、AutoGen Studio、UserProxyAgent 人工介入
- CrewAI：角色 Agents→Tasks→Crew、Flows(事件驱动/可恢复)、记忆(短/实体/向量)、observability hooks、企业 RBAC/telemetry、guardrail
