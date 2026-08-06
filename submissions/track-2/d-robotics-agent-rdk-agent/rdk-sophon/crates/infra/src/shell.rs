//! RealShellRunner：用 tokio::process 执行 sh -c 的 ShellRunner 实现。
//! 从原 executor/shell.rs 的 ShellPolicy::run 提取执行部分。
//! deny 列表/超时值/输出上限的"策略"判定在 domain::CommandPolicy（纯逻辑），
//! 本实现只负责"按给定 timeout 执行给定 cmd"，并截断输出。

use std::process::Stdio;
use std::time::Duration;

use async_trait::async_trait;
use shared::ports::{ShellError, ShellOutput, ShellRunner};
use tokio::io::AsyncReadExt;
use tokio::process::Command;

/// 默认输出截断上限（每路 stdout/stderr）。调用方可在配置里覆盖。
const DEFAULT_MAX_OUTPUT_BYTES: usize = 256 * 1024;

pub struct RealShellRunner {
    max_output_bytes: usize,
}

impl RealShellRunner {
    pub fn new() -> Self {
        Self { max_output_bytes: DEFAULT_MAX_OUTPUT_BYTES }
    }

    /// 用自定义输出上限构造。
    pub fn with_max_output(max_output_bytes: usize) -> Self {
        Self { max_output_bytes }
    }
}

impl Default for RealShellRunner {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl ShellRunner for RealShellRunner {
    async fn run(&self, cmd: &str, timeout: Duration) -> Result<ShellOutput, ShellError> {
        let mut child = Command::new("sh")
            .arg("-c")
            .arg(cmd)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .kill_on_drop(true)
            .spawn()
            .map_err(|e| ShellError::Spawn(e.to_string()))?;

        let mut stdout = child.stdout.take().expect("piped");
        let mut stderr = child.stderr.take().expect("piped");
        let mut out_buf = Vec::new();
        let mut err_buf = Vec::new();
        let max = self.max_output_bytes;

        // 并发读两路输出，避免某路填满管道死锁。整体跑在 timeout 之内。
        let status = match tokio::time::timeout(timeout, async {
            let (o, e) = tokio::join!(
                stdout.read_to_end(&mut out_buf),
                stderr.read_to_end(&mut err_buf),
            );
            let _ = (o, e);
            child.wait().await
        })
        .await
        {
            Ok(s) => s.map_err(|e| ShellError::Wait(e.to_string()))?,
            Err(_) => {
                // 超时：kill_on_drop 会杀掉子进程。
                return Err(ShellError::Timeout { secs: timeout.as_secs() });
            }
        };

        // 截断输出，防止单次执行回传过大。
        if out_buf.len() > max {
            out_buf.truncate(max);
        }
        if err_buf.len() > max {
            err_buf.truncate(max);
        }

        Ok(ShellOutput {
            exit: status.code(),
            stdout: String::from_utf8_lossy(&out_buf).to_string(),
            stderr: String::from_utf8_lossy(&err_buf).to_string(),
        })
    }
}
