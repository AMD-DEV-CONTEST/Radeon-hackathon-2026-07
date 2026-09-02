# XAI 成功指标与定期回看机制（T6 · 六维验收·维度六 诚实·价值·治理）

> 把「当初定的成功标准」变成可量化、可定期回看的习惯，避免「上线即失忆」。
> 配套脚本：`scripts/metrics_snapshot.py`（一键快照，建议每周一次）。

## 一、指标框架（四维度，对齐 METRICS_TRACKER）

| 维度 | 指标 | 目标/健康线 | 数据来源 |
|---|---|---|---|
| **效率** | 首响延迟（/api/chat/send p50） | < 模型固有延迟 + 2s | `loadtest_core.py` |
| | 吞吐（/api/intent、/api/memory） | > 1000 RPS | `loadtest_core.py` |
| **质量** | 单元测试通过率 | ≥ 95%（当前 117/121≈97%） | `pytest tests/` |
| | 端到端冒烟通过率 | 100%（38/38） | `scripts/smoke_test.py` |
| | 诚实检查通过率 | 100%（13/13） | `scripts/honesty_check.py` |
| **学习** | failure_correction 积累数 | 单调增长（越用越聪明） | `memory_core` 第8层 |
| | Distill/GEPA 自进化运行数 | 定期发生 | `core/distill.py` |
| **成本** | 模型 token 消耗 | 受控、可审计 | `model_registry` 计量 |
| | 人工注意力占用（审批/纠偏分钟数） | 随 Guardian 收敛下降 | `guardian_bridge` 工单 |

## 二、六维验收判定阈值（交付闸门）

| 维度 | 交付门槛 | 当前判定 |
|---|---|---|
| 一 功能与需求 | smoke 全绿 + 关键需求 RTM 可追溯 | ✅ |
| 二 性能质量 | 核心接口 0 错 + 有并发护栏 | ✅（T1 补护栏） |
| 三 安全验收 | 零硬编码密钥 + 鉴权全 PASS + 依赖低风险 | ✅（T2） |
| 四 数据与状态 | 重启一致 + 备份恢复演练 OK | ✅（T3 + xai-backup） |
| 五 运维就绪 | 可观测接口 + 回滚基线 + 自动备份 | ✅（T4 + snapshot） |
| 六 诚实·治理 | 诚实 13/13 + 成功指标可回看 | ✅（T6） |

## 三、回看节奏（常态化）

- **每日**：`xai-backup.py` 自动备份（已部署 watchdog）。
- **每周**：跑 `python3 scripts/metrics_snapshot.py`，对照上表看趋势；若任一指标跌破健康线，触发 ACR 复盘。
- **每版本/发布前**：重跑 `ACCEPTANCE_XAI_LIVE_*.md` 六维清单 + `security_scan.py`。

## 四、当前基线（2026-07-28 六维验收实弹）

- 功能：smoke 38/38 · pytest 117 passed + 4 skipped
- 性能：/api/chat/send 0 错（p50≈8.7s，瓶颈在模型）· /api/intent 1645 RPS · /api/memory 1941 RPS · 并发护栏=20
- 安全：0 密钥 · 4 接口鉴权全 PASS · 依赖仅 PyYAML(MIT)
- 数据：重启读回 OK · 备份恢复演练 7 DB integrity=OK
- 运维：/api/metrics 在线 · xai-snapshot 回滚基线 · launchd 自动备份
- 诚实：13/13

> 本文件与 `metrics_snapshot.py` 构成「成功标准回看」最小闭环，进 v3.1 三十天实证期首批常态化项。
