//! JSON-RPC 消息与 WebSocket 文本帧的编解码。
//! WS 帧天然有边界，每帧一条 JSON-RPC 文本。无需 NDJSON 换行分隔。

use shared::protocol::JsonRpcMessage;

/// 把一条 JSON-RPC 消息序列化为 WS 文本帧内容。
pub fn encode(msg: &JsonRpcMessage) -> Result<String, serde_json::Error> {
    serde_json::to_string(msg)
}

/// 把一帧 WS 文本解析为 JSON-RPC 消息。
#[allow(dead_code)]
pub fn decode(text: &str) -> Result<JsonRpcMessage, serde_json::Error> {
    serde_json::from_str(text)
}

#[cfg(test)]
mod tests {
    use super::*;
    use shared::protocol::Id;

    #[test]
    fn roundtrip_notification() {
        let msg = JsonRpcMessage::new_notification("telemetry", None);
        let s = encode(&msg).unwrap();
        assert!(s.contains("\"method\":\"telemetry\""));
        let back = decode(&s).unwrap();
        assert!(back.is_notification());
        let _ = Id::Num(0);
    }
}
