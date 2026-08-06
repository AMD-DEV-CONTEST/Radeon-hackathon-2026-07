//! AlertService：阈值告警领域服务。
//! 纯函数：输入 StateSnapshot + AlertThresholds，输出触发的 AlertRule 列表。
//! 不碰 JSON-RPC 或 transport——message 组装在 TelemetryService/上层做。这样便于单测。

use shared::protocol::StateSnapshot;

use crate::alert_rules::{AlertKind, AlertRule, AlertThresholds};

pub struct AlertService;

impl AlertService {
    /// 评估当前快照是否触发任何告警。返回触发的规则列表（可能为空）。
    pub fn evaluate(snap: &StateSnapshot, thresholds: &AlertThresholds) -> Vec<AlertRule> {
        let mut rules = Vec::new();
        // 温度：任一 zone 超过阈值即告警。
        if let Some(t) = &snap.thermal {
            for z in &t.zones {
                if z.temp_c >= thresholds.temp_c {
                    rules.push(AlertRule {
                        kind: AlertKind::Thermal,
                        target: z.name.clone(),
                        current: z.temp_c,
                        threshold: thresholds.temp_c,
                    });
                }
            }
        }
        // 磁盘：任一真实文件系统使用率超过阈值即告警。
        if let Some(disks) = &snap.disks {
            for d in disks {
                if d.usage_pct >= thresholds.disk_usage_pct {
                    rules.push(AlertRule {
                        kind: AlertKind::Disk,
                        target: d.mount.clone(),
                        current: d.usage_pct,
                        threshold: thresholds.disk_usage_pct,
                    });
                }
            }
        }
        rules
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use shared::protocol::{DiskInfo, Thermal, ThermalZone};

    fn snap_with_thermal(temp: f64) -> StateSnapshot {
        StateSnapshot {
            thermal: Some(Thermal {
                zones: vec![ThermalZone { name: "cpu".into(), temp_c: temp }],
            }),
            ..Default::default()
        }
    }

    fn snap_with_disk(pct: f64) -> StateSnapshot {
        StateSnapshot {
            disks: Some(vec![DiskInfo {
                mount: "/".into(),
                fs_type: "ext4".into(),
                total_bytes: 100,
                used_bytes: 50,
                free_bytes: 50,
                usage_pct: pct,
            }]),
            ..Default::default()
        }
    }

    #[test]
    fn thermal_over_threshold_emits_alert() {
        // 80°C 超 75°C 阈值，应产一条 Thermal 告警。
        let snap = snap_with_thermal(80.0);
        let rules = AlertService::evaluate(&snap, &AlertThresholds::default());
        assert_eq!(rules.len(), 1);
        assert_eq!(rules[0].kind, AlertKind::Thermal);
        assert_eq!(rules[0].current, 80.0);
    }

    #[test]
    fn thermal_under_threshold_no_alert() {
        // 60°C 未越阈值，不产告警。
        let snap = snap_with_thermal(60.0);
        let rules = AlertService::evaluate(&snap, &AlertThresholds::default());
        assert!(rules.is_empty());
    }

    #[test]
    fn disk_over_threshold_emits_alert() {
        // 95% 超 90% 阈值，产一条 Disk 告警。
        let snap = snap_with_disk(95.0);
        let rules = AlertService::evaluate(&snap, &AlertThresholds::default());
        assert_eq!(rules.len(), 1);
        assert_eq!(rules[0].kind, AlertKind::Disk);
    }

    #[test]
    fn no_data_no_alert() {
        // 空快照不产告警。
        let snap = StateSnapshot::default();
        let rules = AlertService::evaluate(&snap, &AlertThresholds::default());
        assert!(rules.is_empty());
    }
}
