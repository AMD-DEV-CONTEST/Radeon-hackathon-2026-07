//! client 共享 RPC 客户端库：本地 CLI（sophonctl）与远程入口（HTTP 网关、WS 出站）复用。
//! Client 封装 send/recv 循环、id 递增、id 匹配响应、超时、收到 notification 跳过不误当响应。
//! 从原 sophonctl/main.rs 的 call_and_print + chrono_id 提取。

mod client;
mod builder;
mod error;

pub use client::Client;
pub use builder::ClientBuilder;
pub use error::ClientError;
