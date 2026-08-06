//! Transport layer: a pluggable `Transport` trait plus concrete adapters.
//!
//! Each adapter solves exactly one problem — **framing** — and then hands
//! complete `JsonRpcMessage`s to/from the dispatcher. The dispatcher never
//! knows whether a message came from TCP, a serial line, a WebSocket, or a
//! Unix domain socket.
//!
//! Framing strategy by transport:
//! - TCP / Unix socket: newline-delimited JSON (NDJSON), one message per line.
//! - Serial: same NDJSON over the byte stream (cheap, debuggable over a tty).
//! - WebSocket: the WS frame boundary is the message boundary; we still
//!   serialise as JSON inside the frame.
//!
//! The MVP ships TCP, Unix socket, and a serial adapter. WebSocket and TLS
//! land in a follow-up — the trait is ready for them.

mod framed;
mod tcp;
mod unix;
mod serial;
mod stub;

pub use framed::{FramedReader, FramedWriter, FrameError};
pub use tcp::TcpTransport;
pub use unix::UnixTransport;
pub use serial::SerialTransport;
pub use stub::StubTransport;

use async_trait::async_trait;

/// A connected, bidirectional transport endpoint.
///
/// `recv` returns the next complete message or `None` on clean EOF.
/// `send` writes one message. Implementations are free to buffer/flush as
/// needed; `send` returns once the message is handed to the kernel/socket.
#[async_trait]
pub trait Transport: Send {
    /// Human-readable label for logs, e.g. "tcp:192.168.1.10:7777".
    fn label(&self) -> &str;

    async fn recv(&mut self) -> Result<Option<shared::protocol::JsonRpcMessage>, TransportError>;

    async fn send(&mut self, msg: &shared::protocol::JsonRpcMessage) -> Result<(), TransportError>;

    /// Hint that the peer has closed / the link is dead.
    async fn closed(&self) -> bool {
        false
    }
}

#[derive(Debug, thiserror::Error)]
pub enum TransportError {
    #[error("io error: {0}")]
    Io(#[from] std::io::Error),
    #[error("frame error: {0}")]
    Frame(#[from] FrameError),
    #[error("serial error: {0}")]
    Serial(String),
    #[error("message too large: {0} bytes")]
    TooLarge(usize),
    #[error("connection closed")]
    Closed,
}
