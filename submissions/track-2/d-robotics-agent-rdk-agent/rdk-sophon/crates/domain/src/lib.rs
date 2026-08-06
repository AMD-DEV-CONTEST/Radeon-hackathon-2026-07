//! domain 领域层：纯领域服务、策略，以及硬件采集器。零 IO 依赖（采集器通过 ports 注入读取）。
//!
//! 子模块：
//! - `collectors`：6 个硬件采集器，构造期注入 Reader，实现 ports::Collector。
//! - 顶层服务：StateService/AlertService/TelemetryService/CommandPolicy。
//!
//! 依赖方向：shared → domain。domain 不依赖 application/infra。

pub mod collectors;

mod state_service;
mod alert_service;
mod telemetry_service;
mod command_policy;
mod alert_rules;

pub use state_service::StateService;
pub use alert_service::AlertService;
pub use telemetry_service::TelemetryService;
pub use command_policy::{CommandPolicy, default_deny_patterns};
pub use alert_rules::{AlertThresholds, AlertRule, AlertKind};

// 采集器便捷重导出。
pub use collectors::{ThermalCollector, CpuCollector, MemoryCollector, DiskCollector, NetCollector, BpuCollector};
