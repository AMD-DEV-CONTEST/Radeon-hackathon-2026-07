//! 文件系统统计（statvfs）。仅 Linux 提供真实实现，非 Linux 返回 None。
//! 从原 collectors/disk.rs 的 FFI 提取到 infra 层。

/// statvfs 解析结果：块大小、总块、空闲块、可用块。
#[derive(Debug, Clone)]
pub struct StatvfsResult {
    pub block_size: u64,
    pub blocks: u64,
    pub blocks_free: u64,
    pub blocks_avail: u64,
}

/// 对给定挂载点做 statvfs。失败（非 Linux 或路径无效）返回 None。
pub fn statvfs_of(path: &str) -> Option<StatvfsResult> {
    #[cfg(target_os = "linux")]
    {
        use std::ffi::CString;
        let c = CString::new(path).ok()?;
        let mut s: libc::statvfs = unsafe { std::mem::zeroed() };
        // SAFETY: cstr NUL 结尾；statvfs 写入本地栈结构。
        let rc = unsafe { libc::statvfs(c.as_ptr(), &mut s) };
        if rc != 0 {
            return None;
        }
        Some(StatvfsResult {
            block_size: s.f_bsize as u64,
            blocks: s.f_blocks as u64,
            blocks_free: s.f_bfree as u64,
            blocks_avail: s.f_bavail as u64,
        })
    }
    #[cfg(not(target_os = "linux"))]
    {
        let _ = path;
        None
    }
}
