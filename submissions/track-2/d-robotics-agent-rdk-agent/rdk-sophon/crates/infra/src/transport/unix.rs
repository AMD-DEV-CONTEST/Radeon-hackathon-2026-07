//! Unix domain socket transport — for the local CLI (`sophonctl`) and any
//! board-local consumer. Authorised by filesystem permissions on the socket
//! path (0600, owned by the daemon's user).

use crate::transport::{framed::{FrameError, FramedReader, FramedWriter}, Transport, TransportError};
use async_trait::async_trait;
use shared::protocol::JsonRpcMessage;
use std::io;
use tokio::net::unix::{OwnedReadHalf, OwnedWriteHalf};
use tokio::net::UnixStream;

pub struct UnixTransport {
    label: String,
    reader: FramedReader<OwnedReadHalf>,
    writer: FramedWriter<OwnedWriteHalf>,
}

impl UnixTransport {
    pub fn new(stream: UnixStream, label: impl Into<String>) -> Self {
        let label = label.into();
        let (r, w) = stream.into_split();
        Self {
            label,
            reader: FramedReader::new(r),
            writer: FramedWriter::new(w),
        }
    }
}

#[async_trait]
impl Transport for UnixTransport {
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
