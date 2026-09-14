//! BPU（Horizon 地平线 Brain Processing Unit）采集器：best-effort 调 hrut_* 工具解析。
//! 工具调用通过 HrutGateway 注入，非 RDK 板或无工具时返回 None，daemon 省略 bpu 字段。

use std::sync::Arc;

use async_trait::async_trait;
use shared::ports::{Collector, HrutGateway};
use shared::protocol::{BpuInfo, StateSnapshotFragment};

pub struct BpuCollector {
    hrut: Arc<dyn HrutGateway>,
}

impl BpuCollector {
    pub fn new(hrut: Arc<dyn HrutGateway>) -> Self {
        Self { hrut }
    }

    async fn gather(&self) -> Option<BpuInfo> {
        let util = self.utilisation().await;
        let temp = self.temp().await;
        let freq = self.freq().await;
        if util.is_none() && temp.is_none() && freq.is_none() {
            None
        } else {
            Some(BpuInfo {
                utilisation_pct: util,
                temp_c: temp,
                freq_mhz: freq,
            })
        }
    }

    async fn utilisation(&self) -> Option<f64> {
        let out = self.hrut.run("hrut_bpuinfo").await?;
        find_first_percent(&out)
    }

    async fn temp(&self) -> Option<f64> {
        // 先试 hrut_sensors，失败再试 hrut_thermal。
        let out = match self.hrut.run("hrut_sensors").await {
            Some(s) => s,
            None => self.hrut.run("hrut_thermal").await?,
        };
        for line in out.lines() {
            if line.to_lowercase().contains("temp") {
                if let Some(n) = find_first_number(line) {
                    return Some(n);
                }
            }
        }
        None
    }

    async fn freq(&self) -> Option<f64> {
        let out = self.hrut.run("hrut_bpuinfo").await?;
        for line in out.lines() {
            if line.to_lowercase().contains("freq") {
                if let Some(n) = find_first_number(line) {
                    return Some(n);
                }
            }
        }
        None
    }
}

#[async_trait]
impl Collector for BpuCollector {
    fn name(&self) -> &'static str {
        "bpu"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        self.gather().await.map(StateSnapshotFragment::Bpu)
    }
}

/// 在字符串里找首个 0..=100 的百分比数。
fn find_first_percent(s: &str) -> Option<f64> {
    for tok in s.split_whitespace() {
        let t = tok.trim_end_matches('%');
        if let Ok(n) = t.parse::<f64>() {
            if (0.0..=100.0).contains(&n) {
                return Some(n);
            }
        }
    }
    None
}

/// 在字符串里找首个数字。
fn find_first_number(s: &str) -> Option<f64> {
    s.split_whitespace().find_map(|t| {
        t.trim_end_matches(|c: char| !c.is_ascii_digit() && c != '.' && c != '-')
            .parse::<f64>()
            .ok()
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use testkit::common::make_fake_hrut;

    #[tokio::test]
    async fn parses_bpu_util_and_freq() {
        // 假 hrut_bpuinfo 含 30% 与 1500 freq。
        let c = BpuCollector::new(Arc::new(make_fake_hrut()));
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Bpu(b) => {
                assert_eq!(b.utilisation_pct, Some(30.0));
                assert_eq!(b.freq_mhz, Some(1500.0));
                assert_eq!(b.temp_c, Some(55.0));
            }
            _ => panic!("应为 Bpu 片段"),
        }
    }

    #[tokio::test]
    async fn no_tools_returns_none() {
        // 无 hrut 工具 → None。
        let c = BpuCollector::new(Arc::new(testkit::common::FakeHrutGateway::default()));
        assert!(c.collect().await.is_none());
    }
}
