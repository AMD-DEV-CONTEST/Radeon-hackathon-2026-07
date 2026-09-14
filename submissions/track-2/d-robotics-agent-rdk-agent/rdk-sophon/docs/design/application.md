# 5. application crate 设计文档

> DDD 层：application（用例编排）。依赖 `shared`、`domain`、`infra`。
> 源码：`crates/application/`

## 5.1 职责

application 编排用例，调 `domain` 领域服务 + `ports` trait：
- **RpcDispatcher**：JSON-RPC 消息分发到对应用例，把 domain 返回的领域类型用 `serde_json::to_value` 转 Value 包进 Response。
- **CollectionOrchestrator**：遍历 `Vec<Box<dyn Collector>>` 组装 `StateSnapshot`。
- **SessionService**：单连接驱动（`run_session` + `Broadcaster`）。
- **AuditLog**：审计日志通道。

## 5.2 模块结构

```
application/src/
├── lib.rs              # pub use 重导出
├── rpc_dispatcher.rs   # RpcDispatcher + DispatchOutcome
├── collection_orchestrator.rs
├── session_service.rs  # run_session + Broadcaster
└── audit.rs            # AuditEntry + AuditLog
```

## 5.3 RpcDispatcher（`rpc_dispatcher.rs`）

```rust
pub struct RpcDispatcher {
    pub orchestrator: Arc<CollectionOrchestrator>,
    pub state: Arc<StateService>,
    pub command_policy: CommandPolicy,
    pub shell_runner: Arc<dyn ShellRunner>,
    pub plugin_runner: Arc<dyn PluginRunner>,
}

impl RpcDispatcher {
    pub fn new(orchestrator, state, command_policy, shell_runner, plugin_runner) -> Self;
    pub async fn dispatch(&self, msg: JsonRpcMessage, source: &str, audit: &AuditLog) -> DispatchOutcome;
}
```

### dispatch 流程（`rpc_dispatcher.rs:39-57`）
1. `Request` → 调 `call(method, params, source, audit)` → 包 `Response`（Ok→result，Err→error）→ `DispatchOutcome::Response`。
2. `Notification` / `Response`（别人的响应）→ `DispatchOutcome::NoReply`。

### 方法表（`rpc_dispatcher.rs:60-89`）
完整方法契约见 [`../contracts/jsonrpc/methods.md`](../contracts/jsonrpc/methods.md)。路由在 `call` 的 `match method`：
- 状态拉取：`get_state`/`get_thermal`/`get_cpu`/`get_memory`/`get_disk`/`get_net`/`get_bpu` → `serde_json::to_value(domain 返回的领域类型)`。
- 控制：`refresh_state`（调 `orchestrator.refresh`，返回 `{ok, ts}`）、`ping`（返回 `{pong, ts}`）。
- shell：`exec_shell`（见下）。
- 动态插件：`plugin.list`/`plugin.invoke`（见下）。
- 未知 → `MethodNotFound`（-32601）。

### exec_shell（`rpc_dispatcher.rs:91-137`）
1. 取参数：必须 `Params::Named` 含 `cmd: String`，否则 `InvalidParams`（-32602）。
2. `command_policy.check(cmdline)`：先过 enabled/deny 纯策略（domain）。
3. `shell_runner.run(cmdline, timeout)`：执行（infra）。
4. 审计：记录 `source`、`method="exec_shell"`、`args`（截前 200 字符）、`outcome`（`ok exit=0`/`nonzero exit=N`/`error: ...`）、`duration_ms`。
5. 成功 → `{exit, stdout, stderr}`；超时 → `Timeout`（-32003）；其它 shell 错误 → `ExecError`（-32000）。

### 动态插件（`rpc_dispatcher.rs:165-244`）
`plugin.list` 委托 `PluginRunner::list`；`plugin.invoke` 只接受 `plugin: String` 与 `args: [String]`，不将参数拼接成 shell。调用结果与 shell 输出一致为 `{exit, stdout, stderr}`，每次成功、非零退出或失败都写审计 `method="plugin.invoke"`。

## 5.4 CollectionOrchestrator（`collection_orchestrator.rs`）

```rust
pub struct CollectionOrchestrator {
    collectors: Vec<Box<dyn Collector>>,
    state: Arc<StateService>,
}
```
- `new(collectors, state)`。
- `collect_once()`：遍历各 Collector，`collect().await` 返回片段则 `merge_fragment` 组装，stamp 时间戳，原子 `state.replace`。某 Collector 返回 `None` 被跳过，不影响其他。
- `current_snapshot() -> StateSnapshot`：读当前快照副本。
- `refresh(audit, source) -> Option<String>`：立即采集一次并返回时间戳。

## 5.5 SessionService（`session_service.rs`）

### Broadcaster（`session_service.rs:14-33`）
进程级 telemetry/alert 广播总线。`new(capacity)`（默认 256）、`subscribe() -> Receiver`、`publish(msg)`。

### run_session（`session_service.rs`）
驱动一条连接直到 EOF 或致命错误。`tokio::select!` 并发：
- **广播分支**：`bcast_rx.recv()` 收到 notification → `transport.send` 转发给对端。`Lagged` 时重订阅不静默丢。`Closed` 时退出。
- **读分支**：请求被后台 dispatch；请求执行期间仍监听广播和 EOF。EOF/读错误会 abort 当前任务，从而 drop `kill_on_drop` 的插件进程；同连接的并行 request 返回 `InvalidRequest`。

慢 shell 或插件不会阻塞广播转发，且客户端 Ctrl-C 不会遗留长驻插件进程。

## 5.6 AuditLog（`audit.rs`）

`AuditLog` 持 `mpsc::UnboundedSender<AuditEntry>`，daemon 装配时建后台任务消费，写 `tracing::info!(target: "audit", ...)`。
- `AuditEntry { ts, source, method, args, outcome, duration_ms }`。
- `record(e)` best-effort（sink 关闭丢弃）。`now_ts()` 返回 RFC3339 秒精度 UTC。

## 5.7 依赖

内部：`shared`、`domain`、`infra`。外部：`tokio`/`tracing`/`serde`/`serde_json`/`thiserror`/`async-trait`/`chrono`。

## 5.8 设计约束

- application **不得**依赖 `daemon`（单向向下）。
- dispatcher 是 wire 格式转换的**唯一位置**（domain 返回领域类型，application 转 Value）。
- `run_session` **不得**让慢命令阻塞广播转发。

## 5.9 新增 RPC 方法

1. 在 `rpc_dispatcher.rs::call` 的 `match` 加分支。
2. 若需新参数/返回结构，在 `shared/protocol` 定义类型。
3. 同步更新 `../contracts/jsonrpc/methods.md`（params/result/示例）。
4. 若有 HTTP 网关入口，同步更新 `../contracts/http/routes.md` + `api-http/src/routes.rs`。
