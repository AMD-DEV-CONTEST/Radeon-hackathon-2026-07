//! 内存采集器：读 /proc/meminfo（kB 单位）。

use std::sync::Arc;

use async_trait::async_trait;
use shared::ports::{Collector, ProcReader};
use shared::protocol::{MemoryInfo, StateSnapshotFragment};

pub struct MemoryCollector {
    proc_r: Arc<dyn ProcReader>,
}

impl MemoryCollector {
    pub fn new(proc_r: Arc<dyn ProcReader>) -> Self {
        Self { proc_r }
    }
}

#[async_trait]
impl Collector for MemoryCollector {
    fn name(&self) -> &'static str {
        "memory"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        let s = self.proc_r.read("/proc/meminfo").await?;
        let mut total = 0u64;
        let mut avail = 0u64;
        let mut free = 0u64;
        let mut swap_total = 0u64;
        let mut swap_free = 0u64;
        for line in s.lines() {
            let Some((key, val)) = split_kv(line) else { continue };
            match key {
                "MemTotal" => total = val * 1024,
                "MemAvailable" => avail = val * 1024,
                "MemFree" => free = val * 1024,
                "SwapTotal" => swap_total = val * 1024,
                "SwapFree" => swap_free = val * 1024,
                _ => {}
            }
        }
        let used = total.saturating_sub(avail);
        let swap_used = swap_total.saturating_sub(swap_free);
        Some(StateSnapshotFragment::Memory(MemoryInfo {
            total_bytes: total,
            used_bytes: used,
            free_bytes: free,
            swap_total_bytes: swap_total,
            swap_used_bytes: swap_used,
        }))
    }
}

/// 拆 "MemTotal:  1234 kB" → ("MemTotal", 1234)。无效行返回 None。
fn split_kv(line: &str) -> Option<(&str, u64)> {
    let mut it = line.split_whitespace();
    let raw_key = it.next()?;
    let key = raw_key.trim_end_matches(':');
    let raw_val = it.next()?;
    // 忽略可选单位 token（"kB"）
    let val: u64 = raw_val.parse().ok()?;
    Some((key, val))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;
    use testkit::common::FakeProcReader;

    #[tokio::test]
    async fn parses_meminfo() {
        // MemTotal 7424344 kB → used = total - avail。
        let mut files = HashMap::new();
        files.insert("/proc/meminfo".into(), "MemTotal:        7424344 kB\nMemAvailable:    4268000 kB\nMemFree:          1119498 kB\nSwapTotal:             0 kB\nSwapFree:              0 kB\n".into());
        let c = MemoryCollector::new(Arc::new(FakeProcReader { files }));
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Memory(m) => {
                assert_eq!(m.total_bytes, 7424344 * 1024);
                assert_eq!(m.used_bytes, (7424344 - 4268000) * 1024);
                assert_eq!(m.swap_total_bytes, 0);
            }
            _ => panic!("应为 Memory 片段"),
        }
    }

    #[tokio::test]
    async fn missing_returns_none() {
        let c = MemoryCollector::new(Arc::new(FakeProcReader::default()));
        assert!(c.collect().await.is_none());
    }
}
