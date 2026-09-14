# 1. 功能模块视角：这个系统会做什么

> 本文面向**想快速了解 rdk-sophon 是什么**的外部读者（人或 AI）。
> 不讲怎么部署、起几个进程（那是 [`processes.md`](processes.md) 的事），只讲**功能上这个系统由哪些模块组成、各自做什么**。
> 所有结论附源码引用，不凭记忆编造。

## 1.1 这个项目是什么

rdk-sophon 是跑在 **RDK 开发板**（地平线 X5 等，aarch64 Linux/Ubuntu）上的**长驻硬件探针守护进程**。一句话定位：

> **板端常驻一个守护进程，持续采集硬件状态、对外暴露 JSON-RPC 接口，让开发机/云端能拉取状态、下发命令。**

它解决三个核心诉求：
1. **硬件状态上报**：把板子的温度/CPU/内存/磁盘/网络/BPU 等状态，周期性推送或按需拉取给外部。
2. **远端下发指令**：外部能远程执行板子上的命令（受安全策略约束）。
3. **多形式接入**：同一套能力，通过命令行 CLI、REST、WebSocket 等不同协议都能访问。

## 1.2 功能模块总览（8 个）

按"这个系统会做什么"切，分 8 个功能模块：

| # | 功能模块 | 干什么 | 主要源码位置 |
|---|---------|--------|------------|
| 1 | 硬件采集 | 周期采温度/CPU/内存/磁盘/网络/BPU | `crates/domain/src/collectors/` + `crates/infra/src/{sysfs,proc,hrut,statvfs}.rs` |
| 2 | RPC 协议 | JSON-RPC 2.0 信封 + 状态快照数据模型 | `crates/shared/src/protocol/` |
| 3 | RPC 分发 | 把 method 路由到对应用例，转 JSON | `crates/application/src/rpc_dispatcher.rs` |
| 4 | 采集编排 | 遍历采集器组装快照、周期刷新 | `crates/application/src/collection_orchestrator.rs` |
| 5 | 会话驱动 | 单连接读请求+转发推送，并发不阻塞 | `crates/application/src/session_service.rs` |
| 6 | shell 执行 | 受策略约束的命令执行（deny/超时/审计） | `crates/domain/src/command_policy.rs` + `crates/infra/src/shell.rs` |
| 7 | 传输适配 | TCP/Unix/Serial + NDJSON 帧 | `crates/infra/src/transport/` |
| 8 | 对外入口 | CLI、REST、WebSocket 三种接入 | `crates/api-cli`、`crates/api-http`、`crates/api-ws` |

下面逐一展开。

## 1.3 模块详解

### 1.3.1 硬件采集

读板子的 `/sys`、`/proc`、调 `hrut_*` 工具，产出结构化的状态片段。**best-effort**：单个采集器失败返回 None，不 panic、不拖垮其他采集器。

6 个采集器（`crates/domain/src/collectors/`）：

| 采集器 | 读什么 | 产出 |
|--------|--------|------|
| ThermalCollector | `/sys/class/thermal/thermal_zone*/{temp,type}` | 各温区温度 °C |
| CpuCollector | `/proc/loadavg` + 两帧 `/proc/stat` 算利用率 + cpufreq | 负载/各核利用率/频率 |
| MemoryCollector | `/proc/meminfo` | 总量/已用/可用/swap |
| DiskCollector | `/proc/mounts` + `statvfs` 各挂载点 | 各文件系统用量 |
| NetCollector | `/proc/net/dev` + `/sys/class/net/*` | 各网卡收发字节/状态/MAC |
| BpuCollector | `hrut_bpuinfo`/`hrut_sensors` | BPU 利用率/温度/频率（仅 RDK 板） |

**关键设计**：采集器构造期注入 `SysfsReader`/`ProcReader`/`HrutGateway` trait（`crates/shared/src/ports/traits.rs`），不直接读文件。这样测试时能注入假 reader，Mac 上也能测采集逻辑（无真实 `/proc`）。

### 1.3.2 RPC 协议

对外用 **JSON-RPC 2.0**（`crates/shared/src/protocol/message.rs`）。三种消息：
- **Request**：`{jsonrpc, id, method, params?}` — 调用方→守护进程，期望响应。
- **Response**：`{jsonrpc, id, result|error}` — 守护进程→调用方，回应 Request。
- **Notification**：`{jsonrpc, method, params?}`，**无 id** — 守护进程→调用方，单向推送（telemetry/alert）。

状态快照 `StateSnapshot`（`crates/shared/src/protocol/snapshot.rs`）是**单一数据源**：拉取（`get_state`）和推送（`telemetry`）读同一份，避免数据漂移。完整字段见 [`contracts/jsonrpc/data-model.md`](../contracts/jsonrpc/data-model.md)。

### 1.3.3 RPC 分发

`RpcDispatcher`（`crates/application/src/rpc_dispatcher.rs:60-89`）把 method 路由到用例。10 个方法：

| 类别 | 方法 |
|------|------|
| 状态拉取 | `get_state`/`get_thermal`/`get_cpu`/`get_memory`/`get_disk`/`get_net`/`get_bpu` |
| 控制 | `ping`/`refresh_state` |
| 命令执行 | `exec_shell` |

`exec_shell` 是唯一带参数的方法（`{cmd: string}`），受策略约束（见 1.3.6）。完整方法契约见 [`contracts/jsonrpc/methods.md`](../contracts/jsonrpc/methods.md)。

### 1.3.4 采集编排

`CollectionOrchestrator`（`crates/application/src/collection_orchestrator.rs`）持 `Vec<Box<dyn Collector>>`，`collect_once()` 遍历各采集器、用 `StateSnapshot::merge_fragment` 组装成完整快照、原子替换。

**关键设计**：锁外 collect 完再 `state.replace`，避免采集期间持写锁阻塞所有 `get_state` 读。新增采集器只改注册表，不改编排逻辑（开闭原则）。

### 1.3.5 会话驱动

`run_session`（`crates/application/src/session_service.rs:34-89`）用 `tokio::select!` 驱动单连接：
- **读分支**：收 Request → dispatch → 回发 Response。
- **广播分支**：把 telemetry/alert notification 转发给对端。

慢 shell（`exec_shell` 是 await）不会阻塞广播转发——runtime 可调度其它分支。这是"远端下发命令"和"周期推送"能同时跑的关键。

### 1.3.6 shell 执行

**策略与执行分离**：
- `CommandPolicy`（`crates/domain/src/command_policy.rs`）— 纯策略，零 IO：`enabled?` deny 匹配? timeout 值? 可单测不碰进程。
- `RealShellRunner`（`crates/infra/src/shell.rs`）— 真执行：`tokio::process` 跑 `sh -c`，超时 kill，输出截断 256 KiB。

内置 deny 列表（不可被配置削弱）：`rm -rf /`、`mkfs`、`dd if=/dev/zero of=/dev/`、`:(){ :|:&`。`exec_shell` 默认**关闭**（`[shell] enabled = false`），启用等于给远端 root，仅限可信内网调试。每次执行记审计（source/method/args/outcome/duration_ms）。

### 1.3.7 传输适配

`Transport` trait（`crates/infra/src/transport/mod.rs:37-49`）是 dispatcher 与物理层唯一边界。4 个适配器：

| 适配器 | 用途 |
|--------|------|
| TcpTransport | 网络/USB 网卡/SSH 隧道 |
| UnixTransport | 本地 CLI、板端进程间 |
| SerialTransport | 调试 UART |
| StubTransport | 测试/dry-run |

所有适配器只解决**帧边界**问题（NDJSON：一行一条 JSON，`\n` 分隔），dispatcher 不知消息来自哪种传输。帧格式契约见 [`contracts/transport/ndjson.md`](../contracts/transport/ndjson.md)。

### 1.3.8 对外入口

同一套 RPC 能力，三种接入形式：

| 入口 | 协议 | 形态 |
|------|------|------|
| `sophonctl` | JSON-RPC | 命令行工具（本地 Unix 或远程 TCP `--host`） |
| `probe-http-gateway` | HTTP/REST | 把 JSON-RPC 包成 HTTP（curl/浏览器） |
| `probe-ws-outbound` | WebSocket | 板子主动外连云端 broker 推送 telemetry |

它们复用 `client::Client`（`crates/client/`，带 id 匹配+超时+重连）。

## 1.4 三种上报模式（共享同一份快照）

硬件状态有三种对外方式，都读同一个 `StateSnapshot`：

1. **周期推送**：守护进程每 `telemetry.interval_secs` 秒主动发 `telemetry` notification（无 id）。适合监控大屏。
2. **按需拉取**：外部发 `get_state`/`get_thermal` 等 Request，立即返回当前快照。适合临时排查。
3. **阈值告警**：状态越限（温度≥阈值、磁盘≥阈值）立即发 `alert` notification。适合触发通知。

## 1.5 关键设计原则速览

1. **采集器可注入 trait**：Mac 上用假 reader 测逻辑，板子上用真实 reader 读硬件，业务代码不变。
2. **策略与执行分离**：shell 的"允不允许"和"怎么跑"拆开，策略可单测。
3. **传输中立**：所有传输只管帧边界，dispatcher 不知物理层。
4. **单一数据源**：拉取和推送读同一份快照，数据不漂移。
5. **best-effort 采集**：单个采集器失败不拖垮整体。
6. **daemon 拆 lib+bin**：`build_test_app` 让 E2E 注入假 infra 但走真实网络栈。

## 1.6 想深入了解

- **对外怎么用**（接口字段/错误码/示例）：[`../contracts/`](../contracts/) — 外部集成看这个。
- **内部怎么实现**（各 crate 设计/依赖/约束）：[`../design/`](../design/) — 维护者看这个。
- **怎么编译部署**：[`../../deploy/`](../../deploy/) — 运维看这个。
- **进程视角**（起几个进程、关系如何）：[`processes.md`](processes.md)。
