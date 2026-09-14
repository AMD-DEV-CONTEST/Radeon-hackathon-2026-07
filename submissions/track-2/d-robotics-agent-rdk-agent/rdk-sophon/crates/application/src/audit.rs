//! 审计日志：每条命令执行记录（来源、方法、参数摘要、结果、耗时）。
//! 通过 mpsc channel 喂给后台写任务。从原 executor/audit.rs 移入 application 层。

use chrono::Utc;
use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct AuditEntry {
    /// ISO-8601 时间戳。
    pub ts: String,
    /// 来源连接标签（如 "tcp:1.2.3.4:7777" / "unix"）。
    pub source: String,
    /// RPC 方法名。
    pub method: String,
    /// 参数摘要：JSON 前 200 字符，避免记录完整密钥。
    pub args: String,
    /// 结果（ok/nonzero/timeout 等）。
    pub outcome: String,
    /// 耗时（毫秒）。
    pub duration_ms: u64,
}

#[derive(Debug, Clone)]
pub struct AuditLog {
    sink: tokio::sync::mpsc::UnboundedSender<AuditEntry>,
}

impl AuditLog {
    pub fn new(sink: tokio::sync::mpsc::UnboundedSender<AuditEntry>) -> Self {
        Self { sink }
    }

    /// 记录一条审计（best-effort：sink 关闭则丢弃）。
    pub fn record(&self, e: AuditEntry) {
        let _ = self.sink.send(e);
    }

    /// 当前 UTC 时间戳（RFC3339，秒精度）。
    pub fn now_ts() -> String {
        Utc::now().to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
    }
}
