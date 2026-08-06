use thiserror::Error;

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid message: {0}")]
    InvalidMessage(String),

    #[error("message too large: {0} bytes (max {1})")]
    TooLarge(usize, usize),

    #[error("serde error: {0}")]
    Serde(#[from] serde_json::Error),

    #[error("unknown method: {0}")]
    UnknownMethod(String),
}
