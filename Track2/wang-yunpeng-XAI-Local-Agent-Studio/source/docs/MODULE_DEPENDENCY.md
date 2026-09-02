# XAI Kernel V4 模块依赖分析

**生成日期**: 2026-07-18  
**分析方法**: `grep -rn "^from \." core/` 实证导入链 + PROJECT_OVERVIEW.md 组件状态校验  

---

## 依赖总览图

```
                          ┌──────────────────────────────────────────┐
                          │         server_xai.py (外部入口)          │
                          └──────────────────┬───────────────────────┘
                                             │ from core.engine_xai import XAIEngine
                          ┌──────────────────▼───────────────────────┐
                          │           engine_xai.py (编排引擎)        │
                          │  核心依赖: 18 个模块                      │
                          └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┘
                             │  │  │  │  │  │  │  │  │  │  │  │  │
        ┌────────────────────┘  │  │  │  │  │  │  │  │  │  │  │  │
        ▼                       ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼  ▼
   ┌──────────┐           ┌─────────────────────────────────────────────┐
   │ adapters │           │         认知 / 执行 / 记忆 / 治理 层          │
   │ · base   │           └─────────────────────────────────────────────┘
   │ · hermes │                              │
   │ · openclaw│             ┌───────────────┼───────────────┐
   │ · memory │              ▼               ▼               ▼
   └──────────┘       ┌──────────┐    ┌──────────┐    ┌───────────┐
                      │ guardian │◄───│  meta    │    │  reason   │
                      └──────────┘    └──────────┘    └─────┬─────┘
                           ▲              ▲                 │
                           │              │                 ▼
                      ┌──────────┐  ┌───────────┐    ┌──────────┐
                      │ control  │  │ workflow  │    │  model   │
                      │  _loop   │  │  _bridge  │    │ _backend │
                      └────┬─────┘  └───────────┘    └──────────┘
                           │
                           ▼
                      ┌──────────┐
                      │memory_core│ ← coordination.py / substrate.py / engine.py
                      └──────────┘
                           ▲
                ┌──────────┼──────────┐
                │          │          │
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ session  │ │ project  │ │  model   │
        │ _store   │ │          │ │ registry │
        └──────────┘ └──────────┘ └────┬─────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │  provider    │
                                │  _fallback   │
                                └──────────────┘
```

---

## 模块依赖详细清单

### 编排引擎层 (Orchestration)

#### `core/engine_xai.py` (1,272 行) — ⚡ 执行链中枢

| 维度 | 详情 |
|------|------|
| **导入** | adapter.base, adapter.openclaw_adapter, adapter.hermes_adapter, adapter.memory_adapter, guardian, model_backend, deepseek_backend, session_store, memory_core, intent_router, grok_build_engine, coordination, control_loop, model_registry, provider_fallback, loop_safety, project |
| **被导入** | server_xai.py (唯一运行时调用者) |
| **链角色** | 执行链编排 — 所有任务入口 |
| **V4 目标** | 拆分到 `kernel/engine.py` + `kernel/lifecycle.py` |

#### `core/engine.py` (252 行) — ❌ 弃用

| 维度 | 详情 |
|------|------|
| **导入** | memory_core, substrate, coordination, guardian, intent_router, control_loop, model_backend, deepseek_backend |
| **被导入** | test_platform.py |
| **链角色** | 旧执行链 — V4 不保留 |
| **V4 目标** | DELETE (合并到 kernel/engine.py) |

---

### 认知层 (Cognition)

#### `core/intent_router.py` (150 行) — ⚠️ 部分活跃

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 纯标准库: dataclasses, enum, re, typing) |
| **被导入** | engine_xai.py, engine.py, workflow_bridge.py, __init__.py |
| **链角色** | 执行链第 1 步: 5 类意图分类 + 评分 |
| **已知缺陷** | `routing` 字段 (openclaw_gateway/grok_build_engine/orchestrator/kb/reason) 零消费者 |
| **V4 目标** | MIGRATE → `cognition/intent_router.py` |

#### `core/reason.py` (97 行) — ⚠️ 仅经 ControlLoop

| 维度 | 详情 |
|------|------|
| **导入** | model_backend (ModelBackend, ModelResponse) |
| **被导入** | control_loop.py, __init__.py |
| **链角色** | ControlLoop 内思考增强: thinking_protocol / self_refine / multi_trajectory |
| **V4 目标** | MIGRATE → `cognition/reasoner.py` |

#### `core/meta.py` (120 行) — ⚠️ 仅经 ControlLoop

| 维度 | 详情 |
|------|------|
| **导入** | guardian (Action, approve) |
| **被导入** | control_loop.py, workflow_bridge.py, __init__.py |
| **链角色** | 元认知校准: BrierCalibrator + L8Auditor 四维审计 |
| **V4 目标** | REFACTOR → 并入 `cognition/verifier.py` |

#### `core/control_loop.py` (119 行) — ⚠️ 仅 /loop 入口

| 维度 | 详情 |
|------|------|
| **导入** | guardian, meta, model_backend, reason |
| **被导入** | engine_xai.py, engine.py, __init__.py |
| **链角色** | 6 步认知循环: meta外环 → reason → meta.reflect → guardian → execute → meta.observe |
| **V4 目标** | MIGRATE → 并入 `kernel/lifecycle.py` |

---

### 治理层 (Governance)

#### `core/guardian.py` (229 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 纯标准库: dataclasses, enum) |
| **被导入** | engine_xai.py, engine.py, workflow_bridge.py, control_loop.py, meta.py, __init__.py |
| **链角色** | 执行链第 4 步: P0/P1/P2 风险分级 + 审批队列 |
| **V4 目标** | REFACTOR → `governance/guardian.py` + `governance/approval.py` |

#### `core/loop_safety.py` (191 行) — ⚠️ 2/5 调用

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 纯标准库: dataclasses, json, os, time) |
| **被导入** | engine_xai.py |
| **链角色** | 5 重安全闸门: Token预算/重复检测/乒乓球/断路器/上下文溢出 |
| **已知缺陷** | 仅 reset/check 2 闸门调用, record_error/record_result/check_context 零调用 |
| **V4 目标** | REFACTOR → 并入 `governance/guardian.py` |

---

### 执行层 (Execution)

#### `core/substrate.py` (254 行) — ❌ 仅旧 engine

| 维度 | 详情 |
|------|------|
| **导入** | memory_core (MemoryCore, Layer, default_core) |
| **被导入** | engine.py, __init__.py |
| **链角色** | 旧执行底座: SubstratePort + LocalSubstrate |
| **V4 目标** | REFACTOR → `execution/executor.py` + `execution/tools.py` + `evolution/evaluator.py` |

#### `core/runner.py` (94 行) — ❌ 零调用方

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 纯标准库: dataclasses, typing) |
| **被导入** | __init__.py (仅导出, 无运行时调用) |
| **链角色** | 长任务执行: 分步 + checkpoint + 质量门 + 续跑 |
| **V4 目标** | REFACTOR → 并入 `execution/executor.py` |

#### `core/grok_build_engine.py` (378 行) — ⚠️ 条件可用

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 标准库: os, json, subprocess, shutil, dataclasses, threading) |
| **被导入** | engine_xai.py, __init__.py |
| **链角色** | 代码工程: GrokBuildBridge 子进程 + CodeEngine 工具 |
| **V4 目标** | REFACTOR → `agents/grok_agent.py` + `execution/tools.py` |

#### `core/openclaw_gateway.py` (233 行) — ❌ 弃用

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖) |
| **被导入** | __init__.py (仅导出, 无运行时调用) |
| **链角色** | 旧网关抽象: Gateway + StubAdapter |
| **V4 目标** | REFACTOR → 并入 `execution/tools.py` |

#### `core/kb.py` (112 行) — ❌ 仅旧测试

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖) |
| **被导入** | workflow_bridge.py |
| **链角色** | 本地知识库 RAG 桩 |
| **V4 目标** | REFACTOR → 并入 `execution/tools.py` |

#### `core/workflow_bridge.py` (211 行) — ⚠️ 仅旧 engine

| 维度 | 详情 |
|------|------|
| **导入** | model_backend, kb, model_router, guardian, meta, intent_router, memory (旧 MemorySystem) |
| **被导入** | __init__.py, engine.py |
| **链角色** | 画布 DAG 桥接: execute_workflow + topo_order |
| **V4 目标** | REFACTOR → 并入 `kernel/lifecycle.py` |

---

### 记忆层 (Memory)

#### `core/memory_core.py` (246 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 纯标准库: sqlite3, dataclasses, enum, json, os, time, pathlib, threading) |
| **被导入** | engine_xai.py, engine.py, coordination.py, substrate.py, __init__.py |
| **链角色** | 执行链第 8 步: 8 层记忆内核 (单一事实源) |
| **V4 目标** | KEEP → `memory/memory_core.py`, 拆出 `retrieval.py` + `consolidation.py` |

#### `core/memory.py` (159 行) — ❌ 须删除

| 维度 | 详情 |
|------|------|
| **导入** | (标准库: json, os, deque) |
| **被导入** | workflow_bridge.py, __init__.py |
| **链角色** | 旧 MemorySystem (deque + Markdown) — V4 禁止 |
| **V4 目标** | DELETE (V4 §原则二: 删除双轨) |

#### `core/adapters/memory_adapter.py` (327 行) — ⚠️ 半活跃

| 维度 | 详情 |
|------|------|
| **导入** | adapter.base (Adapter, AdapterResult) |
| **被导入** | engine_xai.py (仅 /remember /recall 用) |
| **链角色** | MemOS 兼容适配器 — 独立的 `memos.db` 双轨 |
| **V4 目标** | DELETE (V4 §原则二: 删除 MemoryAdapter) |

---

### 智能体层 (Agents)

#### `core/adapters/base.py` (48 行) — ❌ 须删除

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 标准库: abc, dataclasses, typing) |
| **被导入** | hermes_adapter.py, openclaw_adapter.py, memory_adapter.py, adapters/__init__.py |
| **链角色** | Adapter 抽象基类 — V4 不使用 Adapter 模式 |
| **V4 目标** | DELETE |

#### `core/adapters/hermes_adapter.py` (331 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | adapter.base (Adapter, AdapterResult) |
| **被导入** | engine_xai.py, adapters/__init__.py |
| **链角色** | Hermes 通用推理 + GEPA 自进化 |
| **V4 目标** | REFACTOR → `agents/hermes_agent.py` |

#### `core/adapters/openclaw_adapter.py` (513 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | adapter.base (Adapter, AdapterResult) |
| **被导入** | engine_xai.py, adapters/__init__.py |
| **链角色** | 事实执行网关: 6 个本地工具 + OpenClaw CLI 桥接 |
| **V4 目标** | REFACTOR → 并入 `execution/tools.py` |

#### `core/coordination.py` (184 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | memory_core (MemoryCore, Layer, default_core) |
| **被导入** | engine_xai.py, engine.py |
| **链角色** | 多 Agent 协同总线: publish/subscribe/room/Agent |
| **V4 目标** | REFACTOR → `kernel/event_bus.py` + Agent Registry |

---

### 模型层 (Models)

#### `core/model_backend.py` (76 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (无内部依赖 — 标准库: abc, dataclasses, typing) |
| **被导入** | deepseek_backend.py, reason.py, distill.py, workflow_bridge.py, engine.py, engine_xai.py, __init__.py |
| **链角色** | 工具 — 模型后端抽象基类 (ModelBackend/StubBackend) |
| **V4 目标** | REFACTOR → 并入 `models/cloud.py` |

#### `core/deepseek_backend.py` (158 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | model_backend (ModelBackend, ModelResponse) |
| **被导入** | engine.py, engine_xai.py, __init__.py |
| **链角色** | 工具 — DeepSeek OpenAI 兼容后端 |
| **V4 目标** | REFACTOR → 并入 `models/cloud.py` |

#### `core/model_registry.py` (157 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (标准库: json, os, time, uuid, dataclasses, typing) |
| **被导入** | engine_xai.py, provider_fallback.py |
| **链角色** | 工具 — 多模型 CRUD + 激活 |
| **V4 目标** | REFACTOR → 并入 `models/router.py` |

#### `core/model_router.py` (77 行) — ❌ 弃用

| 维度 | 详情 |
|------|------|
| **导入** | (标准库: dataclasses, typing, random) |
| **被导入** | workflow_bridge.py, __init__.py |
| **链角色** | 工具 — 节点级多模型路由 (仅旧 workflow_bridge 用) |
| **V4 目标** | MIGRATE → `models/router.py` |

#### `core/provider_fallback.py` (154 行) — ❌ .infer() 零调用

| 维度 | 详情 |
|------|------|
| **导入** | model_registry (ModelEntry, default_registry) |
| **被导入** | engine_xai.py |
| **链角色** | 工具 — ProviderFallback.infer() 设计完整但运行时零调用 |
| **V4 目标** | REFACTOR → 并入 `models/router.py` |

---

### 进化层 (Evolution)

#### `core/distill.py` (121 行) — ⚠️ 仅 hermes.darwinian_evolve

| 维度 | 详情 |
|------|------|
| **导入** | model_backend (ModelBackend) |
| **被导入** | __init__.py |
| **链角色** | 技能蒸馏 + GEPA 进化: Distiller / GepaEvolver |
| **V4 目标** | REFACTOR → `evolution/distiller.py` + `evolution/skill_builder.py` |

#### `core/skills.py` (128 行) — ❌ 弃用

| 维度 | 详情 |
|------|------|
| **导入** | (标准库) |
| **被导入** | __init__.py |
| **链角色** | 旧技能注册 (SkillRegistry) — 无运行时调用 |
| **V4 目标** | REFACTOR → 并入 `evolution/skill_builder.py` |

#### `core/orchestrator.py` (80 行) — ❌ 弃用

| 维度 | 详情 |
|------|------|
| **导入** | (标准库) |
| **被导入** | __init__.py |
| **链角色** | 旧多 Agent DAG 编排 |
| **V4 目标** | REFACTOR → 并入 `cognition/planner.py` |

---

### 工具层 (Utilities)

#### `core/session_store.py` (124 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (标准库: sqlite3, json, time, os) |
| **被导入** | engine_xai.py |
| **链角色** | 工具 — SQLite 会话历史 |
| **V4 目标** | REFACTOR → 并入 `kernel/lifecycle.py` |

#### `core/project.py` (164 行) — ✅ 活跃

| 维度 | 详情 |
|------|------|
| **导入** | (标准库: sqlite3, os, time, uuid, dataclasses, typing) |
| **被导入** | engine_xai.py |
| **链角色** | 工具 — Project 管理 (SQLite `projects.db`) |
| **V4 目标** | REFACTOR → 并入 `memory/memory_core.py` |

---

## 执行链 vs 工具模块

### 执行链模块 (V4 保留并增强)

```
IntentRouter → Planner[NEW] → ControlLoop → Guardian → ActionBus[NEW] → Executor → Verifier[NEW] → MemoryCore → Evolution
```

| 步骤 | 模块 | 状态 |
|------|------|------|
| 1 | IntentRouter (`intent_router.py`) | ⚠️ routing 字段未消费 |
| 2 | Planner | ❌ 不存在 (P0 新增) |
| 3 | ControlLoop (`control_loop.py`) | ⚠️ 仅 /loop 入口 |
| 4 | Guardian (`guardian.py`) | ✅ P0/P1/P2 生效 |
| 5 | ActionBus | ❌ 不存在 (P0 新增) |
| 6 | Executor (`openclaw_adapter.py`) | ✅ 6 工具 + CLI 桥接 |
| 7 | Verifier | ❌ 不存在 (P0 新增) |
| 8 | MemoryCore (`memory_core.py`) | ✅ 8 层 SQLite |
| 9 | Evolution (`distill.py` + `skills.py`) | ⚠️ 未形成闭环 |

### 工具模块 (V4 保留或合并)

| 模块 | 链角色 | V4 目标 |
|------|--------|---------|
| model_backend + deepseek_backend | 模型客户端 | → `models/cloud.py` |
| model_registry + model_router + provider_fallback | 模型管理 | → `models/router.py` |
| loop_safety | 安全闸门 | → `governance/guardian.py` |
| session_store | 会话持久化 | → `kernel/lifecycle.py` |
| project | 项目隔离 | → `memory/memory_core.py` |
| coordination | Agent 协同 | → `kernel/event_bus.py` |

### 须删除的模块 (V4 禁止)

| 模块 | 删除原因 |
|------|----------|
| memory.py | 旧 MemorySystem 双轨 — V4 §原则二 |
| adapters/memory_adapter.py | MemOS 独立 memos.db 双轨 — V4 §原则二 |
| adapters/base.py | Adapter 模式 — V4 不使用 |
| adapters/__init__.py | adapters/ 目录整体删除 |
| engine.py | 旧编排引擎 — 与 engine_xai.py 合并 |
| substrate.py | 旧执行底座 — 拆入 execution/ |
| workflow_bridge.py | 旧画布桥接 — 并入 lifecycle |
| openclaw_gateway.py | 旧网关抽象 — 替换为 ActionBus |

---

## 依赖统计

| 模块 | 直接依赖数 | 被依赖数 | 风险 |
|------|-----------|----------|------|
| engine_xai.py | 18 | 1 (server_xai.py) | HIGH |
| engine.py | 8 | 1 (test_platform.py) | LOW |
| __init__.py | 21 | 所有外部 import | MED |
| memory_core.py | 0 | 4 | LOW |
| model_backend.py | 0 | 8 | MED |
| guardian.py | 0 | 6 | LOW |
| intent_router.py | 0 | 4 | LOW |
| model_registry.py | 0 | 2 | LOW |
| control_loop.py | 4 | 3 | LOW |
| meta.py | 1 | 2 | LOW |
| reason.py | 1 | 1 | LOW |
| memory.py | 0 | 1 | LOW (DELETE) |
| runner.py | 0 | 0 | N/A (零调用方) |
| kb.py | 0 | 1 | LOW |
| orchestrator.py | 0 | 0 | N/A (弃用) |
| 其余 | 0-2 | 1-2 | LOW |

---

*依赖数据于 2026-07-18 通过 `grep -rn "^from \." core/` 实证扫描获取，排除 .bak 文件和标准库 import。*
