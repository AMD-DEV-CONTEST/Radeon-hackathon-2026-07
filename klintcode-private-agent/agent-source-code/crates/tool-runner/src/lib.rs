//! Command template whitelist and controlled process execution.
//! The model cannot execute arbitrary commands.

mod policy;

pub use policy::*;

use anyhow::Result;
use std::time::Duration;
use thiserror::Error;
use tokio::process::Command;
use tracing::info;

#[derive(Debug, Error)]
pub enum ToolError {
    #[error("Command not in whitelist: {command}")]
    NotWhitelisted { command: String },
    #[error("Command timed out after {seconds}s")]
    Timeout { seconds: u64 },
    #[error("Command failed with exit code {code}: {stderr}")]
    ExecFailed { code: i32, stderr: String },
    #[error("Shell operators not allowed")]
    ShellOperators,
}

/// Result of running a tool command
#[derive(Debug, Clone)]
pub struct ToolResult {
    pub command: String,
    pub exit_code: i32,
    pub stdout: String,
    pub stderr: String,
    pub elapsed_secs: f64,
}

/// Execute a whitelisted command with timeout.
pub async fn execute_command(
    command: &str,
    args: &[&str],
    cwd: &std::path::Path,
    timeout_secs: u64,
) -> Result<ToolResult, ToolError> {
    let full = format!("{} {}", command, args.join(" "));

    info!(command = %full, "Executing tool command");
    let start = std::time::Instant::now();

    let output = tokio::time::timeout(
        Duration::from_secs(timeout_secs),
        Command::new(command).args(args).current_dir(cwd).output(),
    )
    .await
    .map_err(|_| ToolError::Timeout {
        seconds: timeout_secs,
    })?
    .map_err(|e| ToolError::ExecFailed {
        code: -1,
        stderr: e.to_string(),
    })?;

    let elapsed = start.elapsed().as_secs_f64();
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    let code = output.status.code().unwrap_or(-1);

    Ok(ToolResult {
        command: full,
        exit_code: code,
        stdout,
        stderr,
        elapsed_secs: elapsed,
    })
}
