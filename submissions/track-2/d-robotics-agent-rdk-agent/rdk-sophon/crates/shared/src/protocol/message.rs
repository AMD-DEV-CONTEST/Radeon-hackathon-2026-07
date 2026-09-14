use serde::{Deserialize, Serialize};
use std::fmt;

/// JSON-RPC 2.0 envelope. A message is exactly one of:
/// - request  (has method + id)        → expects a response
/// - response (has result|error + id)
/// - notification (has method, NO id)  → fire-and-forget (telemetry/alerts)
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum JsonRpcMessage {
    Request(Request),
    Response(Response),
    Notification(Notification),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Request {
    pub jsonrpc: String,
    pub id: Id,
    pub method: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<Params>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Response {
    pub jsonrpc: String,
    pub id: Id,
    #[serde(flatten)]
    pub payload: ResponsePayload,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum ResponsePayload {
    #[serde(rename = "result")]
    Result(serde_json::Value),
    #[serde(rename = "error")]
    Error(Error),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Notification {
    pub jsonrpc: String,
    pub method: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub params: Option<Params>,
}

/// JSON-RPC id: null/number/string per spec. We never emit null ids.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Id {
    Num(i64),
    Str(String),
    Null,
}

/// Method params: positional (array) or named (object). We mostly use named.
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum Params {
    Named(serde_json::Map<String, serde_json::Value>),
    Positional(Vec<serde_json::Value>),
}

/// JSON-RPC 2.0 error object.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Error {
    pub code: i32,
    pub message: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub data: Option<serde_json::Value>,
}

impl Error {
    pub fn new(code: ErrorCode, message: impl Into<String>) -> Self {
        Self {
            code: code as i32,
            message: message.into(),
            data: None,
        }
    }

    pub fn with_data(mut self, data: serde_json::Value) -> Self {
        self.data = Some(data);
        self
    }
}

/// Standard JSON-RPC error codes plus a few application-specific extensions.
#[derive(Debug, Clone, Copy)]
#[repr(i32)]
pub enum ErrorCode {
    ParseError = -32700,
    InvalidRequest = -32600,
    MethodNotFound = -32601,
    InvalidParams = -32602,
    InternalError = -32603,
    // application-specific
    ExecError = -32000,
    ShellDisabled = -32001,
    ShellDenied = -32002,
    Timeout = -32003,
    RateLimited = -32004,
}

impl JsonRpcMessage {
    pub fn new_request(id: Id, method: impl Into<String>, params: Option<Params>) -> Self {
        Self::Request(Request {
            jsonrpc: crate::JSONRPC_VERSION.to_string(),
            id,
            method: method.into(),
            params,
        })
    }

    pub fn new_response(id: Id, result: serde_json::Value) -> Self {
        Self::Response(Response {
            jsonrpc: crate::JSONRPC_VERSION.to_string(),
            id,
            payload: ResponsePayload::Result(result),
        })
    }

    pub fn new_error(id: Id, err: Error) -> Self {
        Self::Response(Response {
            jsonrpc: crate::JSONRPC_VERSION.to_string(),
            id,
            payload: ResponsePayload::Error(err),
        })
    }

    pub fn new_notification(method: impl Into<String>, params: Option<Params>) -> Self {
        Self::Notification(Notification {
            jsonrpc: crate::JSONRPC_VERSION.to_string(),
            method: method.into(),
            params,
        })
    }

    /// True for telemetry/alert notifications that carry no id and expect no reply.
    pub fn is_notification(&self) -> bool {
        matches!(self, JsonRpcMessage::Notification(_))
    }
}

impl fmt::Display for Id {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Id::Num(n) => write!(f, "{n}"),
            Id::Str(s) => write!(f, "{s}"),
            Id::Null => write!(f, "null"),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_request() {
        let msg = JsonRpcMessage::new_request(
            Id::Num(1),
            "get_thermal",
            None,
        );
        let s = serde_json::to_string(&msg).unwrap();
        assert!(s.contains("\"method\":\"get_thermal\""));
        let back: JsonRpcMessage = serde_json::from_str(&s).unwrap();
        assert!(matches!(back, JsonRpcMessage::Request(_)));
    }

    #[test]
    fn notification_has_no_id() {
        let msg = JsonRpcMessage::new_notification("telemetry", None);
        let s = serde_json::to_string(&msg).unwrap();
        assert!(!s.contains("\"id\""));
        assert!(msg.is_notification());
    }

    #[test]
    fn response_roundtrip_result() {
        let msg = JsonRpcMessage::new_response(Id::Num(1), serde_json::json!({"ok": true}));
        let s = serde_json::to_string(&msg).unwrap();
        let back: JsonRpcMessage = serde_json::from_str(&s).unwrap();
        match back {
            JsonRpcMessage::Response(r) => assert!(matches!(r.payload, ResponsePayload::Result(_))),
            _ => panic!("expected response"),
        }
    }
}
