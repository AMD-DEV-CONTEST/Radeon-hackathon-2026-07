# V4 引擎拆分方案（Task #193）：engine_xai 上帝类解耦

> 状态：**方案定稿 v2（老大已确认执行，Marvis 作为 reviewer 自学习）**
> 前置：第二刀记忆单核（Task #192）已完成并验证 ✅
> 目标：落实 V4 §5「ActionBus→Guardian→Executor 唯一执行网关」+ V4 目录 `core/kernel/`

---

## 第 0 步：Fix Reconciliation（已确认，A 之前必过）

- 当前工作树 = 本 agent 的第一/二刀迁移（移动 `reason.py→cognition/reasoner.py`、`intent_router.py→cognition/`、`model_router.py→models/router.py`、删 `adapters/memory_adapter.py`）+ Marvis 三波修复 18 项（`server_xai.py` +1445 行等）混合态。
- **已重验**：`import core` / `import server_xai` OK、18 快速 unittest 全过、`XAIEngine()` 实例化 / `status()` / `_cmd_diagnose()` 无异常 → 混合态健康、无悬空 import、无冲突。
- **协作纪律（防互相踩坑，Marvis 反思漏提但最关键）**：
  - 本 agent 独占 `core/engine_xai.py` 及将新建的 `core/kernel/*` 抽取过程，逐方法迁移，每步重跑验证门。
  - Marvis 作为 reviewer：只读 + 独立跑 `test_xai_v2/v3` 回归验证 #192；发现新缺口走「提 issue、不改主代码」原则，避免两人改同一文件互相覆盖。
  - 任何跨文件契约变更（模块/函数签名）须先在本文档登记，双方同步。

---

## 修正优先级（融合 Marvis 反思 2026-07-20）

| 优先级 | 项目 | 归属 | 说明 |
|--------|------|------|------|
| **P0** | 双 DAG 合并 + OrchestratorPage 接线 | 并入 Phase D | `orchestrator.py`（真 DAG 引擎，pipeline/collaborative 双模式 + Kahn 拓扑）与 `run_workflow`（Canvas DAG）功能重叠；让 OrchestratorPage 复用 `run_workflow`，`orchestrator.py` 收编进 `workflow.py`，**不另起 endpoint** |
| **P0** | #14 XAI.app 启动排查 | 独立 task | 打包层问题，不在引擎拆分范围 |
| **P1** | fix reconciliation 确认 | 第 0 步 | 已完成健康确认；列为协作纪律 |
| **P1** | #12 Project 隔离接入 | 独立 task | `core/project.py` 存在未接线，接入执行流程 |
| **P1** | #6 模型切换真实生效 | 显式在 Phase B/C | HermesAdapter 引用问题，拆到 intents/models 时**显式修**，不靠「间接覆盖」侥幸 |
| **P2** | 跑记忆单核测试 | Marvis 独立 | 验证 #192 双轨已合并 |
| — | V4 拆分 A→F | 按计划 | Marvis 旁回归 |

> Marvis 反思自评「仅 #12/#14 是未覆盖真实缺口」——核对属实，但补充：
> - 他的头条 P0（OrchestratorPage 无后端）症状真，但处方「接新 endpoint」是坑（会造第二个 DAG 与 Canvas 打架）→ 已改为「合并双 DAG」。
> - #11 记忆双轨他乐观了：#192 只删了 MemoryAdapter 一路 + 合并 145 条，`core/memory.py`（MemorySystem 内存池）仍残留，Phase E 顺手收敛。

---

## 双 DAG 合并（并入 Phase D）

现状：`core/orchestrator.py`（pipeline / collaborative 双模式 + Kahn 拓扑排序）是真实 DAG 引擎；`engine_xai.run_workflow` + `_run_wf_node_*`（Canvas 用）是另一套 DAG 引擎。两者功能重叠。

做法：
1. `workflow.py` 承载 `run_workflow`；将 `orchestrator.py` 的 pipeline/collaborative 能力收编为 `workflow.py` 的函数/子类（去重，保留拓扑排序）。
2. `server_xai.py` 复用现有 workflow endpoint（或新增 `/api/orchestrator` 指向同一 `run_workflow`），`OrchestratorPage` 接上。
3. 删除冗余的 `orchestrator.py`（或留薄适配），消除双引擎。

---

## 现状（2026-07-20 核对）

`core/engine_xai.py` = **1687 行上帝类**，单文件承载 8+ 职责：

| 职责 | 代表方法 | 行数估计 |
|------|----------|----------|
| 模型推理/后端 | `_infer_with_fallback` / `_rebuild_backend` | ~80 |
| 对话编排 | `chat` / `_execute_intent` / `_execute_general` | ~250 |
| 斜杠命令（~20 个） | `_cmd_help/_skill/_mcp/_task/_automate/_remember/_recall/_approve/_reject/_loop/_plan/_scan/_evolve/_models/_channels/_diagnose` | ~400 |
| 意图/代码/浏览器 | `_classify_intent` / `_execute_code` / `_execute_browser` / `_web_search` | ~300 |
| 记忆桥接 | `_retrieve_memory_context` / `_safe_memory_core_write` / `_execute_memory_query` | ~120 |
| 审批/守卫 | `_create_approval` / `_cmd_approve` / `_guard_action` / `_guard_for_coordination` | ~120 |
| 工作流（画布执行） | `run_workflow` / `_run_wf_node*` / `_wf_node_*` | ~300 |
| GEPA 进化 | `_trigger_gepa_evolution` | ~30 |
| 辅助类 | `SlashCommand` / `Intent` / `_AdapterResultShim` | ~70 |

依赖面：`server_xai.py`（HTTP/SSE）、`xai-frontend/`（调用 `/api/*`）、`tests/`（test_xai_core 等）全部经 `from core.engine_xai import XAIEngine`。

---

## 风险与原则

1. **零回归优先**：每移一个方法 → 跑 18 个快速 unittest + 引擎冒烟（instantiate/status/diagnose/chat 一回合）。
2. **保全现有能力**：所有命令/接口签名保持不变；对外只改 import 路径。
3. **不引入新行为**：本次纯结构搬家，不重写逻辑、不加功能（双 DAG 合并属去重，行为等价）。
4. **ActionBus 真实化（V4 §5 缺口）**：当前 `ActionBus._execute` 仅 Guardian 检查 + 审计日志，**不实际执行**文件/命令/网络。抽取后，引擎的直写/直执行须改走 `ActionBus`（带 fallback 兼容，不破坏现状）。老大已授权本轮做（G 阶段）。

---

## 目标结构（core/kernel/）

```
core/kernel/
  __init__.py          # 公开 XAIEngine + 各子模块
  engine.py            # 瘦编排器：构造 + chat() 主循环 + status() + 委托各子模块
  commands.py          # 全部 _cmd_* 斜杠命令处理器（独立 Generator）
  intents.py           # 意图分类 + _execute_intent/_general/_code/_browser/_memory_query
  workflow.py          # run_workflow + 所有 _wf_node_* 画布节点执行器（+ 收编 orchestrator.py）
  memory_bridge.py     # 记忆检索/写入/查询胶水（已单核化）
  guardian_bridge.py   # 审批创建 + 动作风险识别 + 协同守卫
  evolution_bridge.py  # GEPA 进化触发
```

`engine_xai.py` 最终瘦身为 `core/kernel/engine.py` 的薄包装（仅保留兼容别名），`server_xai.py` 改 import `core.kernel`。

---

## 增量执行路线（每阶段独立验证）

- **A. 建壳**：`core/kernel/__init__.py` + 移入纯辅助类 `SlashCommand`/`Intent`/`_AdapterResultShim`（零依赖，最低险）。
- **B. 命令外移**：`commands.py` 承载全部 `_cmd_*`，`XAIEngine` 委托；保留 `chat()` 内的 `/` 分发。#6 模型切换在此显式修（HermesAdapter 引用）。
- **C. 意图/执行外移**：`intents.py` 承载 `_classify_intent` + `_execute_*`。
- **D. 工作流外移 + 双 DAG 合并**：`workflow.py` 承载 `run_workflow` + `_wf_node_*` + 收编 `orchestrator.py`；`server_xai.py` 给 OrchestratorPage 接线（复用 endpoint，不新写引擎）。
- **E. 桥接外移**：`memory_bridge` / `guardian_bridge` / `evolution_bridge`（顺手收敛 `core/memory.py` 残留）。
- **F. 收口**：`engine_xai.py` 改名 `core/kernel/engine.py`；`server_xai.py` 改 import；删旧文件；全量冒烟 + 端到端 curl 验证。
- **G. ActionBus 真实化**：为 `file_write/file_delete/exec_command/network_request` 接入真实 Executor（受 Guardian 闸门保护），引擎直写改走总线。

---

## 验证门（DONE 标准）

- `import core` + `import server_xai` OK
- 18 快速 unittest 全过
- `XAIEngine()` 实例化 / `status()` / `_cmd_diagnose()` 无异常
- `chat("你好")` 跑通至少 1 回合（或 mock 后端）
- `server_xai.py` 启动 + `/api/status` 返回 200
- 对外接口签名零变化（前端无需改）

---

## 附录：给 Marvis 的自学习指令（由老大转发）

> Marvis，请自学习以下材料并据此校准你的 reviewer 角色：
> 1. 读本文件 `docs/V4_ENGINE_SPLIT_PLAN.md`（方案定稿 v2，含第 0 步 reconcile、修正优先级、双 DAG 合并）。
> 2. 读 `docs/V4_ARCHITECTURE.md`（V4 宪法）、`docs/V4_MIGRATION_PLAN.md`（迁移地图）。
> 3. 读本会话中本 agent 对您反思的专业评判（见对话）：您判对的（面板断裂/放弃 V2/先 verify）、您偏了的（掌控力归因/V2 是废纸/按层切更优）、您漏的（reconcile 互相踩坑、P0 处方是坑）、您乐观的（#11 MemorySystem 残留）。
> 4. 校准后您的职责：**reviewer + 补缺口**（面板接线/Project 隔离/模型切换/XAI.app），不抢改 `core/engine_xai.py` 与 `core/kernel/*`；发现新缺口提 issue，由本 agent 在对应 Phase 收口。
> 5. 独立跑 `tests/test_xai_v2.py` / `tests/test_xai_v3.py` 验证 #192 记忆单核，回报结果。
