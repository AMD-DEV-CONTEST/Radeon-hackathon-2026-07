# 2. shared crate 设计文档

> DDD 层：shared（底座）。无内部依赖。
> 源码：`crates/shared/`

## 2.1 职责

shared 是最底座，包含两个子模块：
- `protocol`：JSON-RPC 2.0 信封 + `StateSnapshot` 状态快照数据模型。**无 IO，无 tokio**。
- `ports`：领域对外的纯 trait 抽象（`Collector`/`SysfsReader`/`ProcReader`/`HrutGateway`/`ShellRunner`）。

daemon、`api-cli`、`api-http`、`api-ws` 都依赖 shared，共享同一套协议与端口定义。

## 2.2 模块结构

```
shared/src/
├── lib.rs              # 顶层 pub use 重导出
├── protocol/
│   ├── mod.rs          # 常量 MAX_MESSAGE_BYTES / JSONRPC_VERSION
│   ├── message.rs      # JsonRpcMessage 信封 + ErrorCode
│   ├── snapshot.rs     # StateSnapshot + 各片段 + StateSnapshotFragment
│   └── error.rs        # ProtocolError
└── ports/
    ├── mod.rs
    ├── traits.rs       # 5 个端口 trait + ShellOutput
    └── error.rs        # PortError / ShellError
```

模块根文件只做 `pub mod` 与 `pub use`，不含业务逻辑。

## 2.3 顶层导出（`lib.rs:13-16`）

便捷重导出，下游可直接 `use shared::JsonRpcMessage`：
- 协议类型：`JsonRpcMessage`、`Request`、`Response`、`ResponsePayload`、`Notification`、`Error`、`ErrorCode`、`Id`、`Params`、`StateSnapshot`、`StateSnapshotFragment`、`Thermal`、`ThermalZone`、`CpuInfo`、`MemoryInfo`、`DiskInfo`、`NetInfo`、`BpuInfo`、`PowerInfo`、`ProtocolError`、`MAX_MESSAGE_BYTES`、`JSONRPC_VERSION`。
- 端口类型：`Collector`、`SysfsReader`、`ProcReader`、`HrutGateway`、`ShellRunner`、`ShellOutput`、`PortError`、`ShellError`。

## 2.4 protocol 子模块

### 信封结构（`protocol/message.rs`）
- `JsonRpcMessage` 是 `#[serde(untagged)]` 三选一：`Request | Response | Notification`。
- `Request { jsonrpc, id, method, params? }`；`params` 为 `None` 时不序列化。
- `Response { jsonrpc, id }` + `#[serde(flatten)] payload`，顶层即 `{jsonrpc, id, result|error}`。
- `Notification { jsonrpc, method, params? }`，**无 `id`**（fire-and-forget）。
- `Id`：`Num(i64) | Str(String) | Null`，从不发送 `null` id。
- `Params`：`Named(Map) | Positional(Vec)`，主用 Named。
- `Error { code: i32, message: String, data? }`；`data` 为 `None` 时不序列化。

### 错误码（`protocol/message.rs:90-105`）
`ErrorCode` 为 `#[repr(i32)]`。完整码表见 [`../contracts/jsonrpc/errors.md`](../contracts/jsonrpc/errors.md)。

### 数据模型（`protocol/snapshot.rs`）
`StateSnapshot` 及各片段字段表见 [`../contracts/jsonrpc/data-model.md`](../contracts/jsonrpc/data-model.md)。

### 关键常量
- `MAX_MESSAGE_BYTES = 4 * 1024 * 1024`（4 MiB，`protocol/mod.rs:19`）：单消息最大字节数，传输层据此防内存耗尽。
- `JSONRPC_VERSION = "2.0"`（`protocol/mod.rs:22`）。

## 2.5 ports 子模块（`ports/traits.rs`）

纯 trait，零实现。供 infra（真实实现）与 testkit（假实现）实现，由 domain/application 注入。

| trait | 签名要点 | 用途 |
|------|------|------|
| `Collector` | `fn name(&self) -> &'static str; async fn collect(&self) -> Option<StateSnapshotFragment>` | 单个硬件采集器 |
| `SysfsReader` | `async fn read_dir/read_first_line/read_int` | 读 `/sys` |
| `ProcReader` | `async fn read` | 读 `/proc` |
| `HrutGateway` | `async fn run(tool: &str) -> Option<String>` | 调 `hrut_*` 工具 |
| `ShellRunner` | `async fn run(cmd, timeout) -> Result<ShellOutput, ShellError>` | 执行 `sh -c`（执行，非策略） |

`ShellOutput { exit: Option<i32>, stdout: String, stderr: String }`（`ports/traits.rs`）。

错误类型：`PortError`（硬件读取抽象）、`ShellError`（`Timeout{secs}`/`Spawn`/`Wait`，`ports/error.rs`）。

## 2.6 依赖

无内部依赖。外部：`serde`/`serde_json`/`thiserror`/`chrono`/`uuid`/`async-trait`。

## 2.7 设计约束

- shared **不得**依赖任何内部 crate（保持底座纯净）。
- shared **不得**依赖 `tokio` 或任何 IO 库（纯数据 + trait）。
- `MAX_MESSAGE_BYTES` 放 shared 而非 infra，是因为它约束的是协议消息大小（跨传输通用），不是某传输的实现细节。
