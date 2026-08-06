//! SessionService：单连接驱动。从原 daemon session.rs 移入 application 层。
//! tokio::select! 并发：读请求→后台 dispatch→回发响应，同时把 broadcast 的 telemetry/alert
//! notification 转发给对端。连接关闭时会 abort 正在执行的请求；真实插件进程使用
//! `kill_on_drop`，因此 `sophonctl` 的 Ctrl-C 不会遗留长驻控制脚本。

use std::sync::Arc;

use crate::audit::AuditLog;
use crate::rpc_dispatcher::{DispatchOutcome, RpcDispatcher};
use infra::Transport;
use shared::protocol::{Error, ErrorCode, JsonRpcMessage};
use tokio::sync::broadcast;

/// 进程级 telemetry/alert 广播总线。daemon 装配时建一个，所有连接订阅。
#[derive(Clone)]
pub struct Broadcaster {
    tx: broadcast::Sender<JsonRpcMessage>,
}

impl Broadcaster {
    pub fn new(capacity: usize) -> Self {
        let (tx, _) = broadcast::channel(capacity);
        Self { tx }
    }
    pub fn subscribe(&self) -> broadcast::Receiver<JsonRpcMessage> {
        self.tx.subscribe()
    }
    /// 发布一条消息给所有订阅者（无订阅者时丢弃）。
    pub fn publish(&self, msg: JsonRpcMessage) {
        let _ = self.tx.send(msg);
    }
}

/// 驱动一条连接直到 EOF 或致命错误。
pub async fn run_session(
    label: String,
    mut transport: Box<dyn Transport>,
    dispatcher: Arc<RpcDispatcher>,
    audit: AuditLog,
    mut bcast_rx: broadcast::Receiver<JsonRpcMessage>,
) {
    tracing::info!(%label, "session started");
    let mut pending = None;
    loop {
        if let Some(task) = pending.as_mut() {
            tokio::select! {
                result = task => {
                    pending = None;
                    match result {
                        Ok(DispatchOutcome::Response(resp)) => {
                            if let Err(e) = transport.send(&resp).await {
                                tracing::warn!(%label, error=%e, "response send failed");
                                break;
                            }
                        }
                        Ok(DispatchOutcome::NoReply) => {}
                        Err(e) => tracing::warn!(%label, error=%e, "dispatch task failed"),
                    }
                }
                recv_result = bcast_rx.recv() => {
                    match recv_result {
                        Ok(msg) => {
                            if let Err(e) = transport.send(&msg).await {
                                tracing::warn!(%label, error=%e, "broadcast send failed");
                                break;
                            }
                        }
                        Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
                        Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                            tracing::warn!(%label, lagged = n, "broadcast lagged, resubscribing");
                        }
                    }
                }
                res = transport.recv() => {
                    match res {
                        // 单连接的 Client 是串行请求模型；忙时拒绝新的 request，仍继续读取以便侦测 EOF。
                        Ok(Some(JsonRpcMessage::Request(req))) => {
                            let error = JsonRpcMessage::new_error(req.id, Error::new(ErrorCode::InvalidRequest, "当前连接已有请求正在执行"));
                            if let Err(e) = transport.send(&error).await {
                                tracing::warn!(%label, error=%e, "busy response send failed");
                                break;
                            }
                        }
                        Ok(Some(_)) => {}
                        Ok(None) => {
                            tracing::info!(%label, "peer closed; cancelling pending request");
                            break;
                        }
                        Err(e) => {
                            tracing::warn!(%label, error=%e, "recv error; cancelling pending request");
                            break;
                        }
                    }
                }
            }
            continue;
        }
        tokio::select! {
            biased;
            // 优先转发广播（telemetry/alert），不让慢 shell 阻塞推送。
            recv_result = bcast_rx.recv() => {
                match recv_result {
                    Ok(msg) => {
                        if let Err(e) = transport.send(&msg).await {
                            tracing::warn!(%label, error=%e, "broadcast send failed");
                            break;
                        }
                    }
                    Err(tokio::sync::broadcast::error::RecvError::Closed) => break,
                    Err(tokio::sync::broadcast::error::RecvError::Lagged(n)) => {
                        // WS 出站等慢消费者可能 lag；重订阅继续，不静默丢。
                        tracing::warn!(%label, lagged = n, "broadcast lagged, resubscribing");
                    }
                }
            }
            // 读请求后后台分发，下一轮 select 同时监听 EOF 与广播。
            res = transport.recv() => {
                match res {
                    Ok(Some(incoming)) => {
                        let dispatcher = Arc::clone(&dispatcher);
                        let audit = audit.clone();
                        let source = label.clone();
                        pending = Some(tokio::spawn(async move {
                            dispatcher.dispatch(incoming, &source, &audit).await
                        }));
                    }
                    Ok(None) => {
                        tracing::info!(%label, "peer closed");
                        break;
                    }
                    Err(e) => {
                        tracing::warn!(%label, error=%e, "recv error");
                        break;
                    }
                }
            }
        }
    }
    // abort 会 drop 正在 await 的 PluginRunner；RealPluginRunner 的 kill_on_drop 会杀掉子进程。
    if let Some(task) = pending {
        task.abort();
    }
    tracing::info!(%label, "session ended");
}
