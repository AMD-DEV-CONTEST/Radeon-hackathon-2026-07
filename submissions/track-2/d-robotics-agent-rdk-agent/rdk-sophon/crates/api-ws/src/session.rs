//! WS 会话：连云端 broker → 连本地 daemon → 把 daemon 推来的 notification 转发到云端。
//!
//! 关键设计：WS 出站作为本地 daemon 的 Unix 客户端连进去，daemon 的 run_session
//! 已用 select! 把 broadcast telemetry/alert notification 转发给所有连接（含本进程）。
//! 本进程用底层 transport::UnixTransport 直接 recv（不走 client::Client，因为要收
//! 的是 notification 而非 request/response），收到 notification 后转成 WS 文本帧发出。

use std::sync::Arc;
use std::time::Duration;

use anyhow::{Context, Result};
use shared::protocol::JsonRpcMessage;
use tokio::net::UnixStream;
use tokio::sync::mpsc;
use tokio_tungstenite::tungstenite::Message as WsMessage;
use infra::{Transport, UnixTransport};

/// 会话配置。
#[derive(Debug, Clone)]
pub struct SessionConfig {
    pub broker_url: String,
    pub daemon_sock: String,
    pub backoff_start: Duration,
    pub backoff_max: Duration,
}

/// 跑一次完整会话（连 broker + 连 daemon + 转发）。断开或出错返回，由上层重连。
pub async fn run_once(cfg: Arc<SessionConfig>) -> Result<()> {
    // 1. 连云端 broker（WS）。
    tracing::info!(url = %cfg.broker_url, "connecting to broker");
    let (ws_stream, _resp) = tokio_tungstenite::connect_async(&cfg.broker_url)
        .await
        .with_context(|| format!("连 broker 失败: {}", cfg.broker_url))?;
    tracing::info!("broker connected");

    // 2. 连本地 daemon（Unix socket）。
    let stream = UnixStream::connect(&cfg.daemon_sock)
        .await
        .with_context(|| format!("连 daemon 失败: {}", cfg.daemon_sock))?;
    let mut daemon_t = UnixTransport::new(stream, "daemon");

    // 3. 拆 WS 为读写两端。写端由独立任务持有，从 channel 收要发的帧。
    use futures_util::StreamExt;
    use futures_util::SinkExt;
    let (mut ws_write, mut ws_read) = ws_stream.split();
    let (tx, mut rx) = mpsc::unbounded_channel::<WsMessage>();

    // 写任务：从 channel 取帧写到 WS。
    let write_task = tokio::spawn(async move {
        while let Some(msg) = rx.recv().await {
            if ws_write.send(msg).await.is_err() {
                break;
            }
        }
    });

    // 4. 双向转发：daemon notification → 云端 WS；云端 WS 帧 → 控制。
    loop {
        tokio::select! {
            // 从 daemon 收消息（telemetry/alert notification 或对 ping 的响应）。
            res = daemon_t.recv() => {
                match res {
                    Ok(Some(msg)) => {
                        if msg.is_notification() {
                            // notification 转发到云端。
                            if let Ok(text) = crate::codec::encode(&msg) {
                                tracing::debug!("转发 notification: {}", msg_label(&msg));
                                if tx.send(WsMessage::Text(text)).is_err() {
                                    break;
                                }
                            }
                        }
                        // 非 notification 忽略。
                    }
                    Ok(None) => {
                        tracing::info!("daemon 连接关闭");
                        break;
                    }
                    Err(e) => {
                        tracing::warn!(error=%e, "daemon recv error");
                        break;
                    }
                }
            }
            // 云端 WS 来帧（心跳/控制/指令）。
            ws_msg = ws_read.next() => {
                match ws_msg {
                    Some(Ok(WsMessage::Ping(_) | WsMessage::Pong(_))) => continue,
                    Some(Ok(WsMessage::Close(_))) => {
                        tracing::info!("broker 关闭连接");
                        break;
                    }
                    Some(Ok(_)) => {
                        // 云端下发的指令：转发给 daemon（未来扩展，当前忽略）。
                        continue;
                    }
                    Some(Err(e)) => {
                        tracing::warn!(error=%e, "broker ws error");
                        break;
                    }
                    None => break,
                }
            }
        }
    }
    // 退出时 drop 写任务，channel 关闭，写任务自然结束。
    write_task.abort();
    Ok(())
}

/// 给 notification 起个简短标签用于日志。
fn msg_label(msg: &JsonRpcMessage) -> String {
    match msg {
        JsonRpcMessage::Notification(n) => format!("notification:{}", n.method),
        JsonRpcMessage::Response(r) => format!("response:{}", r.id),
        JsonRpcMessage::Request(r) => format!("request:{}", r.method),
    }
}
