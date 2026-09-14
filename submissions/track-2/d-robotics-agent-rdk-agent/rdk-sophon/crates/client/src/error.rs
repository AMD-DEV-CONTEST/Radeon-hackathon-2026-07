//! 客户端错误类型。

use thiserror::Error;

#[derive(Debug, Error)]
pub enum ClientError {
    #[error("transport 错误: {0}")]
    Transport(String),
    #[error("协议错误: {0}")]
    Protocol(String),
    #[error("服务端错误 {code}: {message}")]
    Server { code: i32, message: String },
    #[error("响应超时（{secs} 秒）")]
    Timeout { secs: u64 },
    #[error("连接在响应前关闭")]
    Closed,
}
