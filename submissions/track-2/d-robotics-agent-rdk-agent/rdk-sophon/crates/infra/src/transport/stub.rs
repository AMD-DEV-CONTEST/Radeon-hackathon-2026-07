//! In-memory transport for tests and a `dry-run` daemon mode. Two ends of an
//! in-memory channel; messages written to one end are read at the other.

use crate::transport::{Transport, TransportError};
use async_trait::async_trait;
use shared::protocol::JsonRpcMessage;
use tokio::sync::mpsc;

pub struct StubTransport {
    label: String,
    tx: mpsc::UnboundedSender<JsonRpcMessage>,
    rx: mpsc::UnboundedReceiver<JsonRpcMessage>,
}

impl StubTransport {
    /// Returns (a, b): messages sent on `a` arrive at `b`, and vice-versa.
    pub fn pair() -> (Self, Self) {
        let (atx, brx) = mpsc::unbounded_channel();
        let (btx, arx) = mpsc::unbounded_channel();
        let a = Self {
            label: "stub:a".into(),
            tx: atx,
            rx: arx,
        };
        let b = Self {
            label: "stub:b".into(),
            tx: btx,
            rx: brx,
        };
        (a, b)
    }
}

#[async_trait]
impl Transport for StubTransport {
    fn label(&self) -> &str {
        &self.label
    }

    async fn recv(&mut self) -> Result<Option<JsonRpcMessage>, TransportError> {
        match self.rx.recv().await {
            Some(m) => Ok(Some(m)),
            None => Ok(None),
        }
    }

    async fn send(&mut self, msg: &JsonRpcMessage) -> Result<(), TransportError> {
        self.tx
            .send(msg.clone())
            .map_err(|_| TransportError::Closed)
    }
}
