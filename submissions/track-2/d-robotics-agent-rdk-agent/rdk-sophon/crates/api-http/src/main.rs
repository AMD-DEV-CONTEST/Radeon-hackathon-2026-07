//! probe-http-gateway：把 daemon 的 JSON-RPC 包成 HTTP/REST。
//! 本地连 daemon 的 Unix socket（作为 client），对外暴露 REST 路由，
//! 方便 curl / 浏览器 / 脚本访问板端硬件状态与命令。

mod routes;
mod error;

use std::time::Duration;

use anyhow::Result;
use clap::Parser;
use client::ClientBuilder;

/// HTTP 网关 CLI 参数。
#[derive(Debug, Parser)]
#[command(name = "probe-http-gateway", about = "rdk-sophon REST 网关")]
struct Args {
    /// HTTP 监听地址。
    #[arg(long, default_value = "0.0.0.0:8080")]
    listen: String,
    /// daemon 的 Unix socket 路径。
    #[arg(long, default_value = "/run/probe-daemon.sock")]
    daemon_sock: String,
    /// 连 daemon 的响应超时（秒）。
    #[arg(long, default_value = "10")]
    timeout: u64,
}

#[tokio::main]
async fn main() -> Result<()> {
    tracing_subscriber::fmt().with_env_filter(
        tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
    ).init();

    let args = Args::parse();
    let client = ClientBuilder::new()
        .timeout(Duration::from_secs(args.timeout))
        .unix(&args.daemon_sock)
        .await
        .map_err(|e| anyhow::anyhow!("连 daemon 失败（{}）: {e}", args.daemon_sock))?;

    let app = routes::router(client);
    let listener = tokio::net::TcpListener::bind(&args.listen).await?;
    tracing::info!(%args.listen, "http-gateway up");
    axum::serve(listener, app).await?;
    Ok(())
}
