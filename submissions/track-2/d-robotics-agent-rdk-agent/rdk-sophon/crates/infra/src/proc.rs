//! RealProcReader：真实读 /proc 的 ProcReader 实现。

use async_trait::async_trait;
use shared::ports::ProcReader;
use std::path::Path;

pub struct RealProcReader;

impl RealProcReader {
    pub fn new() -> Self {
        Self
    }
}

impl Default for RealProcReader {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl ProcReader for RealProcReader {
    /// 读整个 /proc 文件内容。文件不存在返回 None。
    async fn read(&self, path: &str) -> Option<String> {
        std::fs::read_to_string(Path::new(path)).ok()
    }
}
