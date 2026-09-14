# 4. domain crate 设计文档

> DDD 层：domain（领域）。依赖 `shared`、`infra`（仅 `statvfs_of`）。
> 源码：`crates/domain/`

## 4.1 职责

domain 包含：
- **采集器**（`collectors` 子模块）：6 个硬件采集器，构造期注入 Reader，实现 `ports::Collector`。
- **领域服务**：`StateService`、`AlertService`、`TelemetryService`。
- **策略**：`CommandPolicy`（shell deny/timeout 纯策略，零 IO）。
- **告警模型**：`AlertThresholds`/`AlertRule`/`AlertKind`。

domain 经 ports 注入读取，**本身不直接碰 `/sys`/`/proc`/进程**（除 `DiskCollector` 调 `infra::statvfs_of`）。

## 4.2 模块结构

```
domain/src/
├── lib.rs              # pub use 重导出
├── collectors/         # 6 个采集器
│   ├── mod.rs
│   ├── thermal.rs
│   ├── cpu.rs
│   ├── memory.rs
│   ├── disk.rs
│   ├── net.rs
│   └── bpu.rs
├── state_service.rs
├── alert_service.rs
├── telemetry_service.rs
├── command_policy.rs
└── alert_rules.rs
```

## 4.3 采集器（`collectors/`）

每个采集器是 struct，构造期注入 Reader trait，返回 `StateSnapshotFragment`。

| 采集器 | 注入 | 读取路径 | 返回片段 |
|------|------|------|------|
| `ThermalCollector` | `SysfsReader` | `/sys/class/thermal/thermal_zone*/{temp,type}` | `Thermal` |
| `CpuCollector` | `ProcReader` + `SysfsReader` | `/proc/loadavg` + `/proc/stat`（两帧算 busy%）+ cpufreq sysfs | `Cpu` |
| `MemoryCollector` | `ProcReader` | `/proc/meminfo` | `Memory` |
| `DiskCollector` | `ProcReader` + statvfs fn | `/proc/mounts` + `statvfs` 各挂载点 | `Disks` |
| `NetCollector` | `ProcReader` + `SysfsReader` | `/proc/net/dev` + `/sys/class/net/<if>/{operstate,address}` | `Net` |
| `BpuCollector` | `HrutGateway` | `hrut_bpuinfo`/`hrut_sensors`/`hrut_thermal` | `Bpu` |

采集器**独立、best-effort**：失败返回 `None`，不 panic，不拖垮其他采集器。

### 关键实现细节
- `CpuCollector`：`tokio::time::sleep(100ms)` 读两帧 `/proc/stat` 算各核 busy%（jiffies）。
- `DiskCollector`：`new()` 注入 `infra::statvfs_of`（生产）；`with_statvfs(fn)` 注入假函数（测试）。**free_bytes 填 `blocks_avail`（可用块）而非 `blocks_free`**。
- `BpuCollector`：`temp()` 先试 `hrut_sensors` 失败再 `hrut_thermal`。
- 各采集器内部有 `gather()` 返回强类型，`Collector::collect()` 包成 `StateSnapshotFragment`（避免 inherent 方法遮蔽 trait 方法）。

## 4.4 领域服务

### StateService（`state_service.rs`）
持 `Arc<RwLock<StateSnapshot>>`，返回**领域类型**（不碰 `serde_json::Value`，转换在 application 层）。
- `new(snapshot)` / `snapshot_handle() -> Arc<RwLock<StateSnapshot>>`
- `get_state() -> StateSnapshot`（clone 副本）
- `get_thermal/cpu/memory/disk/net/bpu() -> Option<T>`（各片段）
- `replace(snap)`：原子替换。Orchestrator 应**锁外** collect 完再 `replace`，避免采集期间持写锁阻塞读。

### AlertService（`alert_service.rs`）
纯函数 `evaluate(snap, thresholds) -> Vec<AlertRule>`。不碰 JSON-RPC，notification 组装在 daemon/bootstrap。
- 温度：任一 zone `temp_c >= thresholds.temp_c` → `AlertRule{Thermal, zone名, temp_c, temp_c阈值}`。
- 磁盘：任一非伪文件系统 `usage_pct >= thresholds.disk_usage_pct` → `AlertRule{Disk, mount, usage_pct, 阈值}`。

### TelemetryService（`telemetry_service.rs`）
`build_notification(snap) -> JsonRpcMessage`：把 `StateSnapshot` 整体序列化为 named params，包成 `method="telemetry"` 的 notification（无 id）。

### CommandPolicy（`command_policy.rs`）
纯策略，零 IO，零 async。
- `default_deny_patterns() -> Vec<String>`：`["rm -rf /", "mkfs", "dd if=/dev/zero of=/dev/", ":(){ :|:&"]`。
- `from_config(enabled, timeout_secs, extra_deny)`：内置 deny 列表**始终生效**，`extra_deny` 只能追加收紧，不可削弱。
- `check(cmdline) -> Result<(), Error>`：`enabled=false` → `ShellDisabled`；命中 deny → `ShellDenied`；否则 `Ok`。

### AlertThresholds / AlertRule / AlertKind（`alert_rules.rs`）
- `AlertThresholds { temp_c: f64, disk_usage_pct: f64 }`，Default `75.0 / 90.0`。
- `AlertKind::{Thermal, Disk}`。
- `AlertRule { kind, target, current, threshold }`。

## 4.5 依赖

内部：`shared`、`infra`。外部：`tokio`/`tracing`/`serde`/`serde_json`/`thiserror`/`async-trait`。dev：`testkit`。

## 4.6 设计约束

- domain **不得**依赖 `application`/`daemon`（单向向下）。
- 领域服务**不得**返回 `serde_json::Value`（wire 格式由 application 转换）。
- `CommandPolicy` **不得**含 IO（纯策略可单测）。

## 4.7 新增采集器

1. 在 `collectors/` 新建 `xxx.rs`，定义 `XxxCollector` struct，构造期注入 Reader。
2. 实现 `ports::Collector`，返回 `StateSnapshotFragment::Xxx(...)`（若片段是新的，先在 `shared/protocol/snapshot.rs` 加枚举变体 + `merge_fragment` 分支）。
3. 在 `collectors/mod.rs` 导出。
4. 在 `domain/src/lib.rs` `pub use` 重导出。
5. 在 `daemon/src/bootstrap.rs` 的 `build_production_app`/`build_test_app` 注册新 Collector。
6. 同步更新 `docs/design/domain.md` 与 `../contracts/jsonrpc/data-model.md`。
