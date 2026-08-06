//! probe-ws-outbound：板子主动外连云端 WebSocket broker，把 daemon 的 telemetry/alert
//! notification 转发到云端。作为本地 daemon 的 Unix 客户端连进去，daemon 的 run_session
//! 会把 broadcast notification 转发给本连接，本进程收到后转成 WS 文本帧发出。

mod session;
mod reconnect;
mod codec;

use anyhow::Result;
use clap::Parser;

/// WS 出站 CLI 参数。
#[derive(Debug, Parser)]
#[command(name = "probe-ws-outbound", about = "rdk-sophon WebSocket 出站（云端）")]
struct Args {
    /// 云端 broker 的 WebSocket URL，如 ws://broker.example.com/board-001。
    #[arg(long)]
    broker_url: String,
    /// 本地 daemon 的 Unix socket 路径。
    #[arg(long, default_value = "/run/probe-daemon.sock")]
    daemon_sock: String,
    /// 重连初始退避（秒）。
    #[arg(long, default_value = "1")]
    backoff_start: u64,
    /// 重连最大退避（秒）。
    #[arg(long, default_value = "30")]
    backoff_max: u64,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt().with_env_filter(
        tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
    ).init();

    let args = Args::parse();
    let cfg = session::SessionConfig {
        broker_url: args.broker_url,
        daemon_sock: args.daemon_sock,
        backoff_start: std::time::Duration::from_secs(args.backoff_start),
        backoff_max: std::time::Duration::from_secs(args.backoff_max),
    };
    // 带重连的会话主循环：断线后指数退避重连。
    reconnect::run_with_reconnect(cfg).await
}
