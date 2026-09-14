//! ClientBuilder：选择传输方式构造 Client。
//! tcp 用于远程板子，unix 用于本地 CLI，stub 用于测试。

use std::time::Duration;

use crate::client::Client;
use crate::error::ClientError;
use infra::{StubTransport, TcpTransport, UnixTransport};

pub struct ClientBuilder {
    timeout: Duration,
}

impl Default for ClientBuilder {
    fn default() -> Self {
        Self { timeout: Duration::from_secs(30) }
    }
}

impl ClientBuilder {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn timeout(mut self, t: Duration) -> Self {
        self.timeout = t;
        self
    }

    /// 连远程板子（网络/USB网卡/SSH 隧道都走 TCP）。
    pub async fn tcp(self, addr: &str) -> Result<Client, ClientError> {
        let stream = tokio::net::TcpStream::connect(addr)
            .await
            .map_err(|e| ClientError::Transport(e.to_string()))?;
        let peer = stream.peer_addr().map_err(|e| ClientError::Transport(e.to_string()))?;
        let t = TcpTransport::new(stream, peer);
        Ok(Client::new(Box::new(t)).with_timeout(self.timeout))
    }

    /// 连本地 daemon（Unix socket）。
    pub async fn unix(self, path: &str) -> Result<Client, ClientError> {
        let stream = tokio::net::UnixStream::connect(path)
            .await
            .map_err(|e| ClientError::Transport(e.to_string()))?;
        let t = UnixTransport::new(stream, "unix");
        Ok(Client::new(Box::new(t)).with_timeout(self.timeout))
    }

    /// 测试用：直接给一个 StubTransport pair 的一端。
    pub fn stub(self, t: StubTransport) -> Client {
        Client::new(Box::new(t)).with_timeout(self.timeout)
    }
}
