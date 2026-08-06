# XAI Kernel V3 → V4 迁移地图

**基准版本**: v3.0-final (tagged 2026-07-18)  
**目标版本**: V4.0 Architecture Consolidation  
**总文件数**: 37 个源文件, ~9,945 行代码 (含 web)  

---

## 迁移总览

| 迁移类型 | 文件数 | 代码行数 | 说明 |
|----------|--------|----------|------|
| KEEP | 4 | 2,759 | 已符合 V4 设计, 仅移动或微调 API 路径 |
| MIGRATE | 4 | 443 | 仅移动/改名, 不修改代码逻辑 |
| REFACTOR | 23 | 5,396 | 需要拆分/合并/重写 |
| DELETE | 4 | 552 | V4 明确要求删除的双轨代码 |
| NEW | 10 | ~1,500 | V4 新增模块 (Planner/Verifier/ActionBus等) |

---

## Core/ 文件迁移表

| # | 当前路径 | 行数 | V4 目标 | 迁移类型 | 依赖者 | 风险 | 备注 |
|---|----------|------|---------|----------|--------|------|------|
| 1 | `core/__init__.py` | 70 | 8 个子包 `__init__.py` | REFACTOR | 所有外部 import | LOW | 重构为分层导出, 不再导出所有模块 |
| 2 | `core/engine.py` | 252 | `kernel/engine.py` | REFACTOR | test_platform.py | HIGH | 与 engine_xai.py 合并为唯一引擎入口 |
| 3 | `core/engine_xai.py` | 1,272 | `kernel/engine.py` + `kernel/lifecycle.py` | REFACTOR | server_xai.py | HIGH | 拆分为 engine(编排) + lifecycle(HTTP/SSE) |
| 4 | `core/control_loop.py` | 119 | `kernel/lifecycle.py` (合并) | MIGRATE | engine_xai.py | LOW | ControlLoop.act() 保持原样, 并入 lifecycle |
| 5 | `core/intent_router.py` | 150 | `cognition/intent_router.py` | MIGRATE | engine_xai.py, engine.py, workflow_bridge.py, __init__.py | LOW | 仅移动路径, 代码不变 |
| 6 | `core/guardian.py` | 229 | `governance/guardian.py` + `governance/approval.py` | REFACTOR | engine_xai.py, engine.py, workflow_bridge.py, control_loop.py, meta.py | LOW-MED | 拆分为核心 Guardian + 审批队列 |
| 7 | `core/memory_core.py` | 246 | `memory/memory_core.py` | KEEP | engine_xai.py, engine.py, coordination.py, substrate.py | LOW | 已符合 V4 设计, 拆出 retrieval/consolidation |
| 8 | `core/memory.py` | 159 | — | DELETE | workflow_bridge.py, __init__.py | LOW | V4 §原则二明确删除旧 MemorySystem |
| 9 | `core/substrate.py` | 254 | `execution/executor.py` + `execution/tools.py` + `evolution/evaluator.py` | REFACTOR | engine.py | MED | 混合了执行/工具/进化三种职责, 需拆为三分 |
| 10 | `core/coordination.py` | 184 | `kernel/event_bus.py` + Agent Registry | REFACTOR | engine_xai.py, engine.py | MED | 拆分消息总线 + Agent 管理 |
| 11 | `core/reason.py` | 97 | `cognition/reasoner.py` | MIGRATE | control_loop.py | LOW | 改名 (reason→reasoner) + 移动 |
| 12 | `core/meta.py` | 120 | `cognition/verifier.py` (合并) | REFACTOR | control_loop.py, workflow_bridge.py | LOW | BrierCalibrator + L8Auditor 并入 Verifier |
| 13 | `core/distill.py` | 121 | `evolution/distiller.py` + `evolution/skill_builder.py` | REFACTOR | __init__.py | MED | 拆分为蒸馏器 + 技能构建器 |
| 14 | `core/skills.py` | 128 | `evolution/skill_builder.py` (合并) | REFACTOR | __init__.py | LOW | 合并到 skill_builder.py |
| 15 | `core/runner.py` | 94 | `execution/executor.py` (合并) | REFACTOR | 无运行时调用 | LOW | 长任务执行并入 Executor, 当前无调用方 |
| 16 | `core/grok_build_engine.py` | 378 | `agents/grok_agent.py` + `execution/tools.py` | REFACTOR | engine_xai.py | MED | GrokBuildBridge → Agent, 工具入 execution/tools |
| 17 | `core/orchestrator.py` | 80 | `cognition/planner.py` (合并) | REFACTOR | __init__.py | LOW | DAG 编排并入 Task Planner |
| 18 | `core/kb.py` | 112 | `execution/tools.py` (合并) | REFACTOR | workflow_bridge.py | LOW | 知识库作为执行工具 |
| 19 | `core/loop_safety.py` | 191 | `governance/guardian.py` (合并) | REFACTOR | engine_xai.py | LOW | 5 重闸门并入 Guardian 扩展 |
| 20 | `core/session_store.py` | 124 | `kernel/lifecycle.py` (合并) | REFACTOR | engine_xai.py | LOW | 会话管理是生命周期的一部分 |
| 21 | `core/model_backend.py` | 76 | `models/cloud.py` (合并) | REFACTOR | deepseek_backend.py, reason.py, distill.py, workflow_bridge.py, engine.py, engine_xai.py | LOW | 抽象基类并入云后端文件 |
| 22 | `core/model_registry.py` | 157 | `models/router.py` (合并) | REFACTOR | engine_xai.py, provider_fallback.py | LOW | 注册表并入路由文件 |
| 23 | `core/model_router.py` | 77 | `models/router.py` | MIGRATE | workflow_bridge.py | LOW | 改名 (model_router→router) + 移动 |
| 24 | `core/deepseek_backend.py` | 158 | `models/cloud.py` (合并) | REFACTOR | engine_xai.py, engine.py | LOW | DeepSeek 是云后端的一种实现 |
| 25 | `core/provider_fallback.py` | 154 | `models/router.py` (合并) | REFACTOR | engine_xai.py | LOW | 故障轮换是路由的一部分 |
| 26 | `core/project.py` | 164 | `memory/memory_core.py` (合并) | REFACTOR | engine_xai.py | LOW | Project 管理是记忆作用域 |
| 27 | `core/openclaw_gateway.py` | 233 | `execution/tools.py` (合并) | REFACTOR | __init__.py | MED | 网关抽象→工具注册, 替换为 ActionBus |
| 28 | `core/workflow_bridge.py` | 211 | `kernel/lifecycle.py` (合并) | REFACTOR | 旧 engine.py | LOW-MED | 画布执行并入 lifecycle |
| 29 | `core/adapters/__init__.py` | 18 | — | DELETE | engine_xai.py | LOW | adapters/ 目录整体删除 |
| 30 | `core/adapters/base.py` | 48 | — | DELETE | hermes_adapter.py, openclaw_adapter.py, memory_adapter.py | LOW | Adapter 模式被 V4 直接导入替代 |
| 31 | `core/adapters/hermes_adapter.py` | 331 | `agents/hermes_agent.py` | REFACTOR | engine_xai.py | LOW-MED | 移除 Adapter 基类, 改为 Agent 模式 |
| 32 | `core/adapters/memory_adapter.py` | 327 | — | DELETE | engine_xai.py | LOW-MED | V4 §原则二明确删除 MemoryAdapter 双轨 |
| 33 | `core/adapters/openclaw_adapter.py` | 513 | `execution/tools.py` (合并) | REFACTOR | engine_xai.py | MED | 工具能力整合到 execution/tools |

---

## 关联文件迁移

| # | 当前路径 | 行数 | V4 目标 | 迁移类型 | 风险 | 备注 |
|---|----------|------|---------|----------|------|------|
| 34 | `server_xai.py` | 585 | `kernel/lifecycle.py` + 瘦入口 (~20行) | REFACTOR | HIGH | HTTP 路由合并到 lifecycle, 入口变 thin wrapper |
| 35 | `web/app.js` | 1,361 | `web/app.js` (保持) | KEEP | LOW | 仅更新 API 路径 (如 /api/chat → V4 新路由) |
| 36 | `web/index.html` | 345 | `web/index.html` (保持) | KEEP | LOW | 布局不变 |
| 37 | `web/styles.css` | 807 | `web/styles.css` (保持) | KEEP | LOW | 样式无需更改 |

---

## 废料清理清单 (Phase 0)

| # | 文件 | 说明 |
|---|------|------|
| B1 | `core/engine_xai.py.bak.*` (3 个) | 时间戳备份文件 |
| B2 | `core/memory_core.py.bak.*` (1 个) | 时间戳备份文件 |
| B3 | `web/app.js.bak.*` (4 个) | 时间戳备份文件 |
| B4 | `web/index.html.bak.*` (4 个) | 时间戳备份文件 |
| B5 | `web/styles.css.bak.*` (4 个) | 时间戳备份文件 |

---

## V4 新增模块

| # | 目标路径 | 估算行数 | 优先级 | 说明 |
|---|----------|----------|--------|------|
| N1 | `cognition/planner.py` | ~250 | P0 | Task Planner — 目标→步骤→Agent 分配 |
| N2 | `cognition/verifier.py` | ~200 | P0 | Verifier — Pass/Retry 门控 |
| N3 | `execution/action_bus.py` | ~150 | P0 | ActionBus — 统一动作入口 |
| N4 | `agents/agent_registry.py` | ~100 | P1 | Agent 能力注册表 |
| N5 | `agents/reviewer_agent.py` | ~150 | P1 | Reviewer Agent — 质量/风险验证 |
| N6 | `kernel/event_bus.py` | ~100 | P1 | 系统事件总线 |
| N7 | `memory/retrieval.py` | ~100 | P2 | 从 memory_core 拆出的检索逻辑 |
| N8 | `memory/consolidation.py` | ~80 | P2 | 从 memory_core 拆出的巩固逻辑 |
| N9 | `evolution/skill_builder.py` | ~200 | P2 | Failure→Skill 流水线 |
| N10 | `models/ollama.py` | ~150 | Phase 4 | Ollama 本地后端 |

---

## 风险矩阵

| 风险条目 | 等级 | 关键模块 | 缓解措施 |
|----------|------|----------|----------|
| 引擎合并 | HIGH | engine.py + engine_xai.py → kernel/engine.py | Phase 0 建立测试基线, Phase 1 逐步替换 |
| Import 雪崩 | HIGH | 53 个跨文件 import | sed 批量替换 + import 检查 |
| 记忆双轨 | MED | memory.py + memory_adapter.py | Phase 1 强制统一为 MemoryCore |
| ActionBus 空白 | MED | 全部模块 | Phase 1 创建后逐步迁移调用方 |
| Planner/Verifier 缺失 | HIGH | cognition/ | 利用现有 orchestration + meta 加速实现 |
| 前端兼容 | LOW | web/ | 保持 API 向后兼容 1 个 Phase |

---

## Import 引用影响分析 (Top 5)

| 文件 | Import 数 | 影响范围 |
|------|-----------|----------|
| `core/__init__.py` | 69 个符号 | 所有 `from core import X` 调用者 |
| `core/engine_xai.py` | 18 个模块 | server_xai.py (唯一调用者) |
| `core/engine.py` | 10 个模块 | test_platform.py |
| `core/workflow_bridge.py` | 7 个模块 | 旧 engine.py |
| `server_xai.py` | 1 个核心 import | 自身 |

---

## 代码量变化

| 层级 | V3 (当前) | V4 (目标) | 变化 |
|------|-----------|-----------|------|
| 引擎/内核 | 1,524 | 800 | -724 |
| 认知层 | 486 | 700 | +214 |
| Agent 层 | 709 | 700 | -9 |
| 执行层 | 1,200 | 750 | -450 |
| 记忆层 | 732 | 330 | -402 |
| 进化层 | 249 | 400 | +151 |
| 治理层 | 420 | 260 | -160 |
| 模型层 | 622 | 600 | -22 |
| 其他(已合并) | 369 | 0 | -369 |
| **总计** | **~6,404** | **~4,540** | **-1,864** |

---

*数据基于 XAI_Kernel_V4_Architecture_Consolidation_Manual.md 及 2026-07-18 实际源码扫描。*
