//! Client：JSON-RPC 客户端。持有一条 Transport，发请求并按 id 匹配响应。
//! 收到 notification（telemetry/alert）时不当作响应，转发给可选的 notification 处理回调或跳过。

use std::sync::atomic::{AtomicI64, Ordering};
use std::time::Duration;

use shared::protocol::{Id, JsonRpcMessage, Params, ResponsePayload};
use tokio::sync::Mutex;
use infra::Transport;

use crate::error::ClientError;

/// notification 回调类型别名，避免重复书写复杂签名。
type NotificationCb = Box<dyn Fn(JsonRpcMessage) + Send + Sync>;

pub struct Client {
    transport: Mutex<Box<dyn Transport>>,
    id_counter: AtomicI64,
    /// 默认响应超时。
    default_timeout: Duration,
    /// 可选：收到 notification 时调此回调（如 WS 出站要转发 telemetry 到云端）。
    on_notification: Mutex<Option<NotificationCb>>,
}

impl Client {
    pub fn new(transport: Box<dyn Transport>) -> Self {
        Self {
            transport: Mutex::new(transport),
            id_counter: AtomicI64::new(1),
            default_timeout: Duration::from_secs(30),
            on_notification: Mutex::new(None),
        }
    }

    pub fn with_timeout(mut self, t: Duration) -> Self {
        self.default_timeout = t;
        self
    }

    /// 设置 notification 回调。WS 出站等场景用于把 telemetry/alert 转发出去。
    pub async fn on_notification<F>(&self, f: F)
    where
        F: Fn(JsonRpcMessage) + Send + Sync + 'static,
    {
        *self.on_notification.lock().await = Some(Box::new(f));
    }

    /// 调用一个方法，等待 id 匹配的响应。期间收到的 notification 转发回调或跳过。
    pub async fn call(&self, method: &str, params: Option<Params>) -> Result<serde_json::Value, ClientError> {
        self.call_timeout(method, params, self.default_timeout).await
    }

    pub async fn call_timeout(
        &self,
        method: &str,
        params: Option<Params>,
        timeout: Duration,
    ) -> Result<serde_json::Value, ClientError> {
        let id = Id::Num(self.id_counter.fetch_add(1, Ordering::Relaxed));
        let req = JsonRpcMessage::new_request(id.clone(), method, params);
        let mut t = self.transport.lock().await;
        t.send(&req).await.map_err(|e| ClientError::Transport(e.to_string()))?;

        let deadline = tokio::time::Instant::now() + timeout;
        loop {
            let recv_fut = t.recv();
            let next = match tokio::time::timeout_at(deadline, recv_fut).await {
                Ok(r) => r,
                Err(_) => return Err(ClientError::Timeout { secs: timeout.as_secs() }),
            };
            let msg = match next.map_err(|e| ClientError::Transport(e.to_string()))? {
                Some(m) => m,
                None => return Err(ClientError::Closed),
            };
            match msg {
                JsonRpcMessage::Response(resp) => {
                    // 仅当 id 匹配才采纳；否则继续等（异步乱序防御）。
                    if resp.id == id {
                        return match resp.payload {
                            ResponsePayload::Result(v) => Ok(v),
                            ResponsePayload::Error(e) => Err(ClientError::Server { code: e.code, message: e.message }),
                        };
                    }
                    // id 不匹配：可能是对老请求的迟到响应，丢弃继续等。
                }
                JsonRpcMessage::Notification(n) => {
                    // 收到 telemetry/alert：转发回调或跳过，不误当响应。
                    if let Some(cb) = self.on_notification.lock().await.as_ref() {
                        cb(JsonRpcMessage::Notification(n));
                    }
                }
                JsonRpcMessage::Request(_) => {
                    // 服务端不应发请求给客户端；忽略。
                }
            }
        }
    }
}
