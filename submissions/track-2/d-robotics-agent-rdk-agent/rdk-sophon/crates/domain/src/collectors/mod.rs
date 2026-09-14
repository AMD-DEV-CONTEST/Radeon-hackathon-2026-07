//! 采集器层（domain）：6 个硬件采集器，各自 struct 化，构造期注入 Reader trait，
//! 实现 ports::Collector。返回 protocol::StateSnapshotFragment，由 Orchestrator 组装。
//!
//! 每个采集器独立、best-effort：读取失败返回 None，绝不 panic，绝不拖垮其他采集器。
//! 依赖 ports 的 SysfsReader/ProcReader/HrutGateway trait，测试时可注入假实现在 Mac 上跑。

mod thermal;
mod cpu;
mod memory;
mod disk;
mod net;
mod bpu;

pub use thermal::ThermalCollector;
pub use cpu::CpuCollector;
pub use memory::MemoryCollector;
pub use disk::DiskCollector;
pub use net::NetCollector;
pub use bpu::BpuCollector;
