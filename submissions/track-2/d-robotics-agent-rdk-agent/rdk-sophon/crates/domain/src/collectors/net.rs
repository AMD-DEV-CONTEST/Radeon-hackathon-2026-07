//! 网络采集器：从 /proc/net/dev 取每网卡收发字节，从 sysfs 取 up/down、MAC、地址。

use std::sync::Arc;

use async_trait::async_trait;
use shared::ports::{Collector, ProcReader, SysfsReader};
use shared::protocol::{NetInfo, StateSnapshotFragment};

pub struct NetCollector {
    proc_r: Arc<dyn ProcReader>,
    sysfs: Arc<dyn SysfsReader>,
}

impl NetCollector {
    pub fn new(proc_r: Arc<dyn ProcReader>, sysfs: Arc<dyn SysfsReader>) -> Self {
        Self { proc_r, sysfs }
    }
}

#[async_trait]
impl Collector for NetCollector {
    fn name(&self) -> &'static str {
        "net"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        let dev = self.proc_r.read("/proc/net/dev").await?;
        let mut out = Vec::new();
        // /proc/net/dev 头两行是表头，从第三行起是接口数据。
        for line in dev.lines().skip(2) {
            let Some((name, rest)) = line.split_once(':') else { continue };
            let name = name.trim();
            if name == "lo" {
                continue;
            }
            let nums: Vec<u64> = rest
                .split_whitespace()
                .filter_map(|t| t.parse::<u64>().ok())
                .collect();
            if nums.len() < 16 {
                continue;
            }
            let rx_bytes = nums[0];
            let tx_bytes = nums[8];
            let (up, mac, addrs) = self.iface_meta(name).await;
            out.push(NetInfo {
                name: name.to_string(),
                up,
                mac,
                addrs,
                rx_bytes,
                tx_bytes,
            });
        }
        if out.is_empty() {
            None
        } else {
            Some(StateSnapshotFragment::Net(out))
        }
    }
}

impl NetCollector {
    async fn iface_meta(&self, name: &str) -> (bool, Option<String>, Vec<String>) {
        let base = format!("/sys/class/net/{name}");
        let up = self
            .sysfs
            .read_first_line(&format!("{base}/operstate"))
            .await
            .map(|s| s == "up")
            .unwrap_or(false);
        let mac = self.sysfs.read_first_line(&format!("{base}/address")).await;
        let addrs = self.read_addrs().await;
        (up, mac, addrs)
    }

    /// 从 /proc/net/fib_trie 取本机地址（best-effort，非按接口分组）。
    async fn read_addrs(&self) -> Vec<String> {
        let mut addrs = Vec::new();
        if let Some(s) = self.proc_r.read("/proc/net/fib_trie").await {
            for line in s.lines() {
                let t = line.trim();
                if let Some(rest) = t.strip_prefix("Local:") {
                    let ip = rest.trim();
                    if !ip.is_empty() {
                        addrs.push(ip.to_string());
                    }
                }
            }
        }
        addrs.dedup();
        addrs
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;
    use testkit::common::{FakeProcReader, FakeSysfsReader};

    #[tokio::test]
    async fn parses_dev_and_skips_lo() {
        // /proc/net/dev 含 lo 与 wlan0；lo 跳过，wlan0 保留。
        let mut proc_files = HashMap::new();
        proc_files.insert("/proc/net/dev".into(), "Inter-|   Receive |  Transmit\n face |bytes packets errs drop fifo frame compressed multicast|bytes packets errs drop fifo colls carrier compressed\n    lo:       0       0    0    0    0     0          0         0        0       0    0    0    0     0       0          0\n  wlan0: 304664629       0    0    0    0     0          0         0  1410732       0    0    0    0     0       0          0\n".into());
        proc_files.insert("/proc/net/fib_trie".into(), "Local: 192.168.128.10\n".into());
        let mut sys_files = HashMap::new();
        sys_files.insert("/sys/class/net/wlan0/operstate".into(), "up".into());
        sys_files.insert("/sys/class/net/wlan0/address".into(), "18:ce:df:79:40:53".into());
        let c = NetCollector::new(
            Arc::new(FakeProcReader { files: proc_files }),
            Arc::new(FakeSysfsReader { files: sys_files, dirs: HashMap::new() }),
        );
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Net(nics) => {
                assert_eq!(nics.len(), 1);
                assert_eq!(nics[0].name, "wlan0");
                assert!(nics[0].up);
                assert_eq!(nics[0].rx_bytes, 304664629);
                assert_eq!(nics[0].tx_bytes, 1410732);
                assert_eq!(nics[0].mac.as_deref(), Some("18:ce:df:79:40:53"));
            }
            _ => panic!("应为 Net 片段"),
        }
    }

    #[tokio::test]
    async fn missing_returns_none() {
        let c = NetCollector::new(
            Arc::new(FakeProcReader::default()),
            Arc::new(FakeSysfsReader::default()),
        );
        assert!(c.collect().await.is_none());
    }
}
