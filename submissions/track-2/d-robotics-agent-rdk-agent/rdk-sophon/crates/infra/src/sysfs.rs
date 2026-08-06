//! RealSysfsReader：真实读 /sys 的 SysfsReader 实现。
//! 所有读操作都是 best-effort，文件缺失返回 None，不 panic。

use async_trait::async_trait;
use shared::ports::SysfsReader;
use std::path::Path;

/// 真实 sysfs 读取器，构造无状态，可廉价克隆（这里不需要 Clone，只读）。
pub struct RealSysfsReader;

impl RealSysfsReader {
    pub fn new() -> Self {
        Self
    }
}

impl Default for RealSysfsReader {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl SysfsReader for RealSysfsReader {
    /// 列举目录下条目名。目录不存在返回 io::Error。
    async fn read_dir(&self, path: &str) -> std::io::Result<Vec<String>> {
        // std::fs::read_dir 是阻塞的，但 sysfs 目录通常很小且读取极快，
        // 这里直接同步读。如果未来发现阻塞 runtime，可换 spawn_blocking。
        let entries = std::fs::read_dir(Path::new(path))?;
        let mut names = Vec::new();
        for entry in entries.flatten() {
            names.push(entry.file_name().to_string_lossy().to_string());
        }
        Ok(names)
    }

    /// 读文件首行并 trim。文件不存在或读取失败返回 None。
    async fn read_first_line(&self, path: &str) -> Option<String> {
        let s = std::fs::read_to_string(Path::new(path)).ok()?;
        Some(s.lines().next()?.trim().to_string())
    }

    /// 读文件首个空白 token 解析为 i64。失败返回 None。
    async fn read_int(&self, path: &str) -> Option<i64> {
        let s = self.read_first_line(path).await?;
        s.split_whitespace().next()?.parse::<i64>().ok()
    }
}
