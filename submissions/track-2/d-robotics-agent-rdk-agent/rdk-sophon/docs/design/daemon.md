# 7. daemon crate 设计文档

> DDD 层：bootstrap（装配）。依赖 `shared`/`infra`/`domain`/`application`。
> 源码：`crates/daemon/`

## 7.1 职责

daemon 是依赖注入装配与运行时编排入口。同时有 `[lib]` 与 `[[bin]]`：
- **lib**：暴露 `build_production_app`/`build_test_app`，供 main 与 E2E 测试装配。
- **bin**（`probe-daemon`）：CLI 参数解析 + 配置加载 + tracing 初始化 + 调 lib 装配 + 起监听 + 优雅退出。

## 7.2 模块结构

```
daemon/src/
├── lib.rs        # pub use + pub mod config
├── config.rs     # Config（TOML 反序列化）
├── bootstrap.rs  # App/AppHandles + build_*_app + accept_*_loop + 采集循环
└── main.rs       # bin 入口（clap + 装配 + 监听 + ctrl_c）
```

## 7.3 App 与 AppHandles（`bootstrap.rs`）

```rust
pub struct App {
    pub dispatcher: Arc<RpcDispatcher>,
    pub state: Arc<StateService>,
    pub orchestrator: Arc<CollectionOrchestrator>,
    pub audit: AuditLog,
    pub broadcaster: Broadcaster,
    pub cancel: CancellationToken,
}
pub struct AppHandles {
    pub app: Arc<App>,
    pub collect_handle: JoinHandle<()>,
    pub audit_handle: JoinHandle<()>,
}
```

## 7.4 装配函数（`bootstrap.rs`）

| 函数 | 注入 | 用途 |
|------|------|------|
| `build_production_app(cfg)` | 真实 `RealSysfsReader`/`RealProcReader`/`RealHrutGateway`/`RealShellRunner`/`RealPluginRunner` | 生产（main） |
| `build_test_app(cfg, sysfs, proc_r, hrut, shell_runner)` | 假 infra（trait object） | E2E（Mac 上注入假 /proc /sys） |
| `build_test_app_with_collectors(cfg, collectors, shell_runner)` | 直接注入 Collector 列表 | Orchestrator 单测 |

三个都走内部 `build_app`：
1. 建 `StateService`（`Arc<RwLock<StateSnapshot>>`）。
2. 建 `CollectionOrchestrator`（注入 Collector 列表）。
3. `CommandPolicy::from_config`（内置 deny 不可削弱）。
4. 按 `[plugins].enabled` 注入 `RealPluginRunner` 或 `DisabledPluginRunner`，再建 `RpcDispatcher`（注入 orchestrator/state/policy/shell_runner/plugin_runner）。
5. 审计 mpsc sink + 后台写任务（`tracing target: "audit"`）。
6. `Broadcaster::new(256)`。
7. spawn 采集循环。

## 7.5 采集/告警/telemetry 循环（`bootstrap.rs:spawn_collect_loop`）

```
loop {
    select! {
        _ = cancel.cancelled() => break,
        _ = ticker.tick() => {
            orchestrator.collect_once();          // 锁外 collect 再原子 replace
            snap = state.get_state();
            rules = AlertService::evaluate(&snap, &thresholds);  // 纯函数
            for rule in rules { publish(alert notification) }
            if push_enabled { publish(TelemetryService::build_notification(&snap)) }
        }
    }
}
```
- 初始采集一次（让首个 `get_state` 非空）。
- `interval = telemetry.interval_secs.max(1)`；`MissedTickBehavior::Skip`；跳首 tick。
- `push_enabled = interval_secs > 0`（0 = 仅拉取）。
- `CancellationToken` 贯穿，优雅退出。

## 7.6 accept 循环（`bootstrap.rs`）

- `accept_tcp_loop(listener, app)`：`select!` cancel / accept → 建 `TcpTransport` → spawn `run_session`。accept 失败退避 200ms。
- `accept_unix_loop(listener, app)`：同上用 `UnixTransport`（label `"unix"`）。
- 串口（main 里）：单连接，直接 `spawn(run_session)`，不走 accept 循环。

## 7.7 main（`main.rs`）

1. `clap::Parser` 解析 `--config`/`--tcp-bind`/`--unix-path`/`--dry-run`。
2. `load_config`：`Config::load(path)` 失败回退 `Config::default()`（**配置缺失不阻塞启动**，bind 0.0.0.0:7777 + unix socket，shell 默认禁用）。
3. `init_tracing`：`EnvFilter`（`RUST_LOG` 优先，否则用 `log.level`）。
4. `build_production_app(cfg)`。
5. `--dry-run` 则不起监听，等 ctrl_c。
6. TCP/Unix 监听（按 config + CLI 覆盖），spawn accept 循环。
7. Serial（按 config）。
8. `ctrl_c` → `cancel.cancel()` → 等 accept 循环退出。

## 7.8 Config（`config.rs`）

TOML 反序列化，所有 section `#[serde(default)]`。完整字段表见 [`../contracts/cli/config.md`](../contracts/cli/config.md)。

## 7.9 设计约束

- daemon `[lib]` 必须暴露 `build_test_app`，让 E2E 注入假 infra。
- `App` 字段全 `pub`（E2E 要拿 `orchestrator`/`broadcaster`/`cancel`）。
- main **不得**含业务逻辑（只装配 + 编排生命周期）。
- 采集循环**锁外 collect 再原子 replace**，不退化。
