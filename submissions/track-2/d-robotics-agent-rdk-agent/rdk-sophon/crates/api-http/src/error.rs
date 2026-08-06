//! HTTP 错误：把 client::ClientError 映射成 HTTP 状态码 + JSON 体。

use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};
use axum::Json;
use serde_json::json;

use client::ClientError;

/// 把 ClientError 转成 (StatusCode, JSON body)。
pub fn client_error_to_response(e: &ClientError) -> (StatusCode, serde_json::Value) {
    match e {
        ClientError::Server { code, message } => {
            // 服务端错误：按 JSON-RPC 错误码映射 HTTP 码。
            let status = match *code {
                -32601 => StatusCode::NOT_FOUND,        // MethodNotFound
                -32602 => StatusCode::BAD_REQUEST,       // InvalidParams
                -32000 => StatusCode::INTERNAL_SERVER_ERROR, // ExecError
                -32001 => StatusCode::FORBIDDEN,         // ShellDisabled
                -32002 => StatusCode::FORBIDDEN,         // ShellDenied
                -32003 => StatusCode::GATEWAY_TIMEOUT,  // Timeout
                -32004 => StatusCode::TOO_MANY_REQUESTS, // RateLimited
                _ => StatusCode::INTERNAL_SERVER_ERROR,
            };
            (status, json!({"error": {"code": code, "message": message}}))
        }
        ClientError::Timeout { secs } => (
            StatusCode::GATEWAY_TIMEOUT,
            json!({"error": {"code": -32003, "message": format!("响应超时（{secs} 秒）")}}),
        ),
        ClientError::Closed => (StatusCode::BAD_GATEWAY, json!({"error": "daemon 连接关闭"})),
        ClientError::Transport(msg) => (StatusCode::BAD_GATEWAY, json!({"error": format!("transport: {msg}")})),
        ClientError::Protocol(msg) => (StatusCode::BAD_GATEWAY, json!({"error": format!("protocol: {msg}")})),
    }
}

/// axum 可用的错误类型。
pub struct HttpError(pub ClientError);

impl IntoResponse for HttpError {
    fn into_response(self) -> Response {
        let (status, body) = client_error_to_response(&self.0);
        (status, Json(body)).into_response()
    }
}
