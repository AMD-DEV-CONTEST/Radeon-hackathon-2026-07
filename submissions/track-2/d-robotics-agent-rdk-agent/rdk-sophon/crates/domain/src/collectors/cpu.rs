//! CPU 采集器：loadavg 来自 /proc/loadavg；各核利用率来自两帧 /proc/stat（jiffies）；
//! 各核频率来自 sysfs cpufreq policyN/scaling_cur_freq。

use std::sync::Arc;
use std::time::Duration;

use async_trait::async_trait;
use shared::ports::{Collector, ProcReader, SysfsReader};
use shared::protocol::{CpuInfo, StateSnapshotFragment};

pub struct CpuCollector {
    proc_r: Arc<dyn ProcReader>,
    sysfs: Arc<dyn SysfsReader>,
}

impl CpuCollector {
    pub fn new(proc_r: Arc<dyn ProcReader>, sysfs: Arc<dyn SysfsReader>) -> Self {
        Self { proc_r, sysfs }
    }

    async fn gather(&self) -> Option<CpuInfo> {
        let load_avg = self.load_avg().await;
        let core_usage = self.core_usage_sampled().await;
        let core_freq_mhz = self.core_freqs().await;
        if load_avg.is_none() && core_usage.is_none() && core_freq_mhz.is_none() {
            None
        } else {
            Some(CpuInfo {
                load_avg,
                core_usage: core_usage.unwrap_or_default(),
                core_freq_mhz: core_freq_mhz.unwrap_or_default(),
            })
        }
    }

    async fn load_avg(&self) -> Option<Vec<f64>> {
        let s = self.proc_r.read("/proc/loadavg").await?;
        let first_line = s.lines().next()?;
        let parts: Vec<&str> = first_line.split_whitespace().collect();
        if parts.len() < 3 {
            return None;
        }
        Some(vec![
            parts[0].parse().ok()?,
            parts[1].parse().ok()?,
            parts[2].parse().ok()?,
        ])
    }

    /// 用两帧 /proc/stat（间隔 ~100ms）算各核 busy%。
    async fn core_usage_sampled(&self) -> Option<Vec<f64>> {
        let s1 = self.parse_cpu_lines().await?;
        // tokio::time::sleep 不阻塞 runtime（替换原 std::thread::sleep）。
        tokio::time::sleep(Duration::from_millis(100)).await;
        let s2 = self.parse_cpu_lines().await?;
        let mut out = Vec::with_capacity(s1.len());
        for (name, a) in &s1 {
            if name == "cpu" {
                continue;
            }
            if let Some((_, b)) = s2.iter().find(|(n, _)| n == name) {
                let (busy_a, total_a) = jiffies(a);
                let (busy_b, total_b) = jiffies(b);
                let dt = total_b - total_a;
                if dt > 0.0 {
                    out.push(((busy_b - busy_a) / dt) * 100.0);
                } else {
                    out.push(0.0);
                }
            }
        }
        if out.is_empty() {
            None
        } else {
            Some(out)
        }
    }

    async fn parse_cpu_lines(&self) -> Option<Vec<(String, Vec<u64>)>> {
        let s = self.proc_r.read("/proc/stat").await?;
        let mut rows = Vec::new();
        for line in s.lines() {
            let mut it = line.split_whitespace();
            let Some(name) = it.next() else { continue };
            if !name.starts_with("cpu") {
                continue;
            }
            let vals: Vec<u64> = it.filter_map(|v| v.parse().ok()).collect();
            rows.push((name.to_string(), vals));
        }
        if rows.is_empty() {
            None
        } else {
            Some(rows)
        }
    }

    async fn core_freqs(&self) -> Option<Vec<f64>> {
        let root = "/sys/devices/system/cpu/cpufreq";
        let names = self.sysfs.read_dir(root).await.ok()?;
        let mut freqs = Vec::new();
        for name in names {
            if name.starts_with("policy") {
                let cur = format!("{root}/{name}/scaling_cur_freq");
                if let Some(khz) = self.sysfs.read_int(&cur).await {
                    freqs.push(khz as f64 / 1000.0);
                }
            }
        }
        if freqs.is_empty() {
            None
        } else {
            Some(freqs)
        }
    }
}

#[async_trait]
impl Collector for CpuCollector {
    fn name(&self) -> &'static str {
        "cpu"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        self.gather().await.map(StateSnapshotFragment::Cpu)
    }
}

/// (busy, total) jiffies。user+nice+system+irq+softirq+steal 为 busy；total = busy + idle + iowait。
fn jiffies(v: &[u64]) -> (f64, f64) {
    let idx = |i: usize| v.get(i).copied().unwrap_or(0) as f64;
    let user = idx(0);
    let nice = idx(1);
    let system = idx(2);
    let idle = idx(3);
    let iowait = idx(4);
    let irq = idx(5);
    let softirq = idx(6);
    let steal = idx(7);
    let busy = user + nice + system + irq + softirq + steal;
    let total = busy + idle + iowait;
    (busy, total)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;
    use testkit::common::{FakeProcReader, FakeSysfsReader};

    #[tokio::test]
    async fn parses_loadavg_and_freq() {
        // loadavg "1.87 2.40 1.17" + cpufreq 1500000kHz → 1500MHz。
        let mut proc_files = HashMap::new();
        proc_files.insert("/proc/loadavg".into(), "1.87 2.40 1.17 3/200 12345\n".into());
        proc_files.insert("/proc/stat".into(), "cpu  1 1 1 1 0 0 0 0 0 0\ncpu0 1 1 1 1 0 0 0 0 0 0\n".into());
        let mut sys_files = HashMap::new();
        sys_files.insert("/sys/devices/system/cpu/cpufreq/policy0/scaling_cur_freq".into(), "1500000".into());
        let mut sys_dirs = HashMap::new();
        sys_dirs.insert("/sys/devices/system/cpu/cpufreq".into(), vec!["policy0".into()]);
        let c = CpuCollector::new(
            Arc::new(FakeProcReader { files: proc_files }),
            Arc::new(FakeSysfsReader { files: sys_files, dirs: sys_dirs }),
        );
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Cpu(ci) => {
                assert_eq!(ci.load_avg, Some(vec![1.87, 2.40, 1.17]));
                assert_eq!(ci.core_freq_mhz, vec![1500.0]);
            }
            _ => panic!("应为 Cpu 片段"),
        }
    }

    #[tokio::test]
    async fn missing_returns_none() {
        let c = CpuCollector::new(
            Arc::new(FakeProcReader::default()),
            Arc::new(FakeSysfsReader::default()),
        );
        // loadavg 与 freq 都无；cpu usage 因无 /proc/stat 也无。
        assert!(c.collect().await.is_none());
    }
}
