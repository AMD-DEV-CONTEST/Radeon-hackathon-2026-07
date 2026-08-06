//! 磁盘采集器：从 /proc/mounts 取真实文件系统，statvfs 查用量。
//! statvfs FFI 已移至 infra crate，本采集器只调 infra::statvfs_of（通过 trait 注入的可测性见测试）。

use std::sync::Arc;

use async_trait::async_trait;
use shared::ports::{Collector, ProcReader};
use shared::protocol::{DiskInfo, StateSnapshotFragment};

/// 注入 statvfs 函数指针，便于测试时替换。生产用 infra::statvfs_of。
type StatvfsFn = fn(&str) -> Option<infra::StatvfsResult>;

pub struct DiskCollector {
    proc_r: Arc<dyn ProcReader>,
    statvfs_fn: StatvfsFn,
}

impl DiskCollector {
    /// 生产构造：用真实 infra::statvfs_of。
    pub fn new(proc_r: Arc<dyn ProcReader>) -> Self {
        Self { proc_r, statvfs_fn: infra::statvfs_of }
    }

    /// 测试构造：注入假 statvfs 函数。
    pub fn with_statvfs(proc_r: Arc<dyn ProcReader>, statvfs_fn: StatvfsFn) -> Self {
        Self { proc_r, statvfs_fn }
    }
}

#[async_trait]
impl Collector for DiskCollector {
    fn name(&self) -> &'static str {
        "disk"
    }

    async fn collect(&self) -> Option<StateSnapshotFragment> {
        let mounts = self.proc_r.read("/proc/mounts").await?;
        let mut out = Vec::new();
        for line in mounts.lines() {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() < 3 {
                continue;
            }
            let fs_type = parts[2];
            let mount = parts[1];
            if is_pseudo(fs_type, mount) {
                continue;
            }
            let Some(info) = (self.statvfs_fn)(mount) else { continue };
            let total = info.block_size * info.blocks;
            let free = info.block_size * info.blocks_free;
            let avail = info.block_size * info.blocks_avail;
            let used = total - free;
            let usage_pct = if total > 0 {
                (used as f64 / total as f64) * 100.0
            } else {
                0.0
            };
            out.push(DiskInfo {
                mount: mount.to_string(),
                fs_type: fs_type.to_string(),
                total_bytes: total,
                used_bytes: used,
                free_bytes: avail,
                usage_pct,
            });
        }
        if out.is_empty() {
            None
        } else {
            Some(StateSnapshotFragment::Disks(out))
        }
    }
}

/// 判定伪文件系统。proc/sysfs/devtmpfs/tmpfs 等不计入磁盘统计。
fn is_pseudo(fs_type: &str, mount: &str) -> bool {
    const PSEUDO: &[&str] = &[
        "proc", "sysfs", "devtmpfs", "tmpfs", "devpts", "cgroup", "cgroup2",
        "pstore", "bpf", "tracefs", "debugfs", "fusectl", "mqueue", "hugetlbfs",
        "ramfs", "configfs", "securityfs", "autofs", "rpc_pipefs",
    ];
    PSEUDO.contains(&fs_type) || mount.starts_with("/sys/") || mount.starts_with("/proc/")
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;
    use std::sync::Arc;
    use testkit::common::FakeProcReader;
    use infra::StatvfsResult;

    /// 假 statvfs：根分区 100 块 × 1024，用 50。
    fn fake_statvfs(path: &str) -> Option<StatvfsResult> {
        if path == "/" {
            Some(StatvfsResult { block_size: 1024, blocks: 100, blocks_free: 50, blocks_avail: 45 })
        } else {
            None
        }
    }

    #[tokio::test]
    async fn parses_mounts_and_skips_pseudo() {
        // mounts 含 ext4 真实根分区 + proc/tmpfs 伪文件系统，应只保留 ext4。
        let mut files = HashMap::new();
        files.insert("/proc/mounts".into(), "/dev/root / ext4 rw 0 0\nproc /proc proc rw 0 0\ntmpfs /tmp tmpfs rw 0 0\n".into());
        let c = DiskCollector::with_statvfs(Arc::new(FakeProcReader { files }), fake_statvfs);
        let frag = c.collect().await.unwrap();
        match frag {
            StateSnapshotFragment::Disks(disks) => {
                assert_eq!(disks.len(), 1);
                assert_eq!(disks[0].mount, "/");
                assert_eq!(disks[0].fs_type, "ext4");
                assert_eq!(disks[0].total_bytes, 100 * 1024);
                assert_eq!(disks[0].used_bytes, 50 * 1024);
                assert!(disks[0].usage_pct > 49.0 && disks[0].usage_pct < 51.0);
            }
            _ => panic!("应为 Disks 片段"),
        }
    }

    #[tokio::test]
    async fn missing_returns_none() {
        let c = DiskCollector::with_statvfs(Arc::new(FakeProcReader::default()), fake_statvfs);
        assert!(c.collect().await.is_none());
    }
}
