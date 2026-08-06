# XAI 项目综合文档（PROJECT_OVERVIEW.md）

> **生成时间**：2026-07-18
> **文档定位**：交给另一个 AI Agent 评审用的项目单一入口文档。
> **文档真源**：本文与 `~/.workbuddy/memory/MEMORY.md` 的「XAI 项目 · 双核心融合架构」段（架构宪法）一致；与 `AUDIT_REPORT.md`（2026-07-18 17:52 审计快照）+ 本次源码复核（2026-07-18 18:30+）对账。
> **架构宪法**：MEMORY.md「Dual-Kernel Fusion Architecture」为唯一架构真源。其余 6 份蓝图（`xai-final-design` / `xai-platform-architecture` / `xai-ultimate-blueprint-v2` / `xai-fusion-ultimate-plan` / `xai-unified-architecture` / `super-grok-blueprint`）若冲突，以宪法为准。

---

## Part 1 · 蓝图 vs 现实对账（Gap Analysis）

**复核方法**：通读 `MEMORY.md` 宪法段 + `AUDIT_REPORT.md` + 实际源码（core/ 28 个 .py + server_xai.py + web/app.js + 启动链）。注意：审计报告为 17:52 快照，部分 P0/P1 bug 在 18:00+ 修复后已不再适用；下文按当前最新源码状态判定，并在脚注标出审计时与现在的差异。

### 1. 双内核并列（Hermes + Grok Build） — ⚠️ 部分达成

- **宪法要求**：Hermes（通用推理·GEPA 自进化）+ Grok Build（代码工程·subagent/goal/apply_patch/dream 蒸馏）均为第一类公民，无层级关系。
- **现实**：
  - Hermes 通过 `core/adapters/hermes_adapter.py` 接入，`_execute_general` / `_execute_code` / `hermes.darwinian_evolve` 真实调用，可工作。
  - Grok Build 通过 `core/grok_build_engine.py::GrokBuildBridge` 桥接本地 `grok` 二进制（headless `--single --output-format json`）。`engine_xai.py:577` `_execute_code` 优先走 Grok Build，失败回退 Hermes。
  - **不对称点**：Grok Build 是"条件可用"——本机 `~/.grok/bin/grok` 不存在时 `self.available=False`，自动降级到 Hermes。`code_dev` 意图确实路由到 Grok Build 桥（`engine_xai.py:574-588`），但只有"代码生成"一类任务，蓝图中 subagent/goal/apply_patch/dream 蒸馏等子能力未拆出独立接口。
  - **Rust 源码**：`rust/xai-grok-{guardian,reason,meta,runner}` 四个 crate 独立可编译，但**运行时未被调用**——它们是"未来并入 Grok fork 的骨架"，与 Python 内核无运行时耦合。
- **证据**：`engine_xai.py:577` `if self.grok_build.available: gb_result = self.grok_build.run(...)`；`grok_build_engine.py:322` `GROK_BIN = shutil.which("grok") or os.path.expanduser("~/.grok/bin/grok")`。

### 2. Intent Router 仲裁 — ⚠️ 部分达成（路由字段未被消费）

- **宪法要求**：任务分类后自动化分发至最优内核，可配置规则。
- **现实**：
  - `IntentRouter.classify()` 真实被 `engine_xai.py:421` 调用。
  - 但 `IntentResult.routing`（"openclaw_gateway"/"grok_build_engine"/"orchestrator"/"kb"/"reason"）**无任何消费者**。`_classify_intent` 只取 `intent.value` 经 `routing_map` 映射到引擎自己的 `Intent.type`（`code_dev/office/automation/research/general`）。
  - `_execute_intent` 按 `Intent.type` 分派：`code_dev` → `_execute_code`（✓ Grok Build）、`browser` → `_execute_browser`（✓ 真实联网）、`research` → `_execute_browser`（✓ 落到搜索）、`memory` → `_execute_memory_query`（✓）、`office/automation/general` → `_execute_general`（⚠ 通用对话兜底，未走 OpenClaw/Orchestrator）。
  - **双轨分类**：`_classify_intent` 内部还自建一套 rules 兜底（含 browser/memory/office/research/code_dev 五类，关键词与 IntentRouter 不一致）。
- **证据**：`engine_xai.py:418-468`；`intent_router.py:58-64` `ROUTING` 表无消费者。

### 3. 认知 Control Loop（Reason → Meta → Runner → L4 Verify → Distill） — ⚠️ 部分达成

- **宪法要求**：5 步循环两核共享，自思考自循环实体。
- **现实**：
  - `ControlLoop.act()`（`core/control_loop.py:57-119`）真实实现 6 步：`meta 外环(thinking_budget) → reason(thinking_protocol / self_refine / multi_trajectory) → meta.reflect(Brier 校准) → guardian(approve) → execute(execute_fn) → meta.observe(L8Auditor 四维审计)`。
  - 唯一入口是 `/loop` 斜杠命令（`engine_xai.py:945-956` 调用 `self.control_loop.act(task)`）。
  - **缺位**：
    - `Runner`（`core/runner.py`）独立存在（分步 + checkpoint + 质量门 + 续跑），但**运行时无任何调用**（grep 实证）。
    - **L4 Verify 不存在**——代码库无此组件；当前最接近的是 `L8Auditor.audit()` 四维（数据完整/逻辑自洽/幻觉/动作安全），但这是 L8 不是 L4。
    - `Distill` 经 `/api/distill` 端点（`server_xai.py:367-382`）实现，但只是"拼接近期记忆存 anchor"——`hermes.darwinian_evolve` 才是真实模型驱动进化，二者未在 Control Loop 内联动。
  - **不是默认路径**：用户不主动 `/loop` 时，普通对话直接走 `_execute_general`，不经 Control Loop。
- **注**：审计报告 P0-1 称"`/loop` 100% 报错因 `ControlLoop.run` 不存在"——**该 bug 已修复**（`engine_xai.py:953` 改为 `self.control_loop.act(task)`，`ControlLoop.act` 存在）。
- **证据**：`control_loop.py:57` `def act(...)`；`engine_xai.py:953` `result = self.control_loop.act(task)`；`runner.py` 全文无外部调用方。

### 4. Guardian 治理闸门（P0/P1/P2） — ✅ 工作中

- **宪法要求**：风险分级 + 二次确认 + 审批队列，覆盖核心引擎层全区域。
- **现实**：
  - `core/guardian.py` 真实实现：`RiskLevel(P0/P1/P2)`、`RISK_RULES`（delete_file/overwrite_file/force_push/secret_write/rm_rf→P0；run_command/network/install_pkg→P1；read_file/compute→P2）、`classify()` / `approve()` / `guard()` / `before_tool_call()` / `ApprovalQueue` / `PermissionTier`。
  - `engine_xai.py:1070-1085` `_guard_action` 内容级识别：命中 `rm -rf` / `sudo rm` / `mkfs` / `force push` / `drop table` 等升级 P0；命中 `删除/rm /del` → `delete_file` (P0)；命中 `exec/bash/powershell` → `run_command` (P1)；命中 `http(s)://` / `curl` / `fetch` → `network` (P1)；其余 `general` (P2)。
  - P0 拦截 → 创建审批卡片（`_create_approval`）→ 用户 `/approve <id>` 后**真正重执行原意图**（`_cmd_approve` → `_execute_intent`）。
  - `_safe_path` 防 OpenClaw 工作区路径穿越（`openclaw_adapter.py:94-99`）。
  - 审计提到的 `_guard_for_coordination` TypeError **已修复**（`engine_xai.py:1257` 改为 `classify(Action(kind=kind or "general", target=task[:200]))`，字段名匹配 `Action` dataclass）。
- **覆盖缺口**：Guardian 仅覆盖对话/群聊/工作流 exec 节点；`_run_wf_node` 的 `exec/file/git` 节点会查 guardian，但其他节点（chat/react/router/skill）不查。
- **证据**：`guardian.py:42-53` `RISK_RULES`；`engine_xai.py:316-329` P0 拦截→审批卡片；`engine_xai.py:915-934` `_cmd_approve` 真重执行。

### 5. 7 层元认知记忆（单一事实源） — ⚠️ 部分达成

- **宪法要求**：7 层（工作/长期/锚点/反思/因果链/日记/用户画像），单一事实源，禁止双写。
- **现实**：
  - `core/memory_core.py::MemoryCore` 真实实现 **8 层**：`working / short_term / long_term / anchor / reflection / causal / user_profile / failure_correction`（多了 failure_correction，少了 diary/日记）。
  - SQLite：`~/.xai/memory.db`，单连接 + 锁，schema 含 `id/layer/engine/key/value/importance/meta/created_at/accessed_at`。
  - 写入：`engine_xai.py:1236-1251` `_safe_memory_core_write` 每轮对话写 `short_term`，meta 注入 `project_id`。**审计报告 P1-18 双写问题已修复**——不再同时写 `MemoryAdapter`。
  - **未完全消除双轨**：`MemoryAdapter`（`core/adapters/memory_adapter.py`）仍存在并落 `~/.xai/memory/memos.db`，由 `/remember` 命令（`engine_xai.py:890`）和 `_cmd_recall` 走的 `query_cross_engine` 使用。两个 SQLite 文件并存、层名不一致（MemoryAdapter: `short/long/anchor`；MemoryCore: `short_term/long_term/anchor`）。
  - `consolidate()`（短期→长期巩固）存在但无定时调度，需手动调用。
- **证据**：`memory_core.py:31-39` 8 层 `Layer` 枚举；`memory_adapter.py:28-46` 7 层 `MemoryLayer`；`~/.xai/` 实测含 `memory.db` + `memos.db` + `memos.db-shm` + `memos.db-wal`。

### 6. Substrate 执行网关（OpenClaw） — ⚠️ 部分达成

- **宪法要求**：OpenClaw 本体作 Substrate，工具路由 + 文件/终端/浏览器/扫描全栈，直接卡 Guardian 之下。
- **现实**：
  - `core/adapters/openclaw_adapter.py::OpenClawAdapter` 是**事实执行网关**：6 个本地工具（`exec/file_read/file_write/file_delete/browser_open/list_dir`）+ 真实 OpenClaw CLI 桥接（`mcp_list_servers/mcp_add/mcp_list_tools/list_channels/list_real_skills/load_real_skill/vulnerability_scan/schedule_cron`）。
  - `core/substrate.py::SubstratePort / LocalSubstrate` 是另一套抽象，但**只被旧 `core/engine.py` 使用**，新 `engine_xai.py` 不依赖。
  - "卡 Guardian 之下"：`_run_wf_node` 在 `exec/file/git` 类节点前查 guardian（`engine_xai.py:1176-1182`），但 `_execute_code` 写文件 + exec 不查；`_execute_general` 也不查。
  - `_exec_command` 用 `shlex.split` + `subprocess.run(args, shell=False)`（`openclaw_adapter.py:131-148`）——审计中提到的 `shell=True` 气味已修复。
- **证据**：`openclaw_adapter.py:84-92` `_register_local_tools`；`openclaw_adapter.py:135-137` `shlex.split` 数组形式。

### 7. 控制台为纯视图层（4 Tab） — ✅ 基本达成

> **底座修订（2026-07-19）**：官方控制台底座由 `web/` 改为 `xai-frontend/`（liquid-glass/WorkBuddy 风，Route A）。`web/` 的 4-Tab 实现作为参考架构保留。下列"现实"仍描述 `web/`，仅作能力对照，不再作为前端主线路。
>
> **底座再修订（2026-07-22，A0=a 决策）**：经多 Agent 协同评审，**官方产品控制台定为 V4 `frontend/`**（React+Vite，OllamaFLOW 派生 12 页），`xai-frontend/` 由 Route A 扶正**反转降为 legacy**（见 Stale Modules）。`server_xai.py` 的 `WEB_DIR` 已从 `xai-frontend/dist-web` 切到 `frontend/dist`，生产服务 `:8000` 托管 V4。双前端事实：V4 `frontend/` 与 legacy `xai-frontend/` 并存，前者为产品、后者为参考。

- **宪法要求**：WorkBuddy 式三栏，零业务逻辑，UI 能力由内核能力注册表驱动。
- **现实**：
  - `web/`（HTML 345 行 + app.js 1361 行 + styles.css 807 行）纯前端，零业务逻辑，全部经 HTTP/SSE 调后端。
  - 4 Tab 全部已接线：
    1. **对话（chat）**：三栏工作台（会话栏/对话/成果区），SSE 流式 + 拓扑/执行过程/交付物/进化 4 子面板。
    2. **画布（canvas）**：20 种可拖节点 + DAG 编辑器 + `POST /api/workflow/run` 真实后端执行（Kahn 拓扑排序 + 环路检测 + 逐节点 SSE 反馈）。
    3. **群聊（room）**：审计称"死 UI"**已修复**——`app.js:1240-1265` `roomLoadAgents()` 调 `/api/agents`，`roomSend()` 调 `/api/coordination/chat`，点击 Tab 触发加载。
    4. **管理（settings）**：9 个 settings-card（技能/MCP/记忆/自动化/安全扫描/进化/治理/模型/Loop 安全），每个调对应斜杠命令或 API。
  - **缺口**：UI 节点不是"引用已注册能力（by name）"——画布 20 种节点类型硬编码在前端，无能力注册表驱动；蓝图§6 未做到。
- **证据**：`web/index.html:73-78` 4 个 `.nav-item`；`web/app.js:1242,1257` 群聊 API 调用；`web/app.js:1182-1232` Loop Safety UI。

### 8. 整合策略（Grok Build: Rust 源码 + 二进制 MCP 子服务） — ⚠️ 部分达成

- **宪法要求**：汉化 Rust 源码作接口参考 + 原版 `xai-grok-pager-bin` 二进制作运行 MCP 子服务，通过 ACP/MCP 协议通信。
- **现实**：
  - 二进制桥接 ✓：`GrokBuildBridge.run()` 调 `grok --single --output-format json` 子进程。
  - **协议**：✗ 用 subprocess + stdout JSON，**不是 ACP/MCP**。
  - **Rust 源码**：`rust/xai-grok-{guardian,reason,meta,runner}` 独立 crate，与 `grok-build-src/crates/` 无合并；运行时不被 Python 引用。
  - 汉化：在 `~/.grok/downloads/grok-0.2.93-macos-aarch64.orig.bak` 保留回滚点（见 MEMORY.md「grok-build 汉化项目地雷」），但本仓库内无汉化 Rust 源码副本。
- **证据**：`grok_build_engine.py:344` `cmd = [self.grok_bin, "--single", "--output-format", "json", task]`。

### 9. 模型策略（云模型 + 本地 Ollama 双选） — ❌ 未达成

- **宪法要求**：云模型仅连模型端口出网 + 本地 Ollama 双选；除模型端口外无任何主动上传/同步。
- **现实**：
  - `core/model_backend.py::ModelBackend` 抽象层存在；`StubBackend`（离线）+ `DeepSeekBackend`（OpenAI 兼容 `/v1/chat/completions`）两个实现。
  - **无 `OllamaBackend` 类**——全代码库 grep 无 `class OllamaBackend`。
  - `hermes_adapter.list_models()` 会动态检测 `shutil.which("ollama")` 并列出 "ollama/* (本地已安装...)"，但仅作展示，不可用。
  - `ModelRegistry`（`core/model_registry.py`）支持任意 provider（deepseek/openai/anthropic/ollama/custom），添加后存 `~/.xai/models.json`，但 `_rebuild_backend()` 只懂 `DeepSeekBackend`——切到 ollama 时仍构造 DeepSeek 客户端。
  - **隐私闭环**：✓ 除 DeepSeek API 端口外无任何主动上传；记忆/会话/项目全部本地 SQLite；OpenClaw 本地工具不联网。
- **证据**：`engine_xai.py:218-226` `_rebuild_backend` 仅 `DeepSeekBackend`；`grep -r "class OllamaBackend" xai/` 无结果。

### 10. LoopSafety 5 闸门 — ⚠️ 部分达成

- **宪法要求**：5 重闸门真实生效（Token 预算/重复检测/乒乓球/断路器/上下文溢出）。
- **现实**：
  - `core/loop_safety.py::LoopSafety` 实现完整：`reset / check / record_error / record_result / check_context`，3 档预设（recommended/strict/relaxed），持久化到 `~/.xai/loop_safety.json`。
  - **运行时调用**（grep 实证）：
    - `engine_xai.py:285` `self.loop_safety.reset()` — ✓ 调用
    - `engine_xai.py:286` `self.loop_safety.check("chat_start", user_input[:100], tokens=0)` — ✓ 调用
    - `record_error` / `record_result` / `check_context` — ✗ **零调用**
  - 即 **2/5 闸门生效**（reset + check），断路器/上下文压缩/重复检测的回写路径未接。
  - 管理面板 UI 可改阈值（`/api/loop-safety-update`，已兼容 `{key, value}` 与扁平字段两种格式，server_xai.py:425-428），但改了也只影响 `check()` 调用时的判定，不影响未接线的 3 闸门。
  - **注**：审计 P2-24 称 UI 修改无效——**已修复**（`server_xai.py:425-428` 加了 `kwargs[data["key"]] = int(data["value"])`）。
- **证据**：`engine_xai.py:285-286` 仅 2 处调用；`grep "loop_safety\." core/` 无 `record_error/record_result/check_context` 调用点。

### 11. ProviderFallback infer() — ❌ 未达成

- **宪法要求**：底层模型调用失败时，按注册表优先级自动切换到备用模型。
- **现实**：
  - `core/provider_fallback.py::ProviderFallback.infer()` 设计完整：包装一次模型调用，失败时自动轮换。
  - **`infer()` 全代码库零调用**（grep 实证 `provider_fallback\.infer|fallback\.infer` 无结果）。
  - 引擎绕开了这个类，自己实现 `_infer_with_fallback()`（`engine_xai.py:180-204`）和 `_execute_general` 内的 try/except 切换逻辑：失败 → `fb._find_next()` → `model_registry.activate(next_model.id)` → `_rebuild_backend()` → 重试。
  - 即故障轮换**功能**可用，但**未走 `ProviderFallback.infer` 统一接口**——三处复制粘贴逻辑，难维护。
  - tests/ 下无任何 fallback 主备切换测试。
- **证据**：`engine_xai.py:180-204` 自实现；`provider_fallback.py:55-99` `infer` 无调用方。

### 12. Project 隔离 — ⚠️ 部分达成

- **宪法要求**：每条记忆 meta 带 project_id → store/query 加 project 过滤；隔离完全。
- **现实**：
  - `core/project.py::ProjectManager` 真实实现：SQLite `~/.xai/projects.db`，CRUD + 激活，启动时确保"默认工作区"。
  - `MemoryCore.recall(keyword, limit, project_id)` 支持 project_id 过滤——但实现是 `meta LIKE '%"project_id":"{project_id}"%'`（`memory_core.py:158`），用 JSON 字符串 LIKE 模拟，非真实列。
  - `_safe_memory_core_write` 在 meta 里注入 `project_id`（`engine_xai.py:1247`）。
  - `_retrieve_memory_context` 取 `p = self.project_manager.current()` 传 `pid`（`engine_xai.py:700-702`）。
  - **隔离缺口**：
    - `SessionStore`（`~/.xai/sessions.db`）不按 project 分会话——session_id 与 project_id 解耦。
    - `workspace` 不随 project 切换（`OpenClawAdapter._workspace` 固定）。
    - `MemoryAdapter`（`~/.xai/memory/memos.db`）无 project_id 字段。
- **证据**：`memory_core.py:158` `meta LIKE` 模式；`project.py` 无 workspace 切换 hook。

### Gap Analysis 总览表

| # | 宪法组件 | 状态 | 关键证据 |
|---|---|---|---|
| 1 | 双内核并列 | ⚠️ Partial | Grok Build 条件可用，仅代码生成一类任务 |
| 2 | Intent Router 仲裁 | ⚠️ Partial | `routing` 字段零消费者；office/automation 落 general |
| 3 | 认知 Control Loop | ⚠️ Partial | `act()` 工作；Runner/L4 Verify/Distill 未串 |
| 4 | Guardian 治理闸门 | ✅ Working | P0/P1/P2 真实生效，批准后真重执行 |
| 5 | 7 层元认知记忆 | ⚠️ Partial | MemoryCore 8 层 ✓；MemoryAdapter 双轨未消除 |
| 6 | Substrate 执行网关 | ⚠️ Partial | OpenClawAdapter 是事实网关；substrate.py 弃用 |
| 7 | 控制台纯视图层 | ✅ Working | 4 Tab 全部接线（含群聊修复） |
| 8 | Grok Build 整合策略 | ⚠️ Partial | 二进制 ✓；非 ACP/MCP；Rust 源码未合并 |
| 9 | 模型策略 Ollama | ❌ Missing | 无 OllamaBackend 类 |
| 10 | LoopSafety 5 闸门 | ⚠️ Partial | 仅 reset/check 调用，3 闸门未接 |
| 11 | ProviderFallback infer() | ❌ Missing | `infer()` 零调用，引擎自实现绕开 |
| 12 | Project 隔离 | ⚠️ Partial | meta LIKE 模拟；session/workspace 未隔离 |

**整体完成度**：4 ✅ + 7 ⚠️ + 2 ❌ ≈ **55%**（架构层）。审计报告的"60% 总体"评估仍准确，部分 P0/P1 bug 已在审计后修复（见 Changelog）。

---

## Part 2 · 项目综合文档

### 1. Project Identity

| 字段 | 值 |
|---|---|
| 名称 | **XAI 统一操作台**（XAI Unified Console） |
| 版本 | v3（2026-07-18 锁定，融合架构宪法版） |
| 仓库根 | `/Users/Admin/Desktop/mask/xai/` |
| 定位 | 本地私有 + 开源可改 + 自带推理增强/元认知/安全审批内核 + 自蒸馏进化的「Agent 操作系统 + 可视化工作流画布」 |
| 架构范式 | **Dual-Kernel Fusion Architecture**（双核心融合）— Hermes（通用推理 + GEPA 自进化）+ Grok Build（代码工程），Intent Router 仲裁 |
| 目标用户 | 单机单用户开发者 / 技术用户（隐私敏感、需本地闭环、需可视化工作流） |
| 隐私边界 | 云模型仅连模型端口出网；记忆/会话/项目全部本地 SQLite；除模型端口外无任何主动上传 |
| 体验标杆 | 对标 WorkBuddy / Coze / dify / Open-WebUI（流式 + 多轮 + 真实能力 + 治理） |
| 当前完成度 | ~60%（主对话链路达上市级；架构层 4/12 完全达成，7/12 部分达成，2/12 未达成） |

### 2. Architecture Overview

#### 系统架构图（ASCII）

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         控制台（web/，纯视图层，4 Tab）                       │
│  对话 chat │ 画布 canvas │ 群聊 room │ 管理 settings                          │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │ HTTP / SSE  (localhost:8000)
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                       server_xai.py (ThreadingHTTPServer)                    │
│   GET /api/status /api/memory /api/approvals /api/agents /api/projects ...   │
│   POST /api/chat (SSE) /api/chat/send /api/workflow/run (SSE) /api/upload    │
│        /api/save /api/coordination/chat /api/models/{add,delete,activate}    │
│        /api/loop-safety-update                                               │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼──────────────────────────────────────────┐
│                    core/engine_xai.py :: XAIEngine                           │
│                                                                              │
│  用户输入 → _parse_slash → _classify_intent → _guard_action(classify) →      │
│            → _execute_intent → SSE 事件流                                     │
│                                                                              │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────┐   ┌──────────────┐  │
│  │ IntentRouter │   │   Guardian   │   │ ControlLoop  │   │ Coordination │  │
│  │ (5 类 + 评分) │   │ (P0/P1/P2)   │   │  (/loop 入口)│   │   Bus        │  │
│  └──────────────┘   └──────────────┘   └──────────────┘   └──────────────┘  │
└──────────────────────────────────┬──────────────────────────────────────────┘
                                   │
        ┌──────────────────────────┼──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────────┐    ┌───────────────────┐     ┌───────────────────────┐
│ HermesAdapter     │    │ OpenClawAdapter   │     │  GrokBuildBridge      │
│ (model_backend)   │    │ (6 本地工具+CLI)   │     │  (grok --single 子进程)│
│                   │    │                   │     │                       │
│ DeepSeekBackend ←─┤    │ file/exec/browser │     │ 不可用→回退 Hermes     │
│ StubBackend       │    │ scan/mcp/skill/cron│    │                       │
└───────────────────┘    └───────────────────┘     └───────────────────────┘

        ┌──────────────────────────┬──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────────┐    ┌───────────────────┐     ┌───────────────────────┐
│ MemoryCore        │    │ MemoryAdapter     │     │  ModelRegistry        │
│ (~/.xai/memory.db)│    │ (~/.xai/memory/   │     │  (~/.xai/models.json) │
│ 8 层 + project_id │    │  memos.db) 7 层   │     │  多模型 CRUD+激活      │
└───────────────────┘    └───────────────────┘     └───────────────────────┘

        ┌──────────────────────────┬──────────────────────────┐
        ▼                          ▼                          ▼
┌───────────────────┐    ┌───────────────────┐     ┌───────────────────────┐
│ ProjectManager    │    │ LoopSafety        │     │ ProviderFallback      │
│ (~/.xai/projects  │    │ (~/.xai/loop_     │     │ (设计完整但 .infer()  │
│  .db)             │    │  safety.json)     │     │  零调用)              │
└───────────────────┘    └───────────────────┘     └───────────────────────┘
```

#### 数据流图（对话主链路）

```
用户输入
  │
  ▼
[XAIEngine.chat] ── yield {"type":"start"}
  │
  ├─► _parse_slash ──── 是命令 ──► _handle_slash ──► yield answer/done
  │
  └─► _classify_intent ── yield {"type":"intent", ...}
        │
        ├─► _guard_action ──► classify ── yield {"type":"guard", ...}
        │     │
        │     └─► P0 ──► _create_approval ── yield {"type":"approval", ...} ──► done
        │
        └─► _execute_intent
              │
              ├─ code_dev  ──► _execute_code ─── Grok Build / Hermes
              ├─ browser   ──► _execute_browser ─ DuckDuckGo + 模型作答
              ├─ research  ──► _execute_browser
              ├─ memory    ──► _execute_memory_query
              └─ 其他       ──► _execute_general ─ DeepSeek stream_complete
              │
              ▼
        [token / answer / progress / deliverable / error 事件流]
              │
              ▼
        _sessions.add(user/assistant)
        _safe_memory_core_write(short_term + meta.project_id)
              │
              ▼
        yield {"type":"done"}
```

#### 组件清单与状态

| 类别 | 组件 | 文件 | 状态 |
|---|---|---|---|
| 编排 | XAIEngine | `core/engine_xai.py` (1272 行) | ✅ Active |
| HTTP 服务 | server_xai | `server_xai.py` (585 行) | ✅ Active |
| 适配器 | OpenClawAdapter | `core/adapters/openclaw_adapter.py` (513 行) | ✅ Active |
| 适配器 | HermesAdapter | `core/adapters/hermes_adapter.py` (331 行) | ✅ Active |
| 适配器 | MemoryAdapter | `core/adapters/memory_adapter.py` (327 行) | ⚠️ 半活跃（仅 /remember /recall 用） |
| 模型后端 | DeepSeekBackend | `core/deepseek_backend.py` (158 行) | ✅ Active |
| 模型后端 | StubBackend | `core/model_backend.py` (76 行) | ✅ Active（无 key 时降级） |
| 模型注册 | ModelRegistry | `core/model_registry.py` (157 行) | ✅ Active |
| 意图路由 | IntentRouter | `core/intent_router.py` (150 行) | ⚠️ Active 但 routing 字段未消费 |
| Guardian | guardian | `core/guardian.py` (229 行) | ✅ Active |
| 控制环 | ControlLoop | `core/control_loop.py` (119 行) | ⚠️ 仅 /loop 入口 |
| 思考 | reason | `core/reason.py` (97 行) | ⚠️ 仅经 ControlLoop 可达 |
| 元认知 | meta | `core/meta.py` (120 行) | ⚠️ 仅经 ControlLoop 可达 |
| 长任务 | Runner | `core/runner.py` (94 行) | ❌ Inactive（无调用方） |
| 蒸馏 | Distiller / GepaEvolver | `core/distill.py` (121 行) | ⚠️ 仅 hermes.darwinian_evolve 真用 |
| 协同 | CoordinationBus | `core/coordination.py` (184 行) | ✅ Active（/api/coordination/chat） |
| 记忆 | MemoryCore | `core/memory_core.py` (246 行) | ✅ Active |
| 安全 | LoopSafety | `core/loop_safety.py` (191 行) | ⚠️ 仅 reset/check 调用 |
| 故障轮换 | ProviderFallback | `core/provider_fallback.py` (154 行) | ❌ .infer() 零调用 |
| Project | ProjectManager | `core/project.py` (164 行) | ✅ Active |
| 会话 | SessionStore | `core/session_store.py` (124 行) | ✅ Active |
| Grok Build | GrokBuildBridge | `core/grok_build_engine.py` (378 行) | ⚠️ 条件可用 |
| 画布 | workflow_bridge | `core/workflow_bridge.py` (211 行) | ⚠️ 仅旧 engine 用 |
| 旧引擎 | engine.py | `core/engine.py` (252 行) | ❌ 弃用（仅 test_platform.py 引用） |
| 旧服务 | server.py | `server.py` (240 行) | ❌ 弃用 |
| 旧网关 | openclaw_gateway / substrate / kb / orchestrator / skills / memory / model_router / distill | `core/*.py` | ⚠️ 旧蓝图组件，部分被 test_xai_core/v2/v3 测试但运行时不用 |

#### 关键设计决策

1. **模型无关**：所有上层逻辑只依赖 `ModelBackend` 抽象，换模型只换一个 Backend 实现。
2. **零外部依赖**：仅用 Python 标准库（`http.server` + `urllib` + `sqlite3`），无 Flask/FastAPI/requests/openai。
3. **本地优先**：记忆/会话/项目全部 SQLite，无云、无遥测、无主动上传。
4. **SSE 流式**：通用对话逐 token 推送（`token` 事件），`Connection: close` 避免客户端挂起。
5. **Guardian 内容级识别**：不一刀切 `general`，按 `rm -rf / force push / exec / network` 等模式升级风险等级。
6. **批准后真重执行**：审批卡片携带原意图与 session_id，`/approve` 后真正调 `_execute_intent`，不是只标记。
7. **拓扑排序执行画布**：Kahn 算法 + 环路检测 + 逐节点 SSE 反馈。
8. **Rust crate 命名对齐 Grok fork**：`xai-grok-{guardian,reason,meta,runner}` 独立可编译，未来并入 Grok fork。

### 3. Module Inventory（core/ 完整清单）

| 文件 | 行数 | 用途 | 关键类/函数 | 状态 | 依赖 |
|---|---|---|---|---|---|
| `__init__.py` | 70 | 包入口 + 旧蓝图组件 re-export | — | ✅ Active | 全部子模块 |
| `engine_xai.py` | 1272 | **编排引擎主类** | `XAIEngine` / `Intent` / `SlashCommand` / `SLASH_COMMANDS` / `INTENT_TYPES` | ✅ Active | adapters, guardian, model_backend, deepseek_backend, session_store, memory_core, intent_router, grok_build_engine, coordination, control_loop, model_registry, provider_fallback, loop_safety, project |
| `engine.py` | 252 | 旧编排引擎（弃用） | `XAIEngine` / `ResilientBackend` | ❌ Inactive | memory_core, substrate, coordination, guardian, intent_router, control_loop, model_backend, deepseek_backend |
| `control_loop.py` | 119 | 认知控制环（单向管线） | `ControlLoop` / `LoopResult` / `A2UIEvent` | ⚠️ 仅 /loop | guardian, meta, model_backend, reason |
| `coordination.py` | 184 | 多 Agent 协同总线 | `CoordinationBus` / `Agent` / `Message` / `ApprovalCard` | ✅ Active | memory_core |
| `deepseek_backend.py` | 158 | DeepSeek OpenAI 兼容后端 | `DeepSeekBackend` | ✅ Active | model_backend |
| `distill.py` | 121 | 自蒸馏 + GEPA 进化 | `Distiller` / `SkillSpec` / `GepaEvolver` / `EvolutionTrace` | ⚠️ 仅测试 | model_backend |
| `grok_build_engine.py` | 378 | 代码引擎抽象 + Grok 二进制桥接 | `CodeEngine` / `Stub*Tool` / `GrokBuildBridge` / `default_bridge` | ⚠️ 条件可用 | subprocess, shutil |
| `guardian.py` | 229 | 风险分级 + 审批队列 | `RiskLevel` / `Action` / `ApprovalResult` / `classify` / `approve` / `guard` / `ApprovalQueue` / `PermissionTier` | ✅ Active | — |
| `intent_router.py` | 150 | 意图分类（5 类 + 关键词评分） | `IntentType` / `IntentResult` / `IntentRouter` / `route_task` | ⚠️ routing 未消费 | — |
| `kb.py` | 112 | 本地知识库（RAG 桩） | `KnowledgeBase` / `Chunk` | ❌ Inactive | — |
| `loop_safety.py` | 191 | 5 重安全闸门 | `SafetyConfig` / `LoopSafety` / `PRESETS` | ⚠️ 2/5 调用 | — |
| `memory.py` | 159 | 旧统一记忆池 | `MemorySystem` / `UnifiedMemoryPool` | ❌ Inactive | — |
| `memory_core.py` | 246 | **8 层元认知记忆内核** | `MemoryCore` / `Layer` / `MemoryEntry` / `default_core` | ✅ Active | sqlite3 |
| `meta.py` | 120 | 元认知校准 + L8 审计 | `BrierCalibrator` / `reflect` / `L8Auditor` / `AuditDim` / `ReflectResult` | ⚠️ 仅经 ControlLoop | guardian |
| `model_backend.py` | 76 | 模型后端抽象 | `ModelBackend` / `StubBackend` / `ModelResponse` | ✅ Active | — |
| `model_registry.py` | 157 | 多模型 CRUD + 激活 | `ModelRegistry` / `ModelEntry` / `default_registry` | ✅ Active | — |
| `model_router.py` | 77 | 节点级多模型路由 | `ModelRouter` / `ModelProfile` | ❌ Inactive | — |
| `openclaw_gateway.py` | 233 | 旧执行网关抽象 | `Gateway` / `*Adapter` / `Stub*Adapter` | ❌ Inactive | — |
| `orchestrator.py` | 80 | 多 Agent DAG 编排 | `Orchestrator` / `Node` / `Graph` | ❌ Inactive | — |
| `project.py` | 164 | Project 管理 | `ProjectManager` / `Project` / `default_project_manager` | ✅ Active | sqlite3 |
| `provider_fallback.py` | 154 | 故障轮换引擎 | `ProviderFallback` / `FallbackState` / `default_fallback` | ❌ .infer() 零调用 | model_registry |
| `reason.py` | 97 | 思考增强 | `Budget` / `thinking_budget` / `thinking_protocol` / `self_refine` / `multi_trajectory` / `Trajectory` | ⚠️ 仅经 ControlLoop | model_backend |
| `runner.py` | 94 | 长任务执行 | `Runner` / `RunState` / `StepResult` | ❌ 无调用方 | — |
| `session_store.py` | 124 | 会话历史 SQLite | `SessionStore` | ✅ Active | sqlite3 |
| `skills.py` | 128 | 技能注册（旧） | `SkillRegistry` / `Skill` | ❌ Inactive | — |
| `substrate.py` | 254 | OpenClaw 本地等价（旧） | `SubstratePort` / `LocalSubstrate` / `default_substrate` | ❌ 仅旧 engine 用 | memory_core |
| `workflow_bridge.py` | 211 | 画布 DAG 桥接（旧） | `execute_workflow` / `topo_order` | ⚠️ 仅旧 engine 用 | kb, model_router, guardian, meta, intent_router, memory |
| `adapters/base.py` | 48 | 适配器抽象基类 | `Adapter` / `AdapterResult` | ✅ Active | — |
| `adapters/openclaw_adapter.py` | 513 | **OpenClaw 适配器** | `OpenClawAdapter` | ✅ Active | base, shlex, subprocess, webbrowser |
| `adapters/hermes_adapter.py` | 331 | **Hermes 适配器** | `HermesAdapter` | ✅ Active | base, subprocess |
| `adapters/memory_adapter.py` | 327 | MemOS 适配器（双轨之一） | `MemoryAdapter` / `MemoryLayer` | ⚠️ 半活跃 | base, sqlite3 |

**总计**：core/ 28 个 .py 文件，约 5500 行；其中 14 个 ✅ Active、7 个 ⚠️ 部分活跃、7 个 ❌ 弃用/Inactive。

### 4. API Reference

#### HTTP 端点（`server_xai.py::XAIHandler`）

| 方法 | 路径 | 用途 | 请求 | 响应 |
|---|---|---|---|---|
| GET | `/` | 前端入口 | — | `web/index.html` |
| GET | `/web/<file>` | 静态资源 | — | app.js / styles.css（带 `Cache-Control: no-cache`） |
| GET | `/api/status` | 系统状态 | — | `{xai_engine, model, project, openclaw, hermes, memory, memory_core_layers, grok_build, models, pending_approvals, slash_commands}` |
| GET | `/api/memory` | 记忆统计 | — | `{adapter: {...}, core: {layer: count}, core_db: "~/.xai/memory.db"}` |
| GET | `/api/approvals` | 待审批列表 | — | `{approvals: [{id, type, detail, intent, reason, status, session}]}` |
| GET | `/api/history` | 会话列表 | — | `{sessions: [{session, last_role, last_content, ts}]}` |
| GET | `/api/session/<sid>` | 单会话历史 | — | `{session, messages: [{role, content}]}` |
| GET | `/api/open?name=<stored>` | 本地打开文件 | query: name | `{ok, path}` 或 `{ok:false, error}` |
| GET | `/api/agents` | Agent 列表 + 房间 | — | `{agents: [{name, role, backend, id}], rooms: [...]}` |
| GET | `/api/coordination/rooms` | 群聊房间列表 | — | `{rooms: [...]}` |
| GET | `/api/distill` | 触发自蒸馏 | — | `{ok, distilled: N, stored_as: "distill:<ts>", sample: [...]}` |
| GET | `/api/models/list` | 模型列表 | — | `{models: [...], stats: {total, active}}` |
| GET | `/api/models/activate/<id>` | 激活模型 + 重建后端 | — | `{ok, active: {...}}` |
| GET | `/api/loop-safety` | Loop Safety 配置 | — | `{config, runtime, presets}` |
| GET | `/api/projects` | 项目列表 + 当前 | — | `{current: {...}, list: [...]}` |
| GET | `/api/projects/activate/<pid>` | 切换项目 | — | `{ok, project: "name"}` |
| POST | `/api/chat` | **SSE 流式对话** | `{text, session, attachments}` | `text/event-stream`（见下） |
| POST | `/api/chat/send` | 非流式对话 | `{text, session, attachments}` | `{answer, session, errors?}` |
| POST | `/api/workflow/run` | **SSE 工作流执行** | `{nodes, edges}` | `text/event-stream`（见下） |
| POST | `/api/upload` | 上传文件（base64） | `{name, mime, data_base64}` | `{ok, name, stored, path}` |
| POST | `/api/save` | 保存生成内容 | `{name, content, ext}` | `{ok, stored: "artifacts/<name>.<ext>", path}` |
| POST | `/api/coordination/chat` | 群聊发消息 | `{agent, text, room}` | `{ok, msg_id, room, history: [...]}` |
| POST | `/api/models/add` | 添加模型 | `{name, provider, model, base_url, api_key}` | `{ok, model: {...}}` |
| POST | `/api/models/delete` | 删除模型 | `{id}` | `{ok: bool}` |
| POST | `/api/loop-safety-update` | 改 Loop Safety 阈值 | `{preset?}` 或 `{key, value}` 或扁平字段 | `{ok, config: {...}}` |
| GET | `/api/system/health` | 引擎健康摘要（**豁免鉴权**） | — | `{healthy, ts, xai_engine, model, project, ...}` |
| GET | `/api/system/sandbox` | 当前硬沙箱策略（**豁免鉴权**） | — | `{os, available_backends, policy, effective}` |
| GET | `/api/system/errors` | 系统级错误追踪（环缓冲，供 ErrorPanel） | — | `{count, tracked_since, errors[]}` |
| GET | `/api/system/status` | `/api/status` 别名（兼容 legacy 契约） | — | `{...LATEST_STATUS, ts}` |

**未实现的常用端点**：`/api/health`（裸路径仍 404，已提供 `/api/system/health` 替代）、`do_HEAD`（501）。`/api/knowledge/search` 空查询此前会 IndexError（B4 已修复，现返回 `{ok:true, hits:[]}`）。

#### SSE 事件类型

**`/api/chat`** 事件流（`engine_xai.py::chat`）：

| type | 字段 | 说明 |
|---|---|---|
| `start` | `text` | 引擎就绪 |
| `intent` | `intent, confidence, rationale` | 意图分类结果 |
| `guard` | `level, reason` | 风险等级（P0/P1/P2） |
| `approval` | `id, level, action, message` | P0 待审批卡片 |
| `progress` | `stage, text` | 执行进度（task_plan/code_gen/code_check/search/answer/loop/fallback/attach/gb_fallback/diagnose/evolve） |
| `token` | `text` | 流式文本片段（通用对话逐字推送） |
| `answer` | `answer` | 最终回答（命令/非流式结果） |
| `deliverable` | `name, stored, lang, content` | 交付物卡片（代码、结果 JSON） |
| `reset` | `reason` | 流重置（fallback 时） |
| `error` | `error` | 错误（绝不静默） |
| `done` | — | 结束标志（客户端见到 `[DONE]` 后断流） |

**注意**：斜杠命令（`/help`、`/status` 等）的事件流不含 `intent` / `guard`，直接走 `answer` + `done`。
**非流式 `/api/chat/send` 已知缺陷**：只收集 `answer` 事件，通用对话走 `token` 事件 → 普通聊天永远返回空答案（见 Known Issues）。

**`/api/workflow/run`** 事件流（`engine_xai.py::run_workflow`）：

| type | 字段 | 说明 |
|---|---|---|
| `wf_start` | `total` | 工作流开始 |
| `wf_node` | `node_id, status (running/done/error), index, total, label, ntype, output` | 节点状态变化 |
| `progress` | `stage, text` | 节点内进度（如"推理中..."） |
| `wf_done` | `result` | 工作流完成（含最终结果汇总） |
| `error` | `error` | 致命错误（如环路检测） |
| `[DONE]` | — | 流结束 |

#### WebSocket

无。所有实时通信走 SSE。

### 5. Frontend Architecture

> **三前端事实（2026-07-22，A0=a）**：仓库并存三个前端——
> 1. **V4 `frontend/`**（React+Vite，OllamaFLOW 派生）— **官方产品控制台**，`server_xai.py` 经 `WEB_DIR=frontend/dist` 托管，生产 `:8000` 直出。
> 2. `xai-frontend/`（OllamaFLOW Electron fork，849M）— **legacy / 参考**，含 5 个 `PlaceholderPage` 空壳，未对齐 V4 契约，2026-07-22 降权。
> 3. `web/`（vanilla JS 4-Tab）— **参考实现**，纯前端零业务逻辑，能力对照用。
> 下文先述产品前端 V4（12 页 + 契约），再附 `web/` 4-Tab 参考。

#### V4 产品前端（`frontend/`，React+Vite，12 页）

纯视图层，零业务逻辑，全部经 HTTP/SSE 调后端；液态玻璃设计系统（Liquid Glass），亮/暗双主题，3D 特效层（`effects.css`）。12 页 + 后端契约（2026-07-22 F2 走查全绿，均 200 + 真实数据）：

| 页面 | 后端契约（GET 为主，POST 标注） | 走查结果 |
|---|---|---|
| Dashboard 仪表盘 | `/api/status` `/api/agents` `/api/dashboard` `/api/memory/stats` | ✅ 全 200，dashboard 72KB 真实负载 |
| AgentWorkspace 智能体工作台 | `/api/agents` | ✅ 200 |
| TaskCanvas 任务画布 | `/api/agents` `/api/status` | ✅ 200 |
| Timeline 时间线 | `/api/workflow/history` | ✅ 200（`{history:[]}`，新系统暂无工作流，预期空） |
| MemoryCenter 记忆中心 | `/api/memory/stats` | ✅ 200 |
| GuardianCenter 治理中心 | `/api/guardian/pending` `POST /api/guardian/approve` | ✅ 200（`{pending:[]}`，无待审，预期空） |
| EvolutionCenter 进化中心 | `/api/gepa/status` `/api/memory/list` | ✅ 200（GEPA 未跑过，generation=0 预期） |
| ChatConsole 对话台 | `POST /api/chat`（SSE，经 `lib/api.ts`） | ✅ SSE 实流 start→intent→guard→progress |
| SessionHistory 会话历史 | `/api/sessions` `/api/sessions/<id>/messages` `DELETE /api/sessions/<id>` | ✅ 全 200 |
| CapabilityRegistry 能力注册表 | `/api/capabilities` | ✅ 200 |
| ToolHub 工具中心 | `/api/connectors` `/api/mcp/list` `/api/skills` | ✅ 全 200 |
| KnowledgeBase 知识库 | `/api/knowledge/search` `/api/knowledge/stats` | ✅ 200（B4 修复空查询 IndexError；stats 真实） |

> 走查方法：对 `:8000` 实服务逐端点 curl（带 `X-Auth-Token`），15 个端点全 200，无 404/500。空响应均为"新系统暂无数据"预期，非契约缺陷。

#### 4 Tab 及功能（`web/index.html` + `web/app.js`，参考实现）

| Tab | view id | 功能 | 关键 JS 函数 |
|---|---|---|---|
| **对话 chat** | `view-chat` | 三栏工作台：会话栏 / 对话历史 / 成果区；SSE 流式渲染、附件上传、斜杠命令芯片、模型选择器、P0 审批卡片、Markdown + 代码块复制 | `checkConnection`, `loadModels`, `sendMessage`, `handleSSEEvent`, `addTimeline`, `addDeliverable`, `openLocalFile`, `saveAndOpenMd`, `escapeHtml`, `inlineMd`, `topoFromIntent`, `topoAddNode`, `topoRender` |
| **画布 canvas** | `view-canvas` | 20 种可拖节点（chat/react/router/skill/mcp/exec/file/scan/git/gb_gen/gb_refactor/gb_test/agent_hermes/agent_grok/agent_pm/mem_query/input/output/condition/loop）+ DAG 编辑器（拖线/删线/缩放/平移）+ Kahn 拓扑排序执行 + 节点属性面板 | `canvas*` 系列（拖拽/连线/选择/属性）, `wfRun`, `wfSave`, `wfLoad`, `wfExport`, `wfFit`, `wfClear`, `ciPopulate` |
| **群聊 room** | `view-room` | 多 Agent 群聊室：左侧 Agent 列表 + 右侧消息流 + 输入框 | `roomLoadAgents`, `roomSend` |
| **管理 settings** | `view-settings` | 9 个 settings-card：技能 / MCP / 记忆 / 自动化 / 安全扫描 / Darwinian 进化 / 治理闸门 / AI 模型 / Loop 安全闸门；模型管理面板（模态） | `runSettingsCmd`, `showSkillInput`, `loadLoopSafety`, `updateSafety`, `resetSafetyPreset`, `toggleModelPanel`, `addModel`, `deleteModel`, `activateModel` |

**成果区 4 子面板**（对话 Tab 右栏）：
- **拓扑 topo**：对话驱动的 DAG 展示（`topoFromIntent` 从 SSE `intent` 事件自动绘制节点）
- **执行过程 process**：时间线（`addTimeline` 记录意图/治理/进度/交付/错误）
- **交付物 deliver**：代码/文件卡片（📂 打开 / 📋 复制 / ⬇️ 下载）
- **进化 evolve**：自蒸馏按钮（调 `/api/distill`）

#### 关键 JS 函数索引（`web/app.js` 1361 行）

| 行号 | 函数 | 作用 |
|---|---|---|
| 14 | `$` | `getElementById` 快捷方式 |
| 18 | `initTheme` | 浅色/深色主题切换（localStorage 持久化） |
| 33 | `checkConnection` | 调 `/api/status` 更新状态栏 + Project chip |
| 67 | `loadModels` | 调 `/api/chat`（`/models` 命令）拉模型列表填充下拉 |
| 82 | `sel.onchange` | 切换模型 → 调 `/api/models/activate/<id>` |
| 95 | `readSSEText` | 读 SSE 流为纯文本（用于非流式 UI） |
| 112 | 视图切换 | 4 Tab `.nav-item` 切换 |
| 122 | `.ptab` 切换 | 成果区 4 子面板 |
| 135 | `resetPanels` | 清空执行过程/交付物 |
| 146 | `addTimeline` | 追加时间线条目 |
| 157 | `addDeliverable` | 追加交付物卡片 |
| 175 | `openLocalFile` | 调 `/api/open?name=` 用本机默认应用打开 |
| 182 | `saveAndOpenMd` | 调 `/api/save` + `/api/open` |
| 585 | `escapeHtml` | HTML 转义（XSS 防护第一道） |
| 623 | `inlineMd` | 极简 Markdown 渲染（链接白名单 http(s)） |
| 1182 | `loadLoopSafety` | 调 `/api/loop-safety` 渲染配置 UI |
| 1213 | `updateSafety` | POST `/api/loop-safety-update` |
| 1240 | `roomLoadAgents` | 调 `/api/agents` 渲染 Agent 列表 |
| 1249 | `roomSend` | POST `/api/coordination/chat` |
| 1268 | `TOPO` 全局对象 | 拓扑节点/边状态 |
| 1326 | `topoFromIntent` | 从 SSE intent 事件自动绘制拓扑 |
| 1352 | `handleSSEEvent` hook | 包装原函数，注入拓扑自动绘制 |

#### CSS 设计系统（`web/styles.css` 807 行）

- **CSS 变量**：`--brand` (#635bff) / `--bg` / `--bg-panel` / `--text` / `--text-muted` / `--border` 等；`data-theme="light|dark"` 切换。
- **布局**：`#app { display: flex }` — 左 `#rail` (220px) + 主 `#stage` (flex 1)。
- **三栏工作台**：`.workbench { display: flex }` — 中 `.wb-center` (flex 1) + 右 `.wb-right` (360px)。
- **响应式**：min-width 固定，主要面向桌面（≥1024px）。
- **组件**：`.chip` / `.btn-send` / `.nav-item` / `.ptab` / `.deliver-card` / `.tl-item` / `.topo-node` 等。
- **内联关键样式**：`index.html` 头部含 60 行 `<style>` 内联，绕过缓存。

#### 已知前端限制

1. **非流式 `/api/chat/send` 对普通对话返回空**：只收集 `answer` 事件，通用对话走 `token` 事件 → 永远为空（见 Known Issues #6）。
2. **画布节点不引用能力注册表**：20 种节点硬编码在前端，无 by-name 能力调用。
3. **画布节点仅 6 类有真实后端语义**（input/scan/mcp/exec/file/git），其余 14 类落通用模型推理。
4. **`to-canvas-btn` 跳转失效**：点击后 100ms 又点回对话视图（`app.js:1233-1237`）。
5. **响应式不足**：移动端 / 平板布局不友好。
6. **无 Artifacts 级富渲染**：交付物仅代码块级，无 HTML/SVG/React 组件预览。

### 6. Data Storage

#### SQLite 数据库

| 路径 | 用途 | schema 关键字段 | 创建者 |
|---|---|---|---|
| `~/.xai/memory.db` | **8 层元认知记忆内核**（单一事实源目标） | `memory(id, layer, engine, key, value, importance, meta, created_at, accessed_at)` + 3 索引 | `core/memory_core.py::MemoryCore._init_schema` |
| `~/.xai/memory/memos.db` | MemOS 兼容记忆（双轨之一，未消除） | `memories(id, layer, engine, content, meta, importance, created_at, updated_at, expires_at)` + `memory_index(id, memory_id, keyword)` + 4 索引；WAL 模式 | `core/adapters/memory_adapter.py::MemoryAdapter._init_db` |
| `~/.xai/sessions.db` | 多会话历史 | `messages(id, session, role, content, ts)` + `idx_session` 索引；WAL 模式 | `core/session_store.py::SessionStore._init_db` |
| `~/.xai/projects.db` | Project 管理 | `projects(id, name, description, workspace, instructions, budget, created_at, updated_at)` + `idx_project_name` | `core/project.py::ProjectManager._init_schema` |

实测 `~/.xai/` 目录内容：`memory.db` / `memos.db` / `memos.db-shm` / `memos.db-wal` / `models.json` / `projects.db` / `sessions.db` / `workspace/`。

#### 配置文件

| 路径 | 用途 | 创建者 |
|---|---|---|
| `~/.xai/models.json` | 多模型注册表（`{models: [ModelEntry...]}`） | `core/model_registry.py::ModelRegistry._save` |
| `~/.xai/loop_safety.json` | Loop Safety 配置（5 字段 + 3 预设） | `core/loop_safety.py::LoopSafety.save` |
| `~/.xai/server.pid` | 运行时 PID 锁（防多实例） | `server_xai.py::_acquire_pid_lock` |
| `~/.zshrc` | `DEEPSEEK_API_KEY` 真源（启动器解析注入） | 用户手动 |

#### 文件系统布局

```
~/.xai/
├─ memory.db                  # 8 层元认知记忆
├─ memory/
│  └─ memos.db                # MemOS 兼容记忆（双轨）
├─ sessions.db                # 会话历史
├─ projects.db                # Project 管理
├─ models.json                # 模型注册表
├─ loop_safety.json           # Loop Safety 配置
├─ server.pid                 # 运行时 PID
└─ workspace/                 # OpenClaw 工作区（用户数据）
   ├─ uploads/                # 用户上传文件（时间戳前缀）
   ├─ artifacts/              # 生成产物（/api/save 落点）
   ├─ knowledge/              # 本地知识库（自动注入上下文）
   ├─ hermes_skills/          # Hermes 技能 JSON
   ├─ hermes_evo/             # GEPA 待复审变异
   └─ cron/                   # 定时任务 JSON
```

### 7. Security

#### Guardian P0/P1/P2 机制（`core/guardian.py`）

```python
RISK_RULES = {
    "delete_file":     (P0, "删除文件可能不可逆"),
    "overwrite_file":  (P0, "覆盖文件会丢失原内容"),
    "force_push":      (P0, "强制推送会改写远端历史"),
    "secret_write":    (P0, "写入凭证/密钥有泄露风险"),
    "rm_rf":           (P0, "递归删除系统目录极度危险"),
    "run_command":     (P1, "执行命令可能改变系统状态"),
    "network":         (P1, "网络请求可能外发数据"),
    "install_pkg":     (P1, "安装包引入第三方代码"),
    "read_file":       (P2, "只读操作低风险"),
    "compute":         (P2, "纯计算低风险"),
}
```

- **P0（致命）**：拦截 → 入审批队列 → `/approve` 后真重执行。`auto_mode=True` 时默认拒绝。
- **P1（高危）**：记录 + 提示，可自动放行但留痕。
- **P2（常规）**：自动通过。

**内容级识别**（`engine_xai.py:1060-1085`）：
- `_DANGEROUS_PATTERNS`：`rm -rf` / `sudo rm` / `mkfs` / `format` / `force push` / `git push -f` / `drop table` 等 → `rm_rf` (P0)
- `_DELETE_PATTERNS`：`删除文件` / `rm ` / `del ` / `shutil.rmtree` / `os.remove` → `delete_file` (P0)
- `_EXEC_PATTERNS`：`执行命令` / `exec ` / `bash ` / `powershell` → `run_command` (P1)
- `_NETWORK_PATTERNS`：`联网` / `http://` / `https://` / `curl ` / `fetch(` → `network` (P1)

#### 路径穿越防护

1. **OpenClawAdapter._safe_path**（`openclaw_adapter.py:94-99`）：`Path(workspace / filename).resolve()` 必须以 workspace 为前缀，否则抛 `ValueError`。
2. **server_xai._resolve_workspace_file**（`server_xai.py:273-292`）：拒绝 `..` / 绝对路径 / `\` 开头；依次尝试 `name` / `uploads/name` / `artifacts/name`，每个都验证在 workspace 内。
3. **server_xai._handle_save**（`server_xai.py:326-327`）：`ext` 仅允许 `[a-zA-Z0-9.]`，截断 12 字符；`name` 用 `isalnum() + ._-` 净化。**审计 P1-32 路径穿越漏洞已修复**。
4. **server_xai._handle_upload**（`server_xai.py:304`）：`os.path.basename(raw_name)` 剥离路径，拒绝 `.` / `..`。

#### XSS 防护

1. **escapeHtml**（`app.js:585`）：`&` / `<` / `>` 转义。
2. **inlineMd**（`app.js:623`）：极简 Markdown 渲染，先 escapeHtml 再 inlineMd；链接白名单仅 `http(s)://`。
3. **交付物内容用 textContent**（`app.js:165`）：`card.querySelector("code").textContent = code` 不走 innerHTML。

#### API Key 处理

1. **存储**：`~/.zshrc` 环境变量 `DEEPSEEK_API_KEY`（不落盘项目目录）。
2. **注入**：启动器（`xai_go.sh` / `启动XAI.command`）用 `xai_read_key.py` 从 `~/.zshrc` 解析后 `export`。
3. **掩码**：`ModelEntry.mask_key()` 返回 `sk-d***fd55` 形式；`/api/models/list` 和 `/api/status` 永远返回掩码版。
4. **XAI.app 已知缺陷**：`xai_launcher.py` 用 `os.environ.copy()`，不像 `xai_go.sh` 会解析 `~/.zshrc` → 双击 App 启动会落 StubBackend（见 Known Issues）。

### 8. Testing

#### 测试文件清单

| 文件 | 行数 | 覆盖范围 | 运行方式 |
|---|---|---|---|
| `tests/test_xai_core.py` | 7316 字节 | 旧蓝图组件单测（guardian/reason/meta/runner/kb/orchestrator/distill/control_loop） | `pytest tests/test_xai_core.py` |
| `tests/test_xai_v2.py` | 5327 字节 | intent_router / openclaw_gateway / grok_build_engine / workflow_bridge | `pytest tests/test_xai_v2.py` |
| `tests/test_xai_v3.py` | 2938 字节 | v3 新增组件集成测试 | `pytest tests/test_xai_v3.py` |
| `tests/test_deepseek_backend.py` | 2333 字节 | DeepSeekBackend HTTP/流式（用 monkeypatch mock） | `pytest tests/test_deepseek_backend.py` |
| `tests/test_grok_build_engine.py` | 3284 字节 | CodeEngine + GrokBuildBridge | `pytest tests/test_grok_build_engine.py` |
| `tests/test_intent_router.py` | 2083 字节 | IntentRouter 5 类分类 | `pytest tests/test_intent_router.py` |
| `tests/test_openclaw_gateway.py` | 2765 字节 | 旧 Gateway 抽象 + Stub 适配器 | `pytest tests/test_openclaw_gateway.py` |
| `tests/test_platform.py` | 5943 字节 | 旧 engine.py + substrate 集成（含 `test_substrate_shell` 已知环境卡顿） | `pytest tests/test_platform.py` |
| `tests/test_workflow_bridge.py` | 4187 字节 | 画布 DAG 桥接 | `pytest tests/test_workflow_bridge.py` |
| `tests/selftest_e2e.py` | 9185 字节 | **端到端 13 项**：状态/帮助/任务/代码/搜索/记忆/审批/并发 | `python3 tests/selftest_e2e.py`（需服务在 8000） |
| `tests/selftest_e2e_round2.py` | 6657 字节 | **第二轮 13 项**：命令全量 + 边界 + 并发 | `python3 tests/selftest_e2e_round2.py` |
| `tests/selftest_files.py` | 4889 字节 | 上传/保存/打开文件流程 | `python3 tests/selftest_files.py` |
| `tests/selftest_memory_core.py` | 1855 字节 | MemoryCore 8 层 CRUD | `python3 tests/selftest_memory_core.py` |
| `tests/selftest_workflow.py` | 9481 字节 | 画布工作流端到端 | `python3 tests/selftest_workflow.py` |

**测试统计**：73 个单元测试（pytest）+ 5 个端到端自测脚本。审计基线全部通过；`test_platform.py::test_substrate_shell` 在新环境可能卡顿（`shell=True` 子进程管道悬挂，已在 `openclaw_adapter.py` 修复为 `shlex.split`）。

#### 已知测试缺口

1. **`ProviderFallback.infer()` 零测试**：tests/ 下无任何 fallback 主备切换用例。
2. **LoopSafety 5 闸门**：仅 `reset/check` 调用，3 闸门无端到端测试。
3. **ControlLoop.act()**：仅经 `/loop` 命令可达，无独立集成测试。
4. **Ollama 集成**：无测试（因为无实现）。
5. **Project 隔离**：无跨项目记忆污染测试。
6. **路径穿越**：`_handle_save` 修复后无回归测试。
7. **群聊 Tab**：接线后无端到端测试。

### 9. Known Issues & Technical Debt

#### MEDIUM 优先级问题

1. **`/api/chat/send` 非流式端点对普通对话返回空**（`server_xai.py:220-229`）：只收集 `answer` 事件，通用对话走 `token` 事件 → 永远为空。建议改为也累加 `token` 事件。
2. **`IntentRouter.routing` 字段零消费者**（`intent_router.py:58-64`）：5 类路由目标（openclaw_gateway/grok_build_engine/orchestrator/kb/reason）算出后无人用，引擎只取 `intent.value` 经 `routing_map` 映射。office/automation 落 general 兜底。
3. **双轨记忆**（`MemoryAdapter` + `MemoryCore`）：两个 SQLite 文件、两套层名（`short/long` vs `short_term/long_term`），/remember 写 memos.db，对话写 memory.db，/recall 走 cross_engine 跨两库。违反"单一事实源"宪法。
4. **`ProviderFallback.infer()` 零调用**：引擎自实现 `_infer_with_fallback` + `_execute_general` 内 try/except 两处复制逻辑。建议改为统一调 `fallback.infer(fn_call=lambda: hermes.infer(...))`。
5. **LoopSafety 3/5 闸门未接**：`record_error` / `record_result` / `check_context` 全无调用点。建议在 `_execute_general` / `_execute_code` / `run_workflow` 循环中接入。
6. **ControlLoop 仅 /loop 入口**：普通对话不经 Control Loop，Meta/Reason 的 Brier 校准与多轨迹思考能力未默认启用。
7. **Runner 完全未接**（`core/runner.py`）：长任务执行能力（分步 + checkpoint + 质量门 + 续跑）设计完整但运行时无调用方。
8. **Ollama 未集成**：`ModelRegistry` 支持 ollama provider，但 `_rebuild_backend()` 只懂 `DeepSeekBackend`，切到 ollama 时仍构造 DeepSeek 客户端。
9. **Project 隔离不完整**：`SessionStore` 不按 project 分会话；`workspace` 不随 project 切换；`MemoryAdapter` 无 project_id。
10. **`_cmd_approve` 硬编码 session "default"**（审计 P2-7，未修复）：非 default 会话发起的 P0 审批，批准后重执行可能丢失原会话上下文（实际上 `engine_xai.py:927` 已改为 `sid = rec.get("session") or "default"`，审计描述滞后）。
11. **`/api/models/activate/<id>` 用 GET 产生副作用**（审计 P2-35）：应改 POST/PUT。
12. **缺 `/api/health` 与 `do_HEAD`**（审计 P2-35）：外部探测 404/501。
13. **MemoryAdapter 无线程锁**（审计 P1-9）：共享单连接 + `BEGIN IMMEDIATE` 但无线程锁，ThreadingMixIn 并发下事务可交叉。
14. **HermesAdapter 传 `system=` 被 DeepSeekBackend 静默丢弃**（审计 P1-10，`deepseek_backend.py:127`）：技能进化时系统指令失效。
15. **`xai_mock_server.py` bytes 字面量含无效 `\u` 转义**（审计 P2-11，Python 3.12+ SyntaxWarning）。

#### LOW 优先级问题

16. **`XAI.app` 双击即落 Stub**（审计 P1-31）：`xai_launcher.py` 用 `os.environ.copy()`，不像 `xai_go.sh` 会解析 `~/.zshrc` → 无 key → StubBackend。建议改为复用 `xai_go.sh` 逻辑。
17. **解释器路径硬编码**（审计 P2-33）：`xai_go.sh:9` / `启动XAI.command:9` 写死 `.../python/3.13.12/bin/python3`；`XAI.app` 又是另一套（`/usr/bin/python3`）——三处不一致。
18. **`xai_launcher.py:41` 仍用 `pkill -f server_xai.py`**（审计 P2-34）：QA 报告称已修，但只修了 `启动XAI.command`。
19. **双引擎 + 双服务端 + 三前端重复**（审计 P1-5）：`core/engine.py`（旧）+ `core/engine_xai.py`（新）；`server.py`（旧）+ `server_xai.py`（新）；`web/`（交付所用）+ `frontend/`（旧 React+Vite）+ `xai-frontend/`（849M OllamaFlow Electron）。建议归档/删除旧的。
20. **`to-canvas-btn` 跳转失效**（审计 P2-28）：点击后 100ms 又点回对话视图（`app.js:1233-1237`）。
21. **画布 14/20 节点落通用模型推理**（审计 P2-29）：仅 `input/scan/mcp/exec/file/git` 6 类有真实后端语义，`gb_*/agent_*/mem_query/condition/loop` 全落通用推理。
22. **拓扑 Tab `topoFromIntent` 几乎永不命中**：审计 P2-26 描述此问题——规则用针对用户中文文本设计的正则去匹配 `ev.intent`（英文类型串）。当前 `app.js:1326-1349` 已部分修复（加了英文 intent 匹配 + 中文命令匹配），但覆盖仍不完整。
23. **无 git 版本控制**（审计 P2-37）：仓库根无 `.git`，靠 19 个 `.bak.20260718...` 时间戳备份文件撑回滚。
24. **`vendor/` 728M + `xai-frontend/` 849M 裸放无 .gitignore**（审计 P2-37）。
25. **`xai_mock_server.py` 与真实服务互踢端口**（审计 P2-36）：都绑 8000。
26. **`server_xai.pid` 残留**（审计 P2-36）：仓库根有残留 pid 文件，与 `~/.xai/server.pid` 双 pid 文件困惑。
27. **`/api/models/list` 是死端点**（审计 P2-35）：前端走 `/api/status` 拉模型列表。
28. **`_classify_intent` 双轨分类**（审计 P1-4）：`IntentRouter` 一套词表，`_classify_intent` 内部另一套 rules，两套 taxonomy 不一致。
29. **`_retrieve_memory_context` 多处 `except Exception: pass`**（审计 P1-6，部分修复）：与"零静默失败"原则冲突；现已改为调 `self._log(...)` 但仍吞错。
30. **联网搜索结果 URL 永远为空**（审计 P1-3，未修复）：`engine_xai.py:_web_search` 解析了标题和摘要，但 URL 提取正则 `class="result-link"[^>]*href="([^"]+)"` 与 DuckDuckGo lite 实际 HTML 不匹配 → `[1][2]` 引用无落点。
31. **`CoordinationBus.publish` 每条群聊消息写 memory_core short_term**（审计 P1-20）：无 `consolidate()` 定期调度 → 记忆单调膨胀。

#### Stale Modules（弃用但未删）

- `core/engine.py`（252 行）— 旧编排引擎，仅 `tests/test_platform.py` 引用。
- `server.py`（240 行）— 旧 HTTP 服务。
- `core/substrate.py`（254 行）— 旧执行底座，仅旧 engine 用。
- `core/openclaw_gateway.py`（233 行）— 旧网关抽象。
- `core/kb.py` / `core/orchestrator.py` / `core/skills.py` / `core/memory.py` / `core/model_router.py` — 旧蓝图组件，仅旧测试用。
- `core/workflow_bridge.py`（211 行）— 旧画布桥接，仅旧 engine 用。
- `frontend/`（V4 React+Vite，OllamaFLOW 派生 12 页）— **2026-07-22 扶正为官方产品控制台（A0=a 决策）**。11 个业务页 + 1 启动页，纯视图层；`server_xai.py` 的 `WEB_DIR` 已切到 `frontend/dist`，生产服务 `:8000` 直接托管。详见 Part 2 §5。
- `xai-frontend/`（OllamaFlow liquid-glass Electron fork，849M）— **2026-07-22 降为 legacy / 参考架构**（A0=a 决策反转此前 Route A 扶正）。七模块（对话/任务/专家团/自动化/定时/画布/管理）融合重构中止；含 5 个 `PlaceholderPage` 空壳，未与 V4 后端契约对齐。保留代码不删，便于回溯，但不再是主线路。
- `web/`（vanilla JS 4-Tab）— 参考实现，纯前端零业务逻辑，作为能力对照保留。

#### Missing Features vs Blueprint

- **L4 Verify**：蓝图称 Control Loop 第 4 步，代码库无此组件。
- **diary/日记层**：宪法 7 层之一，MemoryCore 未实现（多了 failure_correction）。
- **Ollama 集成**：宪法双选之一，无 OllamaBackend 类。
- **ACP/MCP 协议通信 Grok Build**：宪法要求，实际用 subprocess JSON。
- **能力注册表驱动 UI 节点**：蓝图§6 要求，未实现（前端硬编码 20 种节点）。
- **企业多用户 / SSO / RBAC**：单机单用户，无 LDAP/OIDC/SCIM。
- **语义 RAG / 向量检索**：当前为关键词 SQLite 记忆，无向量语义检索。
- **可观测 / 成本追踪**：仅 `/diagnose` 体检，无 OpenTelemetry / Langfuse / 成本看板。
- **语音 / 图像 / 终端富渲染**：仅代码块级交付物，无 TTS/STT/Artifacts。

### 10. Setup & Deployment

#### 启动方法（3 种）

**方式一：脚本启动（推荐，自动注入 key）**

```bash
cd /Users/Admin/Desktop/mask/xai
./xai_go.sh            # 或双击 启动XAI.command
```

- 解析 `~/.zshrc` 取 `DEEPSEEK_API_KEY`，注入子进程环境。
- 用 `~/.workbuddy/binaries/python/versions/3.13.12/bin/python3` 固定解释器。
- 后台拉起 `server_xai.py`，浏览器自动打开 `http://localhost:8000`。

**方式二：直接起服务**

```bash
cd /Users/Admin/Desktop/mask/xai
DEEPSEEK_API_KEY=xxx python3 server_xai.py
# → http://localhost:8000
```

**方式三：桌面 App**

双击 `XAI.app`（macOS）。

- **已知缺陷**：`xai_launcher.py` 用 `os.environ.copy()`，不解析 `~/.zshrc` → 若 GUI 环境无 key，落 StubBackend。建议改用方式一。
- `xai_launcher.py` 后台拉起 `server_xai.py`，等端口就绪后用 Chrome app 模式或 Safari 打开独立窗口。

#### 环境变量

| 变量 | 默认 | 用途 |
|---|---|---|
| `DEEPSEEK_API_KEY` | （无） | DeepSeek API key，缺失则降级 StubBackend |
| `XAI_HOME` | `~/.xai` | 数据根目录（SQLite + 配置 + workspace） |
| `XAI_WORKSPACE` | `$XAI_HOME/workspace` | OpenClaw 工作区 |
| `XAI_PORT` | `8000` | HTTP 服务端口 |
| `XAI_HOST` | `localhost` | HTTP 服务绑定地址 |

#### 依赖

- **Python**：3.10+（用 `from __future__ import annotations` 保护）；测试基线 3.13.12。
- **标准库**：`http.server` / `socketserver` / `urllib` / `sqlite3` / `subprocess` / `json` / `re` / `pathlib` / `threading` / `hashlib` / `shlex` / `webbrowser` / `fcntl` / `signal` / `atexit`。
- **无第三方 Python 包**：无 Flask/FastAPI/requests/openai/langchain/...
- **可选系统命令**：`openclaw`（真实模式）、`hermes`（CLI 模式）、`grok`（Grok Build 桥接）、`ollama`（仅展示，未集成）。
- **浏览器**：Chrome / Edge / Brave（app 模式）/ Safari（AppleScript 干净窗口）。

#### 浏览器要求

- 现代浏览器支持 `fetch` + `ReadableStream`（SSE 流式）。
- 推荐Chrome 90+ / Edge 90+ / Safari 15+ / Firefox 90+。
- 强刷快捷键：Cmd+Shift+R（macOS）。

### 11. Changelog（2026-07-18 本次会话变更）

> 本节仅记录 2026-07-18 当天源码层面的实质变更。审计报告 17:52 快照后修复的 bug 也在此列。

#### 对话主链路

- **修复 `/loop` 命令 100% 报错**（审计 P0-1）：`engine_xai.py:953` 将 `self.control_loop.run(task)` 改为 `self.control_loop.act(task)`，对齐 `ControlLoop` 真实方法名。
- **修复 `_guard_for_coordination` TypeError**（审计 P0-2）：`engine_xai.py:1257` 改为 `classify(Action(kind=kind or "general", target=task[:200]))`，字段名匹配 `Action` dataclass。
- **修复记忆双写违反"单一事实源"**（审计 P1-18）：`engine_xai.py:354` 移除 `MemoryAdapter` 写入，仅 `_safe_memory_core_write` 写 `memory_core`。
- **接入 Project 隔离**：`_retrieve_memory_context` 取 `project_manager.current().id` 传给 `memory_core.recall(project_id=pid)`；`_safe_memory_core_write` 在 meta 注入 `project_id`。

#### 模型切换

- **修复模型切换对推理零效果**（审计 P0-16）：`server_xai.py:113` 激活后调 `get_engine()._rebuild_backend()`；`engine_xai.py:214-231` 新增 `_rebuild_backend()`，根据 `model_registry.active()` 动态构造 `DeepSeekBackend(api_key, model, base_url)` + 重建 HermesAdapter。
- **修复故障轮换**：`engine_xai.py:180-204` 新增 `_infer_with_fallback()`，失败时 `fb._find_next()` → `model_registry.activate(next_model.id)` → `_rebuild_backend()` → 重试。
- **`_execute_general` 接入 fallback**：流式失败时 `yield {"type":"reset", "reason":"fallback"}` → 切换模型 → 重新流式。

#### 前端

- **修复 slash 命令"暂未收到回复"误报**（审计 P1-23）：`app.js:1354` 加 `return result;`，让 `handleSSEEvent` 包装器不吞原函数返回值。
- **修复 Loop Safety UI 修改无效**（审计 P2-24）：`server_xai.py:425-428` 兼容 `{key, value}` 格式：`kwargs[data["key"]] = int(data["value"])`。
- **群聊 Tab 接线**（审计 P1-25）：`app.js:1240-1265` 新增 `roomLoadAgents()`（调 `/api/agents`）+ `roomSend()`（调 `/api/coordination/chat`）；`data-view="room"` 点击触发加载。
- **拓扑 Tab 部分修复**（审计 P2-26）：`app.js:1326-1349` `topoFromIntent` 加英文 intent 匹配（`code_dev/browser/memory/general/research`）+ 中文命令匹配（`/scan <file>`）。
- **拓扑 Tab 箭头修复**：`index.html:155` `<svg id="topo-edges">` 加 `<defs><marker id="arrow">`，连线显示箭头。

#### 安全

- **修复 `/api/save` 路径穿越漏洞**（审计 P1-32）：`server_xai.py:326` 改为 `ext = "".join(c for c in (data.get("ext") or "md") if c.isalnum() or c == ".")[:12] or "md"`，拒绝 `a/../../../escape` 等模式。
- **OpenClaw `_exec_command` 改用 `shlex.split`**（`openclaw_adapter.py:135-137`）：消除 `shell=True` 命令注入气味。

#### 编译与文档

- **生成 `AUDIT_REPORT.md`**：17:52 完成的全量静态代码审查 + 动态实证，列 41 项问题。
- **生成 `PROJECT_OVERVIEW.md`**（本文档）：18:30+ 完成的综合项目文档，含蓝图对账 + 模块清单 + API + 部署 + Changelog。

#### 未修复但仍记录的审计项

- 审计 P1-3 联网搜索 URL 永远为空 — **未修复**。
- 审计 P1-4 意图分类双轨制 — **未修复**。
- 审计 P1-5 双引擎 + 双服务端 + 三前端重复 — **未修复**（弃用代码未删）。
- 审计 P1-9 MemoryAdapter 无线程锁 — **未修复**。
- 审计 P1-10 HermesAdapter system 消息被丢弃 — **未修复**。
- 审计 P1-31 XAI.app 双击落 Stub — **未修复**。
- 审计 P2-7 `_cmd_approve` 硬编码 session — **实际已修复**（`engine_xai.py:927` `sid = rec.get("session") or "default"`），审计描述滞后。
- 审计 P2-8 `/api/chat/send` 非流式丢 token — **未修复**（见 Known Issues #1）。
- 审计 P2-28 `to-canvas-btn` 跳转失效 — **未修复**。

#### 架构层完成度变化

- 修复前：4 ✅ + 7 ⚠️ + 3 ❌ ≈ 50%
- 修复后：4 ✅ + 7 ⚠️ + 2 ❌ ≈ 55%
- 主要变化：ProviderFallback 功能可用（但 `infer()` 仍零调用，标记未变）；记忆双写消除（但 MemoryAdapter 仍存在，标记未变）。

#### 2026-07-22 / 24 · 全量落地（多 Agent 协同评审）

> 决策 A0=a：**V4 `frontend/` 定为官方产品控制台**，`xai-frontend/` 降为 legacy。以下为落地实质变更。

**后端契约缺口补齐（B1/B2/B3/B5）**
- 新增 `server_routes_system.py`，注册 `GET /api/system/health`（豁免鉴权）、`/api/system/sandbox`、`/api/system/errors`、`/api/system/status`（别名）。`server_xai.py` 在 register 链中 `_reg_system(_ROUTER)` 接入。
- 4 条路由经 `:8000` 实服务验证全 200。

**Bug 修复（B4）**
- `core/kb.py::_bm25_scores`：空查询原返回 `[]` 导致 fused 循环 `nb[i]` 越界 `IndexError`；改为返回与 `self.chunks` 等长的零向量。`/api/knowledge/search` 空查询现返回 `{ok:true, hits:[]}`。

**前端路由切换（A0）**
- `server_xai.py` 的 `WEB_DIR` 由 `xai-frontend/dist-web` 切到 `frontend/dist`；生产服务 `:8000` 直接托管 V4，重启 PID 36097 验证 `index.html 200` + 含 "XAI Station v4"。

**前端 3D 特效（C 档，commit 02cd134）**
- 新增 `effects.css`（共享 3D 层，遵循 `prefers-reduced-motion`），抽取 `TeamWidget.tsx` / `StatusWidget.tsx`，三栏叠加 OllamaFLOW 风格 3D 倾斜；Puppeteer 实测 hover `matrix3d(...)` 真实生效，首屏 11 处 + 会话历史 83 处，零页面错误。

**12 页功能走查（F2，全绿）**
- 对 `:8000` 实服务逐端点 curl（带 `X-Auth-Token`），覆盖 12 个 V4 页面的 15 个后端契约，全 200，无 404/500。空响应（workflow/history、guardian/pending、gepa/status）均为"新系统暂无数据"预期，非缺陷。ChatConsole 经 `POST /api/chat` SSE 实流验证 start→intent→guard→progress。

**仓库卫生（C4）**
- `.gitignore` 增补 `verification_*.md` 与 `xai-backend/data/orchestrations.json`。

**遗留（未做，待评审）**
- B6（**已落地 2026-07-24**）：逐条比对（method×path）后，删除 `server_xai.py` 内联 `elif` 死代码分支 **51 个**（均为 dispatch 先拦截、已有等价注册副本者），净减 104 行；14 个 only-handler 分支（如 `/api/status`、`/api/agents`、`/api/memory/*`）保留。`py_compile` 通过，F2 全 15 端点 + 4 系统路由复测**全 200，0 失败**。
- C3：子模块指针漂移（`vendor/OllamaFlow`、`xai-frontend`、`vendor/MemOS` 无 `.gitmodules` 映射），建议保留（保 legacy 代码）不删。
- X 系列：`xai-frontend/` 5 个 PlaceholderPage 空壳，已降为 legacy，未清理。

---

## 附录：快速验证清单

```bash
# 1. 单元测试（73 项，无需联网）
cd /Users/Admin/Desktop/mask/xai
python3 -m pytest tests/ -q

# 2. 端到端自测（需服务在 8000）
python3 server_xai.py &
python3 tests/selftest_e2e.py         # 13 项核心流程
python3 tests/selftest_e2e_round2.py  # 13 项命令全量 + 边界 + 并发

# 3. 手动冒烟
curl http://localhost:8000/api/status | python3 -m json.tool
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"text":"/help","session":"test"}'
```

## 附录：相关文档索引

| 文档 | 用途 |
|---|---|
| `~/.workbuddy/memory/MEMORY.md` | 架构宪法（Dual-Kernel Fusion） |
| `AUDIT_REPORT.md` | 2026-07-18 17:52 审计快照（41 项问题） |
| `README.md` | 项目说明 + 启动方法 |
| `tests/QA_REPORT.md` | 多轮端到端自测报告（26/26 通过） |
| `COMPARISON_REPORT.md` | 对标成熟开源项目差距分析 |
| `XAI_VENDOR_BENCHMARK_REPORT.md` | vendor/ 5 项目基准对比 |
| `调研报告_架构对标.md` | 7 个 GitHub 明星项目对标 |
| `xai-platform-architecture.md` | v2 重构架构总纲（已废弃，以宪法为准） |
| `xai-unified-architecture.md` | 统一调度台+画布+流程协同（已废弃） |
| `xai-ultimate-blueprint-v2.md` | 总体蓝图 v2（已废弃） |
| `xai-fusion-ultimate-plan.md` | 融合终极计划（已废弃） |
| `xai-ux-collab-blueprint.md` | UX 协同蓝图 |
| `audit-report.md` | 早期审计（8 条 + 三冲突） |

---

*文档结束。任何后续改动若违背宪法，须先经用户签字。*