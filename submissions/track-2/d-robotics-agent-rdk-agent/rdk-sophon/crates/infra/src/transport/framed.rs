//! Newline-delimited JSON framing shared by TCP, Unix socket, and serial.
//!
//! Read side: accumulate bytes into a line buffer, split on `\n`, drop a
//! trailing `\r`, enforce `MAX_MESSAGE_BYTES`, deserialise one `JsonRpcMessage`.
//! Write side: serialise + append `\n` + write_all.

use shared::protocol::{JsonRpcMessage, ProtocolError, MAX_MESSAGE_BYTES};
use std::io;
use tokio::io::{AsyncBufReadExt, AsyncRead, AsyncWrite, AsyncWriteExt, BufReader};

#[derive(Debug, thiserror::Error)]
pub enum FrameError {
    #[error("line too long: {0} bytes (max {1})")]
    TooLong(usize, usize),
    #[error("serde: {0}")]
    Serde(#[from] serde_json::Error),
    #[error("io: {0}")]
    Io(#[from] io::Error),
}

/// Buffered NDJSON reader. Use `next()` to pull one message; `None` means EOF.
pub struct FramedReader<R: AsyncRead + Unpin> {
    reader: BufReader<R>,
    line_buf: Vec<u8>,
}

impl<R: AsyncRead + Unpin> FramedReader<R> {
    pub fn new(reader: R) -> Self {
        Self {
            reader: BufReader::with_capacity(64 * 1024, reader),
            line_buf: Vec::with_capacity(4096),
        }
    }

    /// Returns `Ok(Some(msg))` for a message, `Ok(None)` for clean EOF.
    pub async fn next(&mut self) -> Result<Option<JsonRpcMessage>, FrameError> {
        loop {
            // Try to complete a line from the buffer first.
            let mut found = false;
            // read_until appends to line_buf up to and including the delimiter.
            let n = self.reader.read_until(b'\n', &mut self.line_buf).await?;
            if n == 0 {
                // EOF: if there's a trailing line without \n, parse it; else done.
                if self.line_buf.is_empty() {
                    return Ok(None);
                }
                found = true; // treat final partial line as complete
            } else if self.line_buf.last() == Some(&b'\n') {
                found = true;
            }
            if !found {
                if self.line_buf.len() > MAX_MESSAGE_BYTES {
                    return Err(FrameError::TooLong(self.line_buf.len(), MAX_MESSAGE_BYTES));
                }
                continue;
            }

            if self.line_buf.len() > MAX_MESSAGE_BYTES {
                return Err(FrameError::TooLong(self.line_buf.len(), MAX_MESSAGE_BYTES));
            }
            // strip trailing \n and optional \r, then drain so we can clear.
            let line: Vec<u8> = trim_eol(&self.line_buf).to_vec();
            self.line_buf.clear();
            let bytes: &[u8] = &line;
            if bytes.is_empty() {
                // blank line between messages — skip.
                continue;
            }
            let msg = serde_json::from_slice::<JsonRpcMessage>(bytes)?;
            return Ok(Some(msg));
        }
    }
}

/// Unbuffered NDJSON writer. Each `write` serialises one message + `\n`.
pub struct FramedWriter<W: AsyncWrite + Unpin> {
    writer: W,
}

impl<W: AsyncWrite + Unpin> FramedWriter<W> {
    pub fn new(writer: W) -> Self {
        Self { writer }
    }

    pub async fn write(&mut self, msg: &JsonRpcMessage) -> Result<(), FrameError> {
        // Reuse the public serde_json path so size discipline is consistent.
        let mut buf = serde_json::to_vec(msg)?;
        buf.push(b'\n');
        self.writer.write_all(&buf).await?;
        self.writer.flush().await?;
        Ok(())
    }

    pub fn into_inner(self) -> W {
        self.writer
    }
}

fn trim_eol(buf: &[u8]) -> &[u8] {
    let mut end = buf.len();
    if end > 0 && buf[end - 1] == b'\n' {
        end -= 1;
    }
    if end > 0 && buf[end - 1] == b'\r' {
        end -= 1;
    }
    &buf[..end]
}

/// Convenience for callers that already hold a `ProtocolError`-style budget.
#[allow(dead_code)]
pub fn ensure_size(len: usize) -> Result<(), ProtocolError> {
    if len > MAX_MESSAGE_BYTES {
        Err(ProtocolError::TooLarge(len, MAX_MESSAGE_BYTES))
    } else {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use shared::protocol::Id;
    use tokio::io::duplex;

    #[tokio::test]
    async fn roundtrip_two_messages() {
        let (client, server) = duplex(8 * 1024);
        let mut writer = FramedWriter::new(client);
        let mut reader = FramedReader::new(server);

        let m1 = JsonRpcMessage::new_request(Id::Num(1), "get_thermal", None);
        let m2 = JsonRpcMessage::new_notification("telemetry", None);
        writer.write(&m1).await.unwrap();
        writer.write(&m2).await.unwrap();

        let r1 = reader.next().await.unwrap().unwrap();
        let r2 = reader.next().await.unwrap().unwrap();
        assert!(matches!(r1, JsonRpcMessage::Request(_)));
        assert!(matches!(r2, JsonRpcMessage::Notification(_)));
    }

    #[tokio::test]
    async fn handles_crlf_and_blank_lines() {
        let data = b"{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"x\"}\r\n\n{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"y\"}\n";
        let mut reader = FramedReader::new(&data[..]);
        let r1 = reader.next().await.unwrap().unwrap();
        let r2 = reader.next().await.unwrap().unwrap();
        assert!(matches!(r1, JsonRpcMessage::Request(r) if r.id == Id::Num(1)));
        assert!(matches!(r2, JsonRpcMessage::Request(r) if r.id == Id::Num(2)));
    }

    #[tokio::test]
    async fn eof_without_newline_still_yields_final_line() {
        let data = b"{\"jsonrpc\":\"2.0\",\"id\":7,\"method\":\"z\"}";
        let mut reader = FramedReader::new(&data[..]);
        let r = reader.next().await.unwrap().unwrap();
        assert!(matches!(r, JsonRpcMessage::Request(_)));
        assert!(reader.next().await.unwrap().is_none());
    }
}
