//! 告警阈值与规则的领域模型。纯数据，无 IO。
//! 阈值语义从原 daemon config.rs 的 AlertsConfig 提取为独立领域类型，便于单测。

use serde::{Deserialize, Serialize};

/// 告警阈值集合。daemon 配置里的 [alerts] 映射到本类型。
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AlertThresholds {
    /// 温度告警阈值（°C），任一 thermal zone 超过即触发。
    pub temp_c: f64,
    /// 磁盘使用率告警阈值（%），任一真实文件系统超过即触发。
    pub disk_usage_pct: f64,
}

impl Default for AlertThresholds {
    fn default() -> Self {
        Self {
            temp_c: 75.0,
            disk_usage_pct: 90.0,
        }
    }
}

/// 告警种类：当前为温度与磁盘。新增种类时在此枚举扩展。
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AlertKind {
    Thermal,
    Disk,
}

/// 单条告警规则判定结果。AlertService::evaluate 返回 Vec<AlertRule>，
/// 由上层（application 或 daemon）转成 JSON-RPC notification 发出。
#[derive(Debug, Clone)]
pub struct AlertRule {
    pub kind: AlertKind,
    /// 触发告警的实体名（温度 zone 名 / 磁盘挂载点）。
    pub target: String,
    /// 当前值（温度 °C 或使用率 %）。
    pub current: f64,
    /// 阈值。
    pub threshold: f64,
}
