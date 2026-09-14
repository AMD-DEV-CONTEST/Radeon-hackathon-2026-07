# 8. api 入口 + testkit 设计文档

> api-cli / api-http / api-ws（DDD 层：api）+ testkit（test）。
> 源码：`crates/api-cli/`、`crates/api-http/`、`crates/api-ws/`、`crates/testkit/`

## 8.1 api-cli（sophonctl）

本地或远程 CLI，复用 `client::Client`，与 daemon 走同一套 NDJSON 协议。
- 本地：`ClientBuilder::unix(socket)`。
- 远程：`--host ip:port` → `ClientBuilder::tcp(host)`。
- 完整子命令契约见 [`../contracts/cli/sophonctl.md`](../contracts/cli/sophonctl.md)。

## 8.2 api-http（probe-http-gateway）

REST 网关二进制，把 daemon 的 JSON-RPC 包成 HTTP。本地连 daemon Unix socket（作为 `client`），对外暴露 REST。
- `axum` 路由，每路由调 `Client::call`，result 包成 HTTP JSON。
- 错误码 → HTTP 状态码映射见 [`../contracts/http/errors.md`](../contracts/http/errors.md)。
- 完整路由表见 [`../contracts/http/routes.md`](../contracts/http/routes.md)。

### 模块结构
```
api-http/src/
├── main.rs     # clap + axum::serve
├── routes.rs   # 路由表 + handler
└── error.rs    # HttpError + ClientError→HTTP 映射
```

## 8.3 api-ws（probe-ws-outbound）

WebSocket 出站二进制。板子主动外连云端 broker，把 daemon 的 telemetry/alert notification 转发到云端。
- 作为本地 daemon 的 Unix 客户端连进去（`UnixStream::connect` + `UnixTransport`），用 `run_session` 已有的 broadcast 转发路径收 notification。
- **不用 `client::Client`**（要收 notification 而非 request/response），直接 `transport.recv`。
- 收到 notification → `codec::encode` 成 WS 文本帧 → 通过 mpsc 喂给 WS 写任务。
- WS 读端处理 Ping/Pong/Close/控制帧；云端下发的指令当前忽略（未来扩展）。
- 重连：`run_with_reconnect` 指数退避（`backoff_start` 翻倍，封顶 `backoff_max`），正常断立即重连。
- 完整传输契约见 [`../contracts/transport/ws-outbound.md`](../contracts/transport/ws-outbound.md)。

### 模块结构
```
api-ws/src/
├── main.rs       # clap + run_with_reconnect
├── session.rs    # WS 会话生命周期 + daemon→WS 转发
├── reconnect.rs  # 指数退避重连
└── codec.rs      # JsonRpcMessage ↔ WS 文本帧
```

## 8.4 testkit

测试公共工具，供集成/E2E 注入假 infra。

### 模块结构
```
testkit/src/
├── lib.rs          # pub mod common
└── common/
    ├── mod.rs      # pub use
    ├── fakes.rs    # FakeSysfsReader/FakeProcReader/FakeHrutGateway/FakeShellRunner/FakeCollector
    └── fixtures.rs # make_fake_sysfs/proc/hrut + make_thermal_snap
```

### Fake 实现
- `FakeSysfsReader`：`HashMap<文件路径, 内容>` + `HashMap<目录路径, Vec<条目名>>`。
- `FakeProcReader`：`HashMap<路径, 内容>`。
- `FakeHrutGateway`：`HashMap<工具名, stdout>`。
- `FakeShellRunner`：`HashMap<cmd, ShellOutput>`；`timeout_on_unknown` 模拟超时；`with(cmd, out)` builder。
- `FakeCollector`：返回固定 `StateSnapshotFragment`。

### fixtures
- `make_fake_sysfs()`：典型板端 `/sys`（两个 thermal zone + cpufreq policy0）。
- `make_fake_proc()`：典型 `/proc`（loadavg/meminfo/net/dev/mounts/uptime/stat/fib_trie）。
- `make_fake_hrut()`：典型 hrut 输出（bpuinfo 30%/1500 + sensors temp 55）。
- `make_thermal_snap(temp)`：构造超阈值 thermal 快照供 alert 测试。

### 测试文件
- 集成测试在各 crate 的 `tests/`（如 `crates/daemon/tests/`、`crates/client/tests/`）。
- E2E 测试在 `crates/testkit/tests/`（`tcp_e2e`/`unix_e2e`/`deny_timeout_e2e`）。
- 详细测试规范见 `CLAUDE.md`「测试三层」。

## 8.5 设计约束

- api 入口**不得**依赖 `application`/`domain`/`infra` 的内部细节（只依赖 `client` + `shared`，api-ws 额外依赖 `infra` 的 `UnixTransport`）。
- testkit 是 **dev/test-only**，不进生产二进制。
- 假实现的 trait 必须与真实 infra 行为一致（语义对齐），否则测试无效。
