//! 温度采集器：读 /sys/class/thermal/thermal_zone*/temp（毫摄氏度）。
//! 从 sysfs 注入读取，返回 StateSnapshotFragment::Thermal。

use std::sync::Arc;

use async_trait::async_trait;
use shared::ports::{Collector, SysfsReader};
use shared::protocol::{StateSnapshotFragment, Thermal, ThermalZone};

pub struct ThermalCollector {
    sysfs: Arc<dyn SysfsReader>,
}

impl ThermalCollector {
    pub fn new(sysfs: Arc<dyn SysfsReader>) -> Self {
        Self { sysfs }
    }
}

#[async_trait]
impl Collector for ThermalCollector {
    fn name(&self) -> &'static str {
        "thermal"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        let root = "/sys/class/thermal";
        let names = self.sysfs.read_dir(root).await.ok()?;
        let mut zones = Vec::new();
        for name in names {
            if !name.starts_with("thermal_zone") {
                continue;
            }
            // thermal_zoneN/temp 与 /type
            let temp_path = format!("{root}/{name}/temp");
            let type_path = format!("{root}/{name}/type");
            let mc = self.sysfs.read_int(&temp_path).await?;
            let label = self
                .sysfs
                .read_first_line(&type_path)
                .await
                .unwrap_or_else(|| name.clone());
            zones.push(ThermalZone {
                name: label,
                temp_c: mc as f64 / 1000.0,
            });
        }
        if zones.is_empty() {
            None
        } else {
            Some(StateSnapshotFragment::Thermal(Thermal { zones }))
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;
    use testkit::common::FakeSysfsReader;

    #[tokio::test]
    async fn parses_thermal_zones() {
        // 两个 zone：52000 与 61000 毫摄氏度 → 52.0 / 61.0 °C。
        let mut files = HashMap::new();
        files.insert("/sys/class/thermal/thermal_zone0/temp".into(), "52000".into());
        files.insert("/sys/class/thermal/thermal_zone0/type".into(), "thermal-cpu".into());
        files.insert("/sys/class/thermal/thermal_zone1/temp".into(), "61000".into());
        files.insert("/sys/class/thermal/thermal_zone1/type".into(), "thermal-ddr".into());
        let mut dirs = HashMap::new();
        dirs.insert(
            "/sys/class/thermal".into(),
            vec!["thermal_zone0".into(), "thermal_zone1".into()],
        );
        let sysfs = FakeSysfsReader { files, dirs };
        let c = ThermalCollector::new(Arc::new(sysfs));
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Thermal(t) => {
                assert_eq!(t.zones.len(), 2);
                assert_eq!(t.zones[0].temp_c, 52.0);
                assert_eq!(t.zones[1].name, "thermal-ddr");
            }
            _ => panic!("应为 Thermal 片段"),
        }
    }

    #[tokio::test]
    async fn empty_dir_returns_none() {
        // 空目录 → None。
        let sysfs = FakeSysfsReader::default();
        let c = ThermalCollector::new(Arc::new(sysfs));
        assert!(c.collect().await.is_none());
    }
}
