//! TCP transport — accepts the local network, USB-tethered (RNDIS/CDC-ECM),
//! and SSH-forwarded cases, since all three are just "TCP to a port".
//! TLS is a follow-up; the adapter is shaped to wrap a `TcpStream`.

use crate::transport::{framed::{FrameError, FramedReader, FramedWriter}, Transport, TransportError};
use async_trait::async_trait;
use shared::protocol::JsonRpcMessage;
use std::io;
use tokio::net::tcp::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::TcpStream;

pub struct TcpTransport {
    label: String,
    reader: FramedReader<OwnedReadHalf>,
    writer: FramedWriter<OwnedWriteHalf>,
}

impl TcpTransport {
    pub fn new(stream: TcpStream, peer: std::net::SocketAddr) -> Self {
        let label = format!("tcp:{peer}");
        let (r, w) = stream.into_split();
        Self {
            label,
            reader: FramedReader::new(r),
            writer: FramedWriter::new(w),
        }
    }
}

#[async_trait]
impl Transport for TcpTransport {
    fn label(&self) -> &str {
        &self.label
    }

    async fn recv(&mut self) -> Result<Option<JsonRpcMessage>, TransportError> {
        match self.reader.next().await {
            Ok(Some(m)) => Ok(Some(m)),
            Ok(None) => Ok(None),
            Err(FrameError::Io(e)) if e.kind() == io::ErrorKind::UnexpectedEof => Ok(None),
            Err(e) => Err(e.into()),
        }
    }

    async fn send(&mut self, msg: &JsonRpcMessage) -> Result<(), TransportError> {
        self.writer.write(msg).await.map_err(Into::into)
    }
}
