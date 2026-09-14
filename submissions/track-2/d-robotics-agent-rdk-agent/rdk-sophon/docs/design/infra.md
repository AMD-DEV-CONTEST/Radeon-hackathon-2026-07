# 3. infra crate 设计文档

> DDD 层：infra（基础设施）。依赖 `shared`。
> 源码：`crates/infra/`

## 3.1 职责

infra 实现两件事：
1. **传输层**：`transport` 子模块——`Transport` trait + TCP/Unix/Serial/Stub 适配器 + NDJSON 帧编解码。
2. **真实基础设施**：读 `/sys`、`/proc`、调 `hrut_*` 工具、`statvfs` FFI、用 `tokio::process` 执行 `sh -c`。

所有实现都是 best-effort：单个读取失败返回 `None`/`Err`，不 panic，不拖垮 daemon。

## 3.2 模块结构

```
infra/src/
├── lib.rs              # 顶层 pub use + pub mod transport
├── transport/
│   ├── mod.rs          # Transport trait + TransportError
│   ├── framed.rs       # FramedReader/FramedWriter（NDJSON）
│   ├── tcp.rs          # TcpTransport
│   ├── unix.rs         # UnixTransport
│   ├── serial.rs       # SerialTransport
│   └── stub.rs         # StubTransport（测试/dry-run）
├── sysfs.rs            # RealSysfsReader
├── proc.rs             # RealProcReader
├── hrut.rs             # RealHrutGateway
├── statvfs.rs          # statvfs FFI（仅 Linux）
├── shell.rs            # RealShellRunner
└── plugin.rs           # RealPluginRunner / DisabledPluginRunner
```

## 3.3 传输层（`transport/`）

### Transport trait（`transport/mod.rs:37-49`）
```rust
#[async_trait]
pub trait Transport: Send {
    fn label(&self) -> &str;
    async fn recv(&mut self) -> Result<Option<JsonRpcMessage>, TransportError>;
    async fn send(&mut self, msg: &JsonRpcMessage) -> Result<(), TransportError>;
    async fn closed(&self) -> bool { false }
}
```
dispatcher 与物理层唯一边界。适配器只解决**帧边界**问题，把完整 `JsonRpcMessage` 交给 dispatcher。

### NDJSON 帧（`transport/framed.rs`）
一行一条 JSON，`\n` 分隔。完整契约见 [`../contracts/transport/ndjson.md`](../contracts/transport/ndjson.md)。
- 写：序列化 + 追加 `\n` + `write_all` + `flush`。
- 读：`read_until(b'\n')`，`trim_eol` 剥 `\n`/`\r`，空行跳过，EOF 无换行也解析最后一条。
- 超长（> `MAX_MESSAGE_BYTES`）返回 `FrameError::TooLong`。

### 适配器
| 类型 | 构造 | label | 说明 |
|------|------|------|------|
| `TcpTransport` | `new(stream, peer)` | `tcp:{peer}` | `into_split` + FramedReader/Writer |
| `UnixTransport` | `new(stream, label)` | 传入值 | 同上 |
| `SerialTransport` | `open(path, baud)` | `serial:{path}@{baud}` | 阻塞 `serialport`，读在专用线程，经 `tokio::mpsc` 桥接；默认 8N1，读超时 250ms |
| `StubTransport` | `pair() -> (a, b)` | `stub:a`/`stub:b` | 内存通道，仅测试/dry-run |

serial 适配器**复用** NDJSON 帧逻辑（与 TCP 同），但因为是阻塞 API，读放在 `std::thread` 线程里按 `\n` 切行、`trim_eol`、空行跳过、超长报错，结果通过 channel 喂回 async 侧。

## 3.4 真实基础设施（顶层文件）

### RealSysfsReader（`sysfs.rs`）
实现 `ports::SysfsReader`。`std::fs::read_dir`/`read_to_string`，sysfs 目录小且读快，直接同步读。文件缺失返回 `None`。

### RealProcReader（`proc.rs`）
实现 `ports::ProcReader`。`std::fs::read_to_string`。

### RealHrutGateway（`hrut.rs`）
实现 `ports::HrutGateway`。先试 `--help` 确认工具存在，再跑无参版本拿 stdout；`--help` 失败回退无参。工具不存在返回 `None`，daemon 在非 RDK 板自动省略 `bpu` 字段。

### statvfs（`statvfs.rs`）
`statvfs_of(path: &str) -> Option<StatvfsResult>`。**仅 Linux** 有真实实现（依赖 `libc` crate），非 Linux 返回 `None`。`StatvfsResult { block_size, blocks, blocks_free, blocks_avail }`。

### RealShellRunner（`shell.rs`）
实现 `ports::ShellRunner`。用 `tokio::process::Command` 跑 `sh -c`，`tokio::join!` 并发读 stdout/stderr（防管道填满死锁），`tokio::time::timeout` 控超时，`kill_on_drop` 超时杀进程。输出按 `max_output_bytes`（默认 256 KiB）截断。
- `new()` 默认上限。
- `with_max_output(bytes)` 自定义。

**策略与执行分离**：deny/timeout 值的判定在 `domain::CommandPolicy`（纯逻辑），本结构只负责"按给定 timeout 执行给定 cmd"。

### RealPluginRunner（`plugin.rs`）
实现 `ports::PluginRunner`。每次 list/invoke 扫描配置的 `<dir>/<id>/plugin.toml`，所以增删插件无需重启。manifest 只接受 `api_version=1`、安全的 CLI id 与非空 `entrypoint`。执行时用 `Command::new(entrypoint[0]).args(entrypoint[1..]).args(user_args)`，不使用 shell；stdout/stderr 并发读取且每路截断 256 KiB。`timeout_secs=0` 不设超时，进程在调用连接关闭而任务被 abort 时由 `kill_on_drop` 回收。

`DisabledPluginRunner` 在配置关闭时返回空清单/不存在，不能回退到 raw shell。

## 3.5 依赖

内部：`shared`。外部：`tokio`/`tracing`/`anyhow`/`async-trait`/`thiserror`/`serde_json`/`serialport`。Linux 下额外 `libc`。

## 3.6 设计约束

- infra **不得**依赖 `domain`/`application`/`daemon`（单向向下）。
- 传输适配器**不得**引入业务语义（只解决帧边界）。
- 真实硬件读取**不得**在 trait 实现里 panic（best-effort）。
