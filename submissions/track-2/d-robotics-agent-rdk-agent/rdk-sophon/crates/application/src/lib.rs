//! application 应用层：用例编排。调 domain 领域服务 + ports trait。
//!
//! - RpcDispatcher：JSON-RPC 消息分发到对应用例，把 domain 返回的领域类型用 serde_json::to_value 转成 Value（从原 executor dispatch 移）
//! - CollectionOrchestrator：遍历 Vec<Box<dyn Collector>> 组装 StateSnapshot（从原 executor collect_all 移，消除硬编码 6 调用）
//! - SessionService：单连接驱动，select! 并发读请求/转发广播（从原 daemon session.rs 移）
//! - AuditLog：审计日志通道（从原 executor audit 移）
//!
//! 依赖方向：protocol/ports/domain/collectors/transport → application。
//! application 不依赖 infra/daemon/client。

mod rpc_dispatcher;
mod collection_orchestrator;
mod session_service;
mod audit;

pub use rpc_dispatcher::{RpcDispatcher, DispatchOutcome};
pub use collection_orchestrator::CollectionOrchestrator;
pub use session_service::{run_session, Broadcaster};
pub use audit::{AuditEntry, AuditLog};
