# 2. JSON-RPC 方法契约

> 本文档定义守护进程支持的所有 RPC 方法：方法名、参数、返回结构。
> 外部调用方据此构造 Request、解析 result。
> 实现源码：`crates/application/src/rpc_dispatcher.rs:60-89` 的 `match method`

所有方法在 `RpcDispatcher::call` 中路由。未知方法返回 `MethodNotFound`（-32601）。

## 2.1 方法总览

| 方法 | 参数 | 返回 result | 说明 |
|------|------|------------|------|
| [`ping`](#22-ping) | 无 | `{"pong":true,"ts":<RFC3339>}` | 连通性检查 |
| [`get_state`](#23-get_state) | 无 | `StateSnapshot` 对象 | 完整硬件状态快照 |
| [`get_thermal`](#24-get_thermal) | 无 | `Thermal` 或 `null` | 温度 |
| [`get_cpu`](#25-get_cpu) | 无 | `CpuInfo` 或 `null` | CPU |
| [`get_memory`](#26-get_memory) | 无 | `MemoryInfo` 或 `null` | 内存 |
| [`get_disk`](#27-get_disk) | 无 | `[DiskInfo]` 或 `null` | 磁盘 |
| [`get_net`](#28-get_net) | 无 | `[NetInfo]` 或 `null` | 网络 |
| [`get_bpu`](#29-get_bpu) | 无 | `BpuInfo` 或 `null` | BPU（仅 RDK 板） |
| [`refresh_state`](#210-refresh_state) | 无 | `{"ok":true,"ts":<RFC3339>}` | 立即触发一次采集 |
| [`exec_shell`](#211-exec_shell) | `{"cmd":<string>}` | `{"exit":<int?>,"stdout":<str>,"stderr":<str>}` | 执行 shell（受策略约束） |
| [`plugin.list`](#212-pluginlist) | 无 | `[{"id":<str>,"description":<str>}]` | 列出动态控制插件 |
| [`plugin.invoke`](#213-plugininvoke) | `{"plugin":<str>,"args":[<str>]}` | `{"exit":<int?>,"stdout":<str>,"stderr":<str>}` | 调用动态控制插件 |

各片段的**完整字段定义**见 [`data-model.md`](data-model.md)。

---

## 2.2 `ping`

连通性检查，立即返回。

**请求**：
```json
{"jsonrpc":"2.0","id":1,"method":"ping"}
```

**响应**：
```json
{"jsonrpc":"2.0","id":1,"result":{"pong":true,"ts":"2026-07-28T07:48:54Z"}}
```
- `pong`：恒为 `true`。
- `ts`：RFC3339 秒精度 UTC 时间戳。

---

## 2.3 `get_state`

返回守护进程当前缓存的最完整硬件状态快照。**不触发新采集**（读缓存）；要立即刷新用 `refresh_state`。

**请求**：
```json
{"jsonrpc":"2.0","id":1,"method":"get_state"}
```

**响应**：完整 `StateSnapshot` 对象（字段见 [`data-model.md`](data-model.md)）。空字段省略。序列化失败时返回 `{}`（而非 `null`）。

**示例（节选）**：
```json
{"jsonrpc":"2.0","id":1,"result":{
  "timestamp":"2026-07-28T05:41:14Z",
  "hostname":"ubuntu",
  "uptime_secs":56221.73,
  "thermal":{"zones":[{"name":"thermal-ddr","tempC":62.245},{"name":"thermal-cpu","tempC":61.659}]},
  "cpu":{"load_avg":[1.87,2.4,1.17],"core_usage":[0,0,0,0,0,0,0,0],"core_freq_mhz":[1500.0]},
  "memory":{"totalBytes":7424344064,"usedBytes":2954145792,"freeBytes":1119498240,"swapTotalBytes":0,"swapUsedBytes":0},
  "disks":[{"mount":"/","fs_type":"ext4","totalBytes":30966890496,"usedBytes":19720384512,"freeBytes":9741590528,"usage_pct":63.68}],
  "net":[{"name":"wlan0","up":true,"mac":"18:ce:df:79:40:53","addrs":["192.168.128.10"],"rxBytes":304664629,"txBytes":1410732}]
}}
```

---

## 2.4 `get_thermal`

返回温度片段。无温度数据（非 Linux 或无 thermal zone）时返回 `null`。

**请求**：`{"jsonrpc":"2.0","id":1,"method":"get_thermal"}`
**响应**：`Thermal` 对象或 `null`。字段见 [`data-model.md`](data-model.md#thermal)。

```json
{"jsonrpc":"2.0","id":1,"result":{"zones":[{"name":"thermal-cpu","tempC":62.0}]}}
```

---

## 2.5 `get_cpu`

返回 CPU 片段。字段见 [`data-model.md`](data-model.md#cpuinfo)。

```json
{"jsonrpc":"2.0","id":1,"result":{"load_avg":[1.87,2.4,1.17],"core_usage":[0,0,0,0,0,0,0,0],"core_freq_mhz":[1500.0]}}
```

---

## 2.6 `get_memory`

返回内存片段。字段见 [`data-model.md`](data-model.md#memoryinfo)。
- `used_bytes = total - MemAvailable`，`free_bytes = MemFree`。

```json
{"jsonrpc":"2.0","id":1,"result":{"totalBytes":7424344064,"usedBytes":2954145792,"freeBytes":1119498240,"swapTotalBytes":0,"swapUsedBytes":0}}
```

---

## 2.7 `get_disk`

返回磁盘数组。字段见 [`data-model.md`](data-model.md#diskinfo)。
- `free_bytes` 填的是 `blocks_avail`（可用块），不是 `blocks_free`。
- 仅含真实文件系统（排除 proc/sysfs/tmpfs 等伪文件系统）。

```json
{"jsonrpc":"2.0","id":1,"result":[{"mount":"/","fs_type":"ext4","totalBytes":30966890496,"usedBytes":19720384512,"freeBytes":9741590528,"usage_pct":63.68}]}
```

---

## 2.8 `get_net`

返回网络接口数组。字段见 [`data-model.md`](data-model.md#netinfo)。`lo` 接口被排除。

```json
{"jsonrpc":"2.0","id":1,"result":[{"name":"wlan0","up":true,"mac":"18:ce:df:79:40:53","addrs":["192.168.128.10"],"rxBytes":304664629,"txBytes":1410732}]}
```

---

## 2.9 `get_bpu`

返回 BPU（Horizon Brain Processing Unit）片段。**仅 RDK 板**且 `hrut_*` 工具可用时有值；否则返回 `null`（守护进程自动省略，不报错）。字段见 [`data-model.md`](data-model.md#bpuinfo)。

```json
{"jsonrpc":"2.0","id":1,"result":{"utilisation_pct":30.0,"temp_c":55.0,"freq_mhz":1500.0}}
```

---

## 2.10 `refresh_state`

立即触发一次采集，刷新缓存快照，返回新时间戳。之后调 `get_*` 拿到的就是最新数据。

**请求**：`{"jsonrpc":"2.0","id":1,"method":"refresh_state"}`
**响应**：
```json
{"jsonrpc":"2.0","id":1,"result":{"ok":true,"ts":"2026-07-28T05:41:14Z"}}
```

---

## 2.11 `exec_shell`

执行任意 shell 命令（`sh -c`）。**受策略约束**：必须配置启用 `[shell] enabled = true`，且命令不得命中 deny 列表。

**请求参数**（Named，必需 `cmd` 字符串）：
```json
{"jsonrpc":"2.0","id":1,"method":"exec_shell","params":{"cmd":"uname -a"}}
```
- 缺 `cmd` 或类型错 → `InvalidParams`（-32602）。
- shell 未启用 → `ShellDisabled`（-32001）。
- 命中 deny（如 `mkfs`/`rm -rf /`）→ `ShellDenied`（-32002）。

**响应**（成功）：
```json
{"jsonrpc":"2.0","id":1,"result":{"exit":0,"stdout":"Linux ubuntu 6.1.83 aarch64 ...\n","stderr":""}}
```
- `exit`：进程退出码（`i32`）；被信号杀死时可能为 `null`。
- `stdout`/`stderr`：截断到 256 KiB/路。
- 命令超时（`shell.timeout_secs`，默认 30s）→ `Timeout`（-32003），子进程被 kill。
- 其它执行错误 → `ExecError`（-32000）。

**审计**：每次 `exec_shell`（成功/失败/超时）都记审计日志（`source`、`args` 截前 200 字符、`outcome`、`duration_ms`）。

---

## 2.12 `plugin.list`

返回当前 `[plugins]` 目录中可发现的动态控制插件。关闭插件功能或目录不存在时返回空数组。

**请求**：`{"jsonrpc":"2.0","id":1,"method":"plugin.list"}`

**响应**：
```json
{"jsonrpc":"2.0","id":1,"result":[{"id":"servo","description":"舵机姿态控制"}]}
```

源码: `crates/application/src/rpc_dispatcher.rs:176-180`、`crates/infra/src/plugin.rs:113-124`。

---

## 2.13 `plugin.invoke`

以精确参数数组调用一个动态插件；服务端不会把参数拼成 shell 命令。

**请求**：
```json
{"jsonrpc":"2.0","id":1,"method":"plugin.invoke","params":{"plugin":"servo","args":["servo","0","-2.0"]}}
```

**响应**：
```json
{"jsonrpc":"2.0","id":1,"result":{"exit":0,"stdout":"","stderr":""}}
```

`plugin` 必须是字符串，`args` 必须是字符串数组；参数错误或插件不存在返回 `InvalidParams`（-32602）。插件 manifest 设置的正数 `timeout_secs` 超时时返回 `Timeout`（-32003）。每次调用均审计为 `plugin.invoke`。

源码: `crates/application/src/rpc_dispatcher.rs:182-255`、`crates/infra/src/plugin.rs:126-183`。
