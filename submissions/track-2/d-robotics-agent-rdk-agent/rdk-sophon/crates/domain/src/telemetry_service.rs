//! TelemetryService：把 StateSnapshot 包成 JSON-RPC notification（telemetry 推送）。
//! 从原 daemon main.rs 采集循环里的 message 构造提取为领域服务，便于复用与单测。

use shared::protocol::{JsonRpcMessage, Params, StateSnapshot};

pub struct TelemetryService;

impl TelemetryService {
    /// 用快照构造一条 telemetry notification（无 id，fire-and-forget）。
    pub fn build_notification(snap: &StateSnapshot) -> JsonRpcMessage {
        // 序列化快照为 named params 对象。
        let params = serde_json::to_value(snap)
            .ok()
            .and_then(|v| v.as_object().cloned())
            .unwrap_or_default();
        JsonRpcMessage::new_notification("telemetry", Some(Params::Named(params)))
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use shared::protocol::Id;

    #[test]
    fn telemetry_notification_has_no_id() {
        let snap = StateSnapshot::default();
        let msg = TelemetryService::build_notification(&snap);
        // notification 不应携带 id（fire-and-forget）。
        let s = serde_json::to_string(&msg).unwrap();
        assert!(!s.contains("\"id\""));
        assert!(s.contains("\"method\":\"telemetry\""));
        let _ = Id::Num(0); // 引用 Id 避免未用导入
    }
}
