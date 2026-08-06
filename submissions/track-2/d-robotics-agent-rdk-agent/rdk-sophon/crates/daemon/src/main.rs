//! probe-daemon 入口（bootstrap 层 main）：只做 CLI 参数解析、配置加载、
//! tracing 初始化、调用 lib::build_production_app 装配、启动监听器、优雅退出。
//! 所有运行时逻辑在 daemon::bootstrap（lib）里。

use std::sync::Arc;

use anyhow::{Context, Result};
use clap::Parser;
use daemon::{build_production_app, accept_tcp_loop, accept_unix_loop, AppHandles};
use tracing_subscriber::{fmt, layer::SubscriberExt, util::SubscriberInitExt, EnvFilter};
use infra::Transport;

#[derive(Debug, Parser)]
#[command(name = "probe-daemon", about = "RDK 板端硬件探针守护进程")]
struct Args {
    /// 配置文件路径。
    #[arg(short, long, default_value = "/etc/probe-daemon/config.toml")]
    config: String,
    /// 覆盖 TCP 绑定地址。
    #[arg(long)]
    tcp_bind: Option<String>,
    /// 覆盖 Unix socket 路径。
    #[arg(long)]
    unix_path: Option<String>,
    /// 临时启用 raw shell（覆盖 config 的 [shell].enabled）。危险：允许远程执行任意命令，仅调试用，重启不带本参数即关闭。
    #[arg(long)]
    shell_enabled: bool,
    /// 覆盖 shell 命令超时秒数（配合 --shell-enabled 用）。
    #[arg(long)]
    shell_timeout: Option<u64>,
    /// dry-run：只打日志不起监听（开发机调试用）。
    #[arg(long)]
    dry_run: bool,
}

#[tokio::main]
async fn main() -> Result<()> {
    let args = Args::parse();
    let mut cfg = load_config(&args);
    // CLI 覆盖 shell 配置（临时启用，不改 config 文件）。
    if args.shell_enabled {
        cfg.shell.enabled = true;
        tracing::warn!("--shell-enabled 已生效：远程可执行任意命令，仅调试用，重启不带本参数即关闭");
    }
    if let Some(t) = args.shell_timeout {
        cfg.shell.timeout_secs = t;
    }
    init_tracing(&cfg);
    tracing::info!(version = env!("CARGO_PKG_VERSION"), "probe-daemon starting");
    tracing::info!(?cfg, "loaded config");

    // 装配生产 App（真实 infra）。
    let AppHandles { app, collect_handle, audit_handle } =
        build_production_app(&cfg).context("装配 App 失败")?;

    if args.dry_run {
        tracing::info!("dry-run 模式：不起监听");
        tokio::signal::ctrl_c().await.ok();
        app.cancel.cancel();
        return Ok(());
    }

    // 监听器。
    let mut handles: Vec<tokio::task::JoinHandle<Result<()>>> = Vec::new();

    if cfg.tcp.enabled {
        let bind = args.tcp_bind.clone().unwrap_or_else(|| cfg.tcp.bind.clone());
        let listener = tokio::net::TcpListener::bind(&bind)
            .await
            .with_context(|| format!("绑定 tcp {bind} 失败"))?;
        handles.push(tokio::spawn(accept_tcp_loop(listener, Arc::clone(&app))));
    }

    if cfg.unix.enabled {
        let path = args.unix_path.clone().unwrap_or_else(|| cfg.unix.path.clone());
        let _ = std::fs::remove_file(&path);
        let listener = tokio::net::UnixListener::bind(&path)
            .with_context(|| format!("绑定 unix {path} 失败"))?;
        let _ = std::fs::set_permissions(
            &path,
            std::os::unix::fs::PermissionsExt::from_mode(0o600),
        );
        tracing::info!(%path, "unix listener up");
        handles.push(tokio::spawn(accept_unix_loop(listener, Arc::clone(&app))));
    }

    // 串口（可选）：单个连接，直接 spawn run_session。
    if let Some(serial) = &cfg.serial {
        match infra::SerialTransport::open(&serial.path, serial.baud) {
            Ok(t) => {
                let label = t.label().to_string();
                let dispatcher = Arc::clone(&app.dispatcher);
                let audit = app.audit.clone();
                let rx = app.broadcaster.subscribe();
                tracing::info!(%label, "serial transport up");
                tokio::spawn(application::run_session(label, Box::new(t), dispatcher, audit, rx));
            }
            Err(e) => tracing::warn!(error=%e, "serial open failed"),
        }
    }

    // 优雅退出：Ctrl-C → cancel → 等监听器退出。
    tokio::signal::ctrl_c().await.ok();
    tracing::info!("shutting down");
    app.cancel.cancel();
    for h in handles {
        let _ = h.await;
    }
    // 让采集循环与审计任务感知 cancel 后退出（这里不阻塞等待，detached 即可）。
    let _ = (collect_handle, audit_handle);
    Ok(())
}

fn load_config(args: &Args) -> daemon::config::Config {
    if let Ok(cfg) = daemon::config::Config::load(&args.config) {
        return cfg;
    }
    tracing::warn!(path = %args.config, "config not found; using defaults");
    daemon::config::Config::default()
}

fn init_tracing(cfg: &daemon::config::Config) {
    let filter = EnvFilter::try_from_default_env()
        .unwrap_or_else(|_| EnvFilter::new(&cfg.log.level));
    tracing_subscriber::registry()
        .with(fmt::layer().with_target(true))
        .with(filter)
        .init();
}
