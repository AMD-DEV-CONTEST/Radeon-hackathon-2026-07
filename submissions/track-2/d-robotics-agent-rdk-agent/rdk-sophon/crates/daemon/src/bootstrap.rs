//! bootstrap：DI 装配 + 监听器/采集循环/审计/广播编排。
//! 从原 main.rs 的 178 行装配逻辑拆出。App 持有所有运行时组件与 cancel token。

use std::sync::Arc;

use anyhow::Result;
use application::{
    run_session, AuditEntry, AuditLog, Broadcaster, CollectionOrchestrator, RpcDispatcher,
};
use domain::collectors::{
    BpuCollector, CpuCollector, DiskCollector, MemoryCollector, NetCollector, ThermalCollector,
};
use domain::{AlertService, AlertThresholds, CommandPolicy, StateService, TelemetryService};
use infra::Transport;
use infra::{RealHrutGateway, RealProcReader, RealShellRunner, RealSysfsReader};
use shared::ports::{Collector, HrutGateway, PluginRunner, ProcReader, ShellRunner, SysfsReader};
use shared::protocol::{JsonRpcMessage, Params, StateSnapshot};
use tokio::sync::RwLock;
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

use crate::config::Config;

/// 装配好的应用。持有共享状态与分发器，供监听器 accept 后驱动 session。
pub struct App {
    pub dispatcher: Arc<RpcDispatcher>,
    pub state: Arc<StateService>,
    pub orchestrator: Arc<CollectionOrchestrator>,
    pub audit: AuditLog,
    pub broadcaster: Broadcaster,
    pub cancel: CancellationToken,
}

/// 装配产物：App 本体 + 已 spawn 的后台任务句柄。
pub struct AppHandles {
    pub app: Arc<App>,
    pub collect_handle: JoinHandle<()>,
    pub audit_handle: JoinHandle<()>,
}

/// 生产装配：用真实 infra 实现。main.rs 调用本函数。
pub fn build_production_app(cfg: &Config) -> Result<AppHandles> {
    // 真实 infra：读真实 /sys /proc，调真实 hrut，真实 sh 执行。
    let sysfs: Arc<dyn SysfsReader> = Arc::new(RealSysfsReader::new());
    let proc_r: Arc<dyn ProcReader> = Arc::new(RealProcReader::new());
    let hrut: Arc<dyn HrutGateway> = Arc::new(RealHrutGateway::new());

    let collectors: Vec<Box<dyn Collector>> = vec![
        Box::new(ThermalCollector::new(Arc::clone(&sysfs))),
        Box::new(CpuCollector::new(Arc::clone(&proc_r), Arc::clone(&sysfs))),
        Box::new(MemoryCollector::new(Arc::clone(&proc_r))),
        Box::new(DiskCollector::new(Arc::clone(&proc_r))),
        Box::new(NetCollector::new(Arc::clone(&proc_r), Arc::clone(&sysfs))),
        Box::new(BpuCollector::new(Arc::clone(&hrut))),
    ];
    let shell_runner: Arc<dyn ShellRunner> = Arc::new(RealShellRunner::new());
    let plugin_runner = plugin_runner_for_config(cfg);
    build_app(cfg, collectors, shell_runner, plugin_runner)
}

/// 测试装配：用假 infra。E2E 测试调用，注入假 /proc /sys 数据。
pub fn build_test_app(
    cfg: &Config,
    sysfs: Arc<dyn SysfsReader>,
    proc_r: Arc<dyn ProcReader>,
    hrut: Arc<dyn HrutGateway>,
    shell_runner: Arc<dyn ShellRunner>,
) -> Result<AppHandles> {
    let collectors: Vec<Box<dyn Collector>> = vec![
        Box::new(ThermalCollector::new(Arc::clone(&sysfs))),
        Box::new(CpuCollector::new(Arc::clone(&proc_r), Arc::clone(&sysfs))),
        Box::new(MemoryCollector::new(Arc::clone(&proc_r))),
        Box::new(DiskCollector::new(Arc::clone(&proc_r))),
        Box::new(NetCollector::new(Arc::clone(&proc_r), Arc::clone(&sysfs))),
        Box::new(BpuCollector::new(Arc::clone(&hrut))),
    ];
    let plugin_runner = plugin_runner_for_config(cfg);
    build_app(cfg, collectors, shell_runner, plugin_runner)
}

/// 测试装配：直接注入 Collector 列表（跳过 sysfs/proc/hrut 组装），用于 Orchestrator 单测。
pub fn build_test_app_with_collectors(
    cfg: &Config,
    collectors: Vec<Box<dyn Collector>>,
    shell_runner: Arc<dyn ShellRunner>,
) -> Result<AppHandles> {
    let plugin_runner = plugin_runner_for_config(cfg);
    build_app(cfg, collectors, shell_runner, plugin_runner)
}

fn build_app(
    cfg: &Config,
    collectors: Vec<Box<dyn Collector>>,
    shell_runner: Arc<dyn ShellRunner>,
    plugin_runner: Arc<dyn PluginRunner>,
) -> Result<AppHandles> {
    // 共享状态：StateSnapshot 读写锁。
    let snapshot: Arc<RwLock<StateSnapshot>> = Arc::new(RwLock::new(StateSnapshot::empty()));
    let state = Arc::new(StateService::new(Arc::clone(&snapshot)));

    // Orchestrator：采集编排。
    let orchestrator = Arc::new(CollectionOrchestrator::new(collectors, Arc::clone(&state)));

    // shell 策略：从配置构造（内置 deny 列表不可削弱）。
    let policy = CommandPolicy::from_config(
        cfg.shell.enabled,
        cfg.shell.timeout_secs,
        &cfg.shell.deny_patterns,
    );

    // 分发器。
    let dispatcher = Arc::new(RpcDispatcher::new(
        Arc::clone(&orchestrator),
        Arc::clone(&state),
        policy,
        Arc::clone(&shell_runner),
        plugin_runner,
    ));

    // 审计：mpsc sink + 后台写任务。
    let (audit_tx, mut audit_rx) = tokio::sync::mpsc::unbounded_channel::<AuditEntry>();
    let audit = AuditLog::new(audit_tx);
    let audit_handle = tokio::spawn(async move {
        while let Some(entry) = audit_rx.recv().await {
            tracing::info!(
                target: "audit",
                source = %entry.source,
                method = %entry.method,
                args = %entry.args,
                outcome = %entry.outcome,
                duration_ms = entry.duration_ms,
                "audit"
            );
        }
    });

    // 广播总线。
    let broadcaster = Broadcaster::new(256);

    // 初始采集一次，让首个 get_state 非空。
    let orchestrator_init = Arc::clone(&orchestrator);
    // 注意：build_app 在同步上下文调用，但 Orchestrator 是 async。我们把初始采集推迟到 spawn 的任务里。

    let cancel = CancellationToken::new();

    let app = Arc::new(App {
        dispatcher,
        state: Arc::clone(&state),
        orchestrator: Arc::clone(&orchestrator),
        audit: audit.clone(),
        broadcaster: broadcaster.clone(),
        cancel: cancel.clone(),
    });

    // 采集循环：周期采集 → 告警评估 → 写快照 → telemetry 推送。
    let collect_handle = spawn_collect_loop(
        Arc::clone(&orchestrator_init),
        Arc::clone(&state),
        broadcaster.clone(),
        cfg.clone(),
        cancel.clone(),
    );

    Ok(AppHandles {
        app,
        collect_handle,
        audit_handle,
    })
}

/// 按配置选择真实目录扫描器或禁用实现，生产与测试装配使用完全相同的开关语义。
fn plugin_runner_for_config(cfg: &Config) -> Arc<dyn PluginRunner> {
    if cfg.plugins.enabled {
        Arc::new(infra::RealPluginRunner::new(&cfg.plugins.dir))
    } else {
        Arc::new(infra::DisabledPluginRunner)
    }
}

/// spawn 采集/告警/telemetry 循环。
fn spawn_collect_loop(
    orchestrator: Arc<CollectionOrchestrator>,
    state: Arc<StateService>,
    broadcaster: Broadcaster,
    cfg: Config,
    cancel: CancellationToken,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        // 初始采集：让首个 get_state 有数据。
        orchestrator.collect_once().await;

        let interval = cfg.telemetry.interval_secs.max(1);
        let mut ticker = tokio::time::interval(std::time::Duration::from_secs(interval));
        ticker.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Skip);
        // 跳过首 tick（已做初始采集）。
        ticker.tick().await;

        let thresholds = AlertThresholds {
            temp_c: cfg.alerts.temp_c,
            disk_usage_pct: cfg.alerts.disk_usage_pct,
        };
        let push_enabled = cfg.telemetry.interval_secs > 0;

        loop {
            tokio::select! {
                _ = cancel.cancelled() => break,
                _ = ticker.tick() => {
                    // 采集 → 写快照（Orchestrator 锁外 collect 再原子替换）。
                    orchestrator.collect_once().await;
                    let snap = state.get_state().await;
                    // 告警评估 → publish alert notification。
                    let rules = AlertService::evaluate(&snap, &thresholds);
                    for rule in rules {
                        let params = Params::Named(alert_params(&rule));
                        broadcaster.publish(JsonRpcMessage::new_notification("alert", Some(params)));
                    }
                    // 周期 telemetry 推送。
                    if push_enabled {
                        broadcaster.publish(TelemetryService::build_notification(&snap));
                    }
                }
            }
        }
    })
}

/// 把一条 AlertRule 序列化成 JSON-RPC named params。
fn alert_params(rule: &domain::AlertRule) -> serde_json::Map<String, serde_json::Value> {
    let (kind, current, threshold) = match rule.kind {
        domain::AlertKind::Thermal => ("thermal", rule.current, rule.threshold),
        domain::AlertKind::Disk => ("disk", rule.current, rule.threshold),
    };
    let mut m = serde_json::Map::new();
    m.insert("kind".into(), serde_json::Value::String(kind.into()));
    m.insert(
        "target".into(),
        serde_json::Value::String(rule.target.clone()),
    );
    m.insert("current".into(), serde_json::json!(current));
    m.insert("threshold".into(), serde_json::json!(threshold));
    m
}

/// TCP accept 循环。监听器与 App 注入，每连接 spawn run_session。
pub async fn accept_tcp_loop(listener: tokio::net::TcpListener, app: Arc<App>) -> Result<()> {
    let local = listener
        .local_addr()
        .ok()
        .map(|a| a.to_string())
        .unwrap_or_default();
    tracing::info!(%local, "tcp listener up");
    loop {
        tokio::select! {
            _ = app.cancel.cancelled() => break,
            res = listener.accept() => {
                match res {
                    Ok((stream, peer)) => {
                        let t = infra::TcpTransport::new(stream, peer);
                        let label = t.label().to_string();
                        let dispatcher = Arc::clone(&app.dispatcher);
                        let audit = app.audit.clone();
                        let rx = app.broadcaster.subscribe();
                        tokio::spawn(run_session(label, Box::new(t), dispatcher, audit, rx));
                    }
                    Err(e) => {
                        tracing::warn!(error=%e, "tcp accept failed");
                        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                    }
                }
            }
        }
    }
    Ok(())
}

/// Unix socket accept 循环。
pub async fn accept_unix_loop(listener: tokio::net::UnixListener, app: Arc<App>) -> Result<()> {
    loop {
        tokio::select! {
            _ = app.cancel.cancelled() => break,
            res = listener.accept() => {
                match res {
                    Ok((stream, _peer)) => {
                        let t = infra::UnixTransport::new(stream, "unix");
                        let label = t.label().to_string();
                        let dispatcher = Arc::clone(&app.dispatcher);
                        let audit = app.audit.clone();
                        let rx = app.broadcaster.subscribe();
                        tokio::spawn(run_session(label, Box::new(t), dispatcher, audit, rx));
                    }
                    Err(e) => {
                        tracing::warn!(error=%e, "unix accept failed");
                        tokio::time::sleep(std::time::Duration::from_millis(200)).await;
                    }
                }
            }
        }
    }
    Ok(())
}
