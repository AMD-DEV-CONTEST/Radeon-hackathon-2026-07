//! Protocol crate: pure data structures + JSON-RPC 2.0 envelope.
//!
//! No tokio, no IO — daemon and `sophonctl` both depend on this so that local
//! and remote invocations share one wire format.

mod message;
mod snapshot;
mod error;

pub use message::{JsonRpcMessage, Request, Response, ResponsePayload, Notification, Error, ErrorCode, Id, Params};
pub use snapshot::{StateSnapshot, StateSnapshotFragment, Thermal, ThermalZone, CpuInfo, MemoryInfo, DiskInfo, NetInfo, BpuInfo, PowerInfo};
pub use error::ProtocolError;

/// Re-export so downstream crates don't need to declare serde themselves.
pub use serde::{Serialize, Deserialize};

/// Maximum serialised message size accepted over any transport.
/// Guards against a runaway peer exhausting memory on the board.
pub const MAX_MESSAGE_BYTES: usize = 4 * 1024 * 1024;

/// Version tag embedded in every envelope. Mirrors JSON-RPC 2.0.
pub const JSONRPC_VERSION: &str = "2.0";
