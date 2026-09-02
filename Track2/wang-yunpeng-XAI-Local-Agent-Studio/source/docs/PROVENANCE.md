# PROVENANCE.md — 后端逻辑溯源与参考

> 基于真实代码 file:line 整理。状态：REAL 已实现 / PARTIAL 部分实现 / STUB 占位。

## 一、七大模块

**1. 对话** `/api/chat` → `server_xai.py:252,322` → `engine_xai.py:283 chat`；Hermes 推理 `engine_xai.py:162`。
参考：通用 LLM 对话（Hermes≈本地 OpenHermes 桥）。状态：**REAL**（SSE 流式 + 记忆注入 + 故障轮换 `engine_xai.py:200`）。缺口：模型质量依赖外部 DeepSeek，Stub 下为回显。

**2. 任务** `/api/tasks` → `app_store.py:17 tasks表`, `179 tasks_list/create/update/delete`。
参考：轻量任务表（对标 Todoist 数据模型）。状态：**PARTIAL**（CRUD 完备，但仅持久化，无执行/派发逻辑）。缺口：任务→引擎执行的链路缺失。

**3. 专家团** `/api/teams` → `app_store.py:28 teams表` CRUD。真实多智能体在 `coordination.py:57 CoordinationBus`（`engine_xai.py:169` 注册），但 **未与 `/api/teams` 接线**。
参考：AutoGen/CrewAI 多 Agent。状态：**PARTIAL**（团队=纯存储；群聊=内存总线，重启即丢）。缺口：teams 表与 CoordinationBus 未打通，无持久 Agent 编排。

**4. 自动化** `/api/automations` → `app_store.py:35`, 调度 `server_xai.py:75 _start_scheduler`, `_execute_prompt:63`。
参考：Coze 触发器 / WorkBuddy 自动化。状态：**PARTIAL**（定时型真实触发；事件/webhook 型 `server_xai.py:118` 标注但未实现）。

**5. 定时任务** `/api/schedules` → `app_store.py:43`, cron `cronutil.py:51 next_run`, 轮询线程 `server_xai.py:107`。
参考：APScheduler / cron。状态：**REAL**（标准 5 段 cron、OR 语义、时区、运行历史）。缺口：30s 轮询非精准触发；无持久后台进程管理。

**6. 画布** `/api/workflow/run` → `engine_xai.py:1227 run_workflow`，节点 `1295 _run_wf_node`。
参考：LangGraph/n8n DAG。状态：**REAL**（Kahn 拓扑+环检测 `1253`、scan/exec 真调 OpenClaw `1302-1320`、其余走推理）。缺口：P0 节点未接审批队列（`1314` 仅硬编码拦截）。

**7. 管理** `/api/status` `engine_xai.py:255`；`/api/loop-safety` `loop_safety.py:167` + `server_xai.py:225`；`/api/memory` `server_xai.py:186`（SQLite `memory_core.py:71`）。
参考：loop-safety≈Orbital，Guardian≈policy-as-code/OPA，Memory≈MemOS。状态：**REAL**（五重闸门 `loop_safety.py:109`、P0/P1/P2 分级 `guardian.py:42`、7 层记忆 `memory_core.py:106`）。缺口：语义检索为词袋 `memory.py:_embed`，非向量。

## 二、六项升级能力

| 能力 | 后端支持 | 应借鉴 | 缺口 |
|---|---|---|---|
| 实时事件总线 SSE | PARTIAL（chat/workflow 已 SSE，`server_xai.py:673/357`） | SSE/WebSocket | 后台任务/调度无推送，需统一事件总线 |
| 能力注册表驱动 UI | PARTIAL（`model_registry` `engine_xai.py:142`） | 插件注册表 | 无 capability registry 供 UI 动态渲染 |
| 后端意图置信度 | PARTIAL（`IntentRouter` `intent_router.py:78`，`engine_xai.py:331` 回报） | semantic-router | 关键词启发式，无向量语义；低置信兜底弱 |
| 画布闭环+Guardian | PARTIAL（`guardian.py` 存在） | policy-as-code | 节点 P0 未入审批队列，无 Human 确认闭环 |
| 计划持久化 | STUB（`cognition/planner.py` 未存/无 API） | Plan-and-Execute | 缺 `/api/plan` 与落库 |
| 认知环实时视图 | STUB（`control_loop.py`+`cognition/`） | 可观测性面板 | 无逐步流式认知事件 |

## 三、结论

**可直接用（REAL）**：对话、定时任务、画布 DAG 执行、管理面（status/loop-safety/memory/Guardian 分级）。

**需补 GitHub 验证实现**：
- 任务执行链路、专家团↔CoordinationBus 打通、自动化事件触发；
- 统一事件总线、能力注册表、语义意图路由、画布 P0 审批闭环、计划持久化、认知环实时流。
建议以 n8n/LangGraph（DAG）、CrewAI（多 Agent）、semantic-router（意图）、MemOS（记忆）、OPA（策略）为基准对齐实现。
