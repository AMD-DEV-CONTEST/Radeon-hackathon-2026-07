//! infra 基础设施层：实现 shared::ports 定义的 trait，以及传输适配器。
//!
//! 包含两个子模块：
//! - `transport`：Transport trait + NDJSON 帧 + TCP/Unix/Serial/Stub 适配器。
//! - 顶层实现：sysfs/proc/hrut 读硬件、statvfs FFI、shell 执行（RealShellRunner）。
//!
//! 所有实现都是 best-effort：单个读取失败返回 None/Err，不 panic，不拖垮 daemon。

pub mod transport;

mod hrut;
mod plugin;
mod proc;
mod shell;
mod statvfs;
mod sysfs;

pub use hrut::RealHrutGateway;
pub use plugin::{DisabledPluginRunner, RealPluginRunner};
pub use proc::RealProcReader;
pub use shell::RealShellRunner;
pub use statvfs::{statvfs_of, StatvfsResult};
pub use sysfs::RealSysfsReader;

// 传输层便捷重导出，让下游可直接 `use infra::Transport` 等。
pub use transport::{
    FrameError, FramedReader, FramedWriter, SerialTransport, StubTransport, TcpTransport,
    Transport, TransportError, UnixTransport,
};
