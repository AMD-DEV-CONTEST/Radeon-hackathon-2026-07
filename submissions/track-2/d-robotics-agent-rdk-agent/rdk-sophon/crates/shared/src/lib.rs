//! shared 层：协议数据 + 端口 trait 的共享底座。
//!
//! 包含两个子模块：
//! - `protocol`：JSON-RPC 2.0 信封 + StateSnapshot 状态快照类型。无 IO，无 tokio。
//! - `ports`：领域对外的纯 trait 抽象（Collector/SysfsReader/ProcReader/HrutGateway/ShellRunner）。
//!
//! 依赖方向：shared 是最底层，无内部 crate 依赖。下游（infra/domain/application/daemon）依赖 shared。

pub mod protocol;
pub mod ports;

// 便捷重导出：让下游可直接 `use shared::JsonRpcMessage` 等。
pub use protocol::{JsonRpcMessage, Request, Response, ResponsePayload, Notification, Error, ErrorCode, Id, Params,
                   StateSnapshot, StateSnapshotFragment, Thermal, ThermalZone, CpuInfo, MemoryInfo, DiskInfo, NetInfo, BpuInfo, PowerInfo,
                   ProtocolError, MAX_MESSAGE_BYTES, JSONRPC_VERSION};
pub use ports::{Collector, SysfsReader, ProcReader, HrutGateway, ShellRunner, ShellOutput, PortError, ShellError};
