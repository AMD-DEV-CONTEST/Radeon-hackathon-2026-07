# XAI 需求→用例→代码 追溯矩阵（RTM · T5 · 六维验收·维度一/四 支撑）

> 目的：把「当初要什么」对到「测了什么」对到「代码在哪」，验收一键可追溯。
> 维度一（功能与需求）与维度四（数据与状态）的核心证据链。

| # | 需求条目 | 验收用例 / 脚本 | 代码模块 | 验证结果 |
|---|---|---|---|---|
| R1 | 双核融合架构（Hermes+Grok Build 并列，Intent Router 仲裁） | `tests/test_intent_router.py`；`POST /api/intent` 实时分类 | `core/kernel/engine.py`(`_classify_intent`)、`server_routes_intent.py` | ✅ 意图识别 1645 RPS |
| R2 | 8 层元认知记忆单一事实源（含 failure_correction） | `tests/test_xai_core.py`、`tests/test_idempotency.py` | `core/memory_core.py` | ✅ store/query/restart 全过 |
| R3 | 记忆跨项目隔离（project_id） | `memory_core.query(project_id=)` 单测 + 读侧召回过滤 | `core/memory_core.py:174-183` | ✅ 隔离代码确认 |
| R4 | Guardian P0/P1/P2 风险分级 + 二次确认 | `tests/test_xai_core.py::TestGuardian` | `core/guardian.py`、`core/kernel/guardian_bridge.py` | ✅ P0 自动拦截 / P1 转审批 |
| R5 | HITL 写操作审批工单（不直执行） | `tests/test_idempotency.py::TestApprovalIdempotency`；`POST /api/guardian/grok-write/request` 实测返回 pending | `server_xai.py:_handle_guardian_grok_write_request`、`guardian_bridge.create_approval` | ✅ 生成工单，零直执行 |
| R6 | 元认知读侧闭环（failure_correction 注入 system） | `tests/test_bimodal_contract.py`；MEM-1 读侧 | `memory_bridge.retrieve_memory_context` → `engine._build_system_prompt` | ✅ 全通用对话覆盖 |
| R7 | 核心对话端到端可用 | `POST /api/chat/send` 压测 6/6 成功 | `server_routes_chat.py`、`core/kernel/engine.py` | ✅ 0 错（瓶颈在模型延迟） |
| R8 | 并发护栏（资源上限，不崩） | `scripts/loadtest_core.py`（高并发无错）；semaphore 代码 | `server_routes_chat.py:_CHAT_SEM=Semaphore(20)` | ✅ 新增护栏生效 |
| R9 | 运行监控可观测（看板接口） | `GET /api/metrics` 实测 200 + 结构正确 | `server_routes_metrics.py` | ✅ 带 token 200 / 无 token 401 |
| R10 | 安全：零硬编码密钥 + 危险调用拦截 | `scripts/security_scan.py`（SAST+依赖+闸门+Guardian） | `core/adapters/openclaw_adapter.py`(安全 lint)、`server_xai.py:_check_auth` | ✅ 0 密钥 / 8 命中均为检测规则 |
| R11 | 数据重启一致性 / 幂等 | `tests/test_idempotency.py`（restart + 并发 + 审批幂等） | `core/memory_core.py`、`guardian_bridge.resolve_approval` | ✅ 5/5 通过 |
| R12 | 备份与恢复演练 | `xai-backup.py --verify` 真恢复演练 | `xai-backup.py`(`verify_recovery`)、`server_xai.py:_backup_watchdog` | ✅ 7 DB 恢复 integrity=OK |
| R13 | 诚实·价值·治理（独占强项） | `scripts/honesty_check.py` 13/13 | `core/` 系统提示词 + 宪法 | ✅ 13/13 |
| R14 | 端到端冒烟全绿 | `scripts/smoke_test.py` 38/38 | 全栈 | ✅ 38/38 |
| R15 | 单元测试套件 | `pytest tests/` 117 passed + 4 skipped | `tests/`(16 文件) | ✅ 117+4 |

> 注：R8/R9/R11/R12 为本次六维验收补强项（T1/T4/T3/备份），其余为既有能力。
> 任意需求项变更，只需更新本表对应行 + 关联测试用例，即可追溯影响面。
