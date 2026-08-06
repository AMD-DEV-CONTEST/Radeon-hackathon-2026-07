# XAI 恢复目标定义（RTO / RPO · T4 · 运维就绪）

> 与 `server_routes_metrics.py`(/api/metrics) 配套，定义「挂了多久修好、最多丢多少」。
> 当前为内部产品级目标；随实证期数据再校准。

## 一、RTO（恢复时间目标 Recovery Time Objective）

| 场景 | 目标 RTO | 现有能力 | 状态 |
|---|---|---|---|
| 单实例进程崩溃 | < 30s | `start_xai.sh` 守护循环（崩溃即重生）；或 launchd 托管 | ✅ |
| 手动重启 | < 60s | `bash start_xai.sh` / `python server_xai.py` | ✅ |
| 配置/代码误改回滚 | < 5min | `xai-snapshot.sh`（git tag + 源码/数据双 tar 回滚基线） | ✅ |
| 硬件/整机故障 | < 30min | 7 库 SQLite + `xai-backup.py` 周期备份 | ⚠️ 依赖备份新鲜度 |

## 二、RPO（恢复点目标 Recovery Point Objective）

| 数据 | 目标 RPO | 现有能力 | 状态 |
|---|---|---|---|
| 记忆库（memory.db 等 7 库） | < 30min | `xai-backup.py` 自动备份（含 watchdog 周期）+ `verify_recovery()` 演练 | ✅ |
| 工作区产物（artifacts/uploads） | < 24h | 文件系统 + 快照 | ⚠️ 未纳入自动备份脚本（建议补） |
| 会话/任务状态 | < 5min | SQLite 即时落盘 | ✅ |

## 三、已落地的恢复工具链

- `xai-backup.py`：`backup_one`(SQLite online backup) + `verify_recovery()`(真还原+integrity_check) — **已实弹演练 7 DB integrity=OK**。
- `xai-snapshot.sh`：一行命令回滚基线（git tag + 源码 tar + 数据 tar + 恢复说明）。
- `server_xai.py::_backup_watchdog`：周期（30s）on-change 备份守护。
- 启动自检 `run_startup_selfcheck`：DB 完整性 + 路由模块可导入自检。

## 四、待补强（v3.1 实证期）

1. **P1 工作区产物纳入备份**：`artifacts/`、`uploads/` 加入 `xai-backup.py` 打包。
2. **P1 告警闭环**：`/api/metrics` 接入阈值告警（uptime/daily error 突增 → 通知）。
3. **P2 演练常态化**：把 `verify_recovery()` 纳入每周巡检（与 `metrics_snapshot.py` 同节奏）。
