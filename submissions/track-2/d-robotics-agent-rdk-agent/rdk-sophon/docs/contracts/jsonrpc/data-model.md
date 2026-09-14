# 6. StateSnapshot 数据模型契约

> 守护进程对外暴露的硬件状态 JSON 字段定义。
> 这是 `get_state` 的 result、`get_*` 各片段的 result、`telemetry` notification 的 params 的**完整字段表**。
> 外部调用方据此解析 JSON、绑定字段。
> 实现源码：`crates/shared/src/protocol/snapshot.rs`

## 6.1 命名规则（重要）

字段 JSON 名分两种：
- **顶层快照字段**与**非数值字段**：`snake_case`，如 `uptime_secs`、`core_freq_mhz`、`usage_pct`、`voltages_mv`、`battery_pct`、`utilisation_pct`、`fs_type`、`rx_bytes`（→ `rxBytes`）等。
- **字节/温度等数值字段**：`camelCase`，经 `#[serde(rename = "...")]`，如 `tempC`、`totalBytes`、`usedBytes`、`freeBytes`、`swapTotalBytes`、`swapUsedBytes`、`rxBytes`、`txBytes`、`mV`。
- `mac` 字段显式 rename 为 `mac`（无变化）。

**省略规则**：`Option` 字段值为 `None` 时整个字段省略（`skip_serializing_if = "Option::is_none"`）；多数 `Vec` 字段为空时省略（`skip_serializing_if = "Vec::is_empty"`，且带 `#[serde(default)]`）。

## 6.2 StateSnapshot

顶层对象，`get_state` 返回，`telemetry` 的 `params`。

| 字段 | JSON 名 | 类型 | 省略条件 | 说明 |
|------|---------|------|---------|------|
| timestamp | `timestamp` | string (RFC3339) | None 时省略 | 采集时刻 UTC |
| hostname | `hostname` | string | None 时省略 | **协议预留，当前不产** |
| uptime_secs | `uptime_secs` | f64 | None 时省略 | **协议预留，当前不产** |
| thermal | `thermal` | Thermal 对象 | None 时省略 | 温度 |
| cpu | `cpu` | CpuInfo 对象 | None 时省略 | CPU |
| memory | `memory` | MemoryInfo 对象 | None 时省略 | 内存 |
| disks | `disks` | [DiskInfo] 数组 | None 时省略 | 磁盘 |
| net | `net` | [NetInfo] 数组 | None 时省略 | 网络 |
| bpu | `bpu` | BpuInfo 对象 | None 时省略 | BPU（仅 RDK） |
| power | `power` | PowerInfo 对象 | None 时省略 | **协议预留，当前不产** |

> **"协议预留、当前不产"** 的字段：协议层已定义，但当前 `build_production_app` 注册的 6 个采集器均不填充。调用方应兼容这些字段缺失。

## 6.3 Thermal

`get_thermal` 的 result，`StateSnapshot.thermal`。

```json
{"zones": [{"name": "thermal-cpu", "tempC": 62.0}]}
```

| 字段 | JSON 名 | 类型 | 省略条件 |
|------|---------|------|---------|
| zones | `zones` | [ThermalZone] | 空时省略 |

### ThermalZone

| 字段 | JSON 名 | 类型 | 说明 |
|------|---------|------|------|
| name | `name` | string | zone 标签（如 `thermal-cpu`、`thermal-ddr`），来自 `/sys/class/thermal/.../type` |
| temp_c | `tempC` | f64 | 温度，摄氏度（毫摄氏度 / 1000） |

## 6.4 CpuInfo

`get_cpu` 的 result，`StateSnapshot.cpu`。

```json
{"load_avg": [1.87, 2.4, 1.17], "core_usage": [0,0,0,0,0,0,0,0], "core_freq_mhz": [1500.0]}
```

| 字段 | JSON 名 | 类型 | 省略条件 | 说明 |
|------|---------|------|---------|------|
| load_avg | `load_avg` | [f64; 3] | None 时省略 | 1/5/15 分钟负载平均 |
| core_usage | `core_usage` | [f64] | 空时省略 | 各核利用率 0..100（两帧 /proc/stat 采样） |
| core_freq_mhz | `core_freq_mhz` | [f64] | 空时省略 | 各核频率 MHz |

## 6.5 MemoryInfo

`get_memory` 的 result，`StateSnapshot.memory`。单位：字节。

```json
{"totalBytes": 7424344064, "usedBytes": 2954145792, "freeBytes": 1119498240, "swapTotalBytes": 0, "swapUsedBytes": 0}
```

| 字段 | JSON 名 | 类型 | 默认 | 说明 |
|------|---------|------|------|------|
| total_bytes | `totalBytes` | u64 | — | MemTotal |
| used_bytes | `usedBytes` | u64 | — | `total - MemAvailable` |
| free_bytes | `freeBytes` | u64 | — | MemFree |
| swap_total_bytes | `swapTotalBytes` | u64 | 0 | SwapTotal |
| swap_used_bytes | `swapUsedBytes` | u64 | 0 | `SwapTotal - SwapFree` |

## 6.6 DiskInfo

`get_disk` 返回数组元素，`StateSnapshot.disks`。

```json
{"mount": "/", "fs_type": "ext4", "totalBytes": 30966890496, "usedBytes": 19720384512, "freeBytes": 9741590528, "usage_pct": 63.68}
```

| 字段 | JSON 名 | 类型 | 说明 |
|------|---------|------|------|
| mount | `mount` | string | 挂载点（如 `/`） |
| fs_type | `fs_type` | string | 文件系统类型（如 `ext4`、`vfat`） |
| total_bytes | `totalBytes` | u64 | 总字节 |
| used_bytes | `usedBytes` | u64 | `total - free(blocks_free)` |
| free_bytes | `freeBytes` | u64 | **`blocks_avail`（可用块）**，非 `blocks_free` |
| usage_pct | `usage_pct` | f64 | 使用率 0..100 |

> 仅含真实文件系统，排除 `proc`/`sysfs`/`devtmpfs`/`tmpfs` 等伪文件系统。

## 6.7 NetInfo

`get_net` 返回数组元素，`StateSnapshot.net`。`lo` 接口排除。

```json
{"name": "wlan0", "up": true, "mac": "18:ce:df:79:40:53", "addrs": ["192.168.128.10"], "rxBytes": 304664629, "txBytes": 1410732}
```

| 字段 | JSON 名 | 类型 | 省略条件 | 说明 |
|------|---------|------|---------|------|
| name | `name` | string | — | 接口名（如 `wlan0`、`usb0`） |
| up | `up` | bool | — | operstate 是否 up |
| mac | `mac` | string | None 时省略 | MAC 地址 |
| addrs | `addrs` | [string] | 空时省略 | 本机地址（best-effort，非按接口分组） |
| rx_bytes | `rxBytes` | u64 | — | 接收字节 |
| tx_bytes | `txBytes` | u64 | — | 发送字节 |

## 6.8 BpuInfo

`get_bpu` 的 result，`StateSnapshot.bpu`。**仅 RDK 板**有值，否则 `null`。

```json
{"utilisation_pct": 30.0, "temp_c": 55.0, "freq_mhz": 1500.0}
```

| 字段 | JSON 名 | 类型 | 省略条件 | 说明 |
|------|---------|------|---------|------|
| utilisation_pct | `utilisation_pct` | f64 | None 时省略 | 利用率 0..100 |
| temp_c | `temp_c` | f64 | None 时省略 | 温度 °C |
| freq_mhz | `freq_mhz` | f64 | None 时省略 | 频率 MHz |

## 6.9 PowerInfo（预留）

**协议预留，当前无采集器填充**，调用方应兼容缺失。

| 字段 | JSON 名 | 类型 | 省略条件 | 说明 |
|------|---------|------|---------|------|
| voltages_mv | `voltages_mv` | [PowerRail] | 空时省略 | 电压轨 |
| battery_pct | `battery_pct` | f64 | None 时省略 | 电池百分比 |
| online | `online` | bool | None 时省略 | 在线/有电 |

### PowerRail

| 字段 | JSON 名 | 类型 |
|------|---------|------|
| name | `name` | string |
| mv | `mV` | f64 |

## 6.10 兼容性建议

1. **字段可选**：除 `name`/`up`/`rxBytes`/`txBytes`/`exit` 等少数必填外，多数字段可省略。调用方解析时用"存在则读、缺失则默认"策略。
2. **camelCase 字段**：`tempC`/`totalBytes`/`usedBytes`/`freeBytes`/`swapTotalBytes`/`swapUsedBytes`/`rxBytes`/`txBytes`/`mV` 必须用此名。
3. **预留字段**：`hostname`/`uptime_secs`/`power` 当前不产，别依赖。
4. **单位**：字节字段是字节（非 KB）；温度是摄氏度；频率是 MHz；负载是 1/5/15 分钟平均。
