use serde::Serialize;
use std::path::PathBuf;
use std::process::Stdio;
use tokio::process::Command;
use tokio::time::{timeout, Duration};
use crate::win_process::HideConsoleExt;

#[derive(Debug, Serialize)]
pub struct TerminalCommandResult {
    pub command: String,
    pub cwd: String,
    pub stdout: String,
    pub stderr: String,
    pub exit_code: Option<i32>,
    pub timed_out: bool,
}

fn resolved_cwd(cwd: Option<String>) -> PathBuf {
    cwd.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(PathBuf::from(trimmed))
        }
    })
    .filter(|path| path.is_dir())
    .unwrap_or_else(|| std::env::current_dir().unwrap_or_else(|_| PathBuf::from(".")))
}

#[tauri::command]
pub async fn run_terminal_command(
    command: String,
    cwd: Option<String>,
) -> Result<TerminalCommandResult, String> {
    let command = command.trim().to_string();
    if command.is_empty() {
        return Err("No command provided.".to_string());
    }

    let cwd_path = resolved_cwd(cwd);
    let cwd_display = cwd_path.to_string_lossy().to_string();

    #[cfg(target_os = "windows")]
    let mut child_cmd = {
        let mut cmd = Command::new("powershell.exe");
        cmd.hide_console();
        cmd.args([
            "-NoLogo",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            &command,
        ]);
        cmd
    };

    #[cfg(not(target_os = "windows"))]
    let mut child_cmd = {
        let mut cmd = Command::new("sh");
        cmd.hide_console();
        cmd.args(["-lc", &command]);
        cmd
    };

    child_cmd
        .current_dir(&cwd_path)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);

    let child = child_cmd
        .spawn()
        .map_err(|error| format!("Failed to launch terminal command: {error}"))?;

    match timeout(Duration::from_secs(30), child.wait_with_output()).await {
        Ok(Ok(output)) => Ok(TerminalCommandResult {
            command,
            cwd: cwd_display,
            stdout: String::from_utf8_lossy(&output.stdout).to_string(),
            stderr: String::from_utf8_lossy(&output.stderr).to_string(),
            exit_code: output.status.code(),
            timed_out: false,
        }),
        Ok(Err(error)) => Err(format!("Terminal command failed: {error}")),
        Err(_) => Ok(TerminalCommandResult {
            command,
            cwd: cwd_display,
            stdout: String::new(),
            stderr: "Command timed out after 30 seconds.".to_string(),
            exit_code: None,
            timed_out: true,
        }),
    }
}
