//! 指数退避重连：run_with_reconnect 包住 run_once，断线后退避重试。
//! 退避从 backoff_start 起，每次翻倍，上限 backoff_max，加入轻微抖动避免雷群。

use std::sync::Arc;

use anyhow::Result;

use crate::session::{run_once, SessionConfig};

/// 带重连的主循环。会话出错或断开时，按指数退避重连，永不退出（除非 Ctrl-C）。
pub async fn run_with_reconnect(cfg: SessionConfig) -> Result<()> {
    let cfg = Arc::new(cfg);
    let mut backoff = cfg.backoff_start;
    loop {
        match run_once(Arc::clone(&cfg)).await {
            Ok(()) => {
                // 正常断开（broker 关闭）：立即重连。
                tracing::info!("会话正常结束，立即重连");
                backoff = cfg.backoff_start;
            }
            Err(e) => {
                tracing::warn!(error = %e, ?backoff, "会话异常，退避后重连");
                tokio::time::sleep(backoff).await;
                // 指数退避，封顶 backoff_max。
                backoff = (backoff * 2).min(cfg.backoff_max);
            }
        }
    }
}
