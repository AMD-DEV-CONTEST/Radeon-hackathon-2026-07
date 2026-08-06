//! Serial (UART) transport. Uses the blocking `serialport` crate for broad
//! platform coverage and parks reads on `spawn_blocking` so we don't need a
//! second async serial dependency. NDJSON framing works over the byte stream
//! just like over TCP — a UART that emits text JSON lines is trivially
//! debuggable from a tty.

use crate::transport::{framed::FrameError, Transport, TransportError};
use async_trait::async_trait;
use shared::protocol::JsonRpcMessage;
use std::{
    io::{self, Read, Write},
    sync::mpsc,
    thread,
};
use tokio::sync::Mutex;

/// Open a serial port at the given path/baud. 8N1 is the default; raise via
/// the daemon config if a board needs 7E1 or similar.
pub struct SerialTransport {
    label: String,
    /// Writes go straight to the port from the async side (cheap, non-blocking
    /// for typical command sizes). Reads come back through a channel fed by a
    /// dedicated blocking thread, because `serialport` has no async API.
    write: Mutex<Box<dyn SerialWrite + Send>>,
    recv_rx: tokio::sync::mpsc::Receiver<Result<Option<JsonRpcMessage>, TransportError>>,
}

trait SerialWrite: Write {}
impl<T: Write> SerialWrite for T {}

impl SerialTransport {
    pub fn open(path: &str, baud: u32) -> Result<Self, TransportError> {
        let port = serialport::new(path, baud)
            .timeout(std::time::Duration::from_millis(250))
            .open_native()
            .map_err(|e| TransportError::Serial(e.to_string()))?;
        let label = format!("serial:{path}@{baud}");

        // Split into a reader (owned by the blocking thread) and a writer
        // (kept here). `serialport` ports are Clone, so we can duplicate.
        let mut reader_port = port
            .try_clone_native()
            .map_err(|e| TransportError::Serial(e.to_string()))?;
        let writer_port: Box<dyn SerialWrite + Send> = Box::new(
            port
        );

        let (tx, rx) = tokio::sync::mpsc::channel(16);
        let (ack_tx, ack_rx) = mpsc::channel::<()>();

        thread::spawn(move || {
            // We feed the blocking reader through a small bridge: read bytes
            // from the port in chunks, decode NDJSON lines, send messages.
            let mut buf = [0u8; 4096];
            let mut acc: Vec<u8> = Vec::with_capacity(8192);
            // Signal the constructor that the thread is up.
            let _ = ack_tx.send(());
            loop {
                match reader_port.read(&mut buf) {
                    Ok(0) => {
                        let _ = tx.blocking_send(Ok(None));
                        break;
                    }
                    Ok(n) => {
                        acc.extend_from_slice(&buf[..n]);
                        // Extract complete lines.
                        while let Some(pos) = acc.iter().position(|&b| b == b'\n') {
                            let line: Vec<u8> = acc.drain(..=pos).collect();
                            let line = trim_eol(&line);
                            if line.is_empty() {
                                continue;
                            }
                            match serde_json::from_slice::<JsonRpcMessage>(line) {
                                Ok(m) => {
                                    if tx.blocking_send(Ok(Some(m))).is_err() {
                                        return;
                                    }
                                }
                                Err(e) => {
                                    let _ = tx.blocking_send(Err(TransportError::Frame(
                                        FrameError::Serde(e),
                                    )));
                                }
                            }
                            if line.len() > shared::protocol::MAX_MESSAGE_BYTES {
                                let _ = tx.blocking_send(Err(TransportError::TooLarge(
                                    line.len(),
                                )));
                                return;
                            }
                        }
                        if acc.len() > shared::protocol::MAX_MESSAGE_BYTES {
                            let _ = tx.blocking_send(Err(TransportError::TooLarge(acc.len())));
                            return;
                        }
                    }
                    Err(ref e) if e.kind() == io::ErrorKind::TimedOut => continue,
                    Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => continue,
                    Err(e) => {
                        let _ = tx.blocking_send(Err(TransportError::Serial(e.to_string())));
                        break;
                    }
                }
            }
        });
        // Wait for the reader thread to have started so `recv` won't race.
        let _ = ack_rx.recv();

        Ok(Self {
            label,
            write: Mutex::new(writer_port),
            recv_rx: rx,
        })
    }
}

#[async_trait]
impl Transport for SerialTransport {
    fn label(&self) -> &str {
        &self.label
    }

    async fn recv(&mut self) -> Result<Option<JsonRpcMessage>, TransportError> {
        match self.recv_rx.recv().await {
            Some(Ok(m)) => Ok(m),
            Some(Err(e)) => Err(e),
            None => Ok(None),
        }
    }

    async fn send(&mut self, msg: &JsonRpcMessage) -> Result<(), TransportError> {
        let mut buf = serde_json::to_vec(msg).map_err(FrameError::Serde)?;
        buf.push(b'\n');
        let mut w = self.write.lock().await;
        // Writes are short and bounded (a few KB at most). A blocking write
        // under the mutex is acceptable for the MVP; if a slow UART backs up,
        // the bounded read channel exerts backpressure upstream.
        w.write_all(&buf)
            .map_err(|e| TransportError::Serial(e.to_string()))?;
        w.flush()
            .map_err(|e| TransportError::Serial(e.to_string()))?;
        Ok(())
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
