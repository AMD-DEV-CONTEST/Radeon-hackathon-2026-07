// Bridges scripts/determinex_toolchain_installer.py -- the per-language oracle toolchain
// enablement flow. Listing is a fast, read-only probe (shutil.which per language). Installing
// actually runs winget/a portable-zip extraction, then RE-CHECKS the real oracle afterward
// (never trusts the installer's own exit code as proof) -- same "never lie about what's
// available" contract as every oracle in this app.
//
// Ryan, direct instruction 2026-07-27: "ensure the system knows what tool chains it needs for
// everything and gives the user the ability to download and use either upon installation or as
// needed during a project they open and work on." The Python side already existed
// (determinex_toolchain_installer.py, built 2026-07-22) with zero frontend surface -- this is
// the missing bridge, mirroring agent_registry.rs's pattern for scripts/determinex_agents.py.

// Python is resolved through `ipc_hive::resolve_python_exe()`, never `Command::new("python")`.
//
// That resolver exists for a specific reason: on Windows, PATH `python` is very
// often the Microsoft Store AppExecLink stub, which does not run Python -- it opens
// the Store. It also prefers the repo venv, so the interpreter that has the
// project's dependencies is the one used. Ten call sites across six files bypassed
// it and used bare `python`, which worked only on machines where PATH happened to
// resolve to a real interpreter.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::PathBuf;
use std::process::Command;
use std::time::Duration;

use crate::project_audit::run_with_timeout;
use crate::win_process::HideConsoleExt;

const TOOLCHAIN_SCRIPT: &str = "scripts/determinex_toolchain_installer.py";

// Python's install_toolchain() emits a ToolchainInstallResult dataclass via dataclasses.asdict()
// -- plain snake_case JSON, same asymmetric rename as agent_registry.rs's CodingAgentInfo (see
// that file's comment for why: Python's own field names aren't negotiable there, and a single
// rename_all would make deserialization expect the wrong casing from the JSON that's actually
// on the wire).
#[derive(Debug, Serialize, Deserialize, Clone)]
#[serde(rename_all(serialize = "camelCase", deserialize = "snake_case"))]
pub struct ToolchainInstallResult {
    pub language: String,
    pub already_available: bool,
    pub attempted: bool,
    pub installer: String,
    pub command: String,
    pub succeeded: bool,
    #[serde(default)]
    pub output: String,
    #[serde(default)]
    pub notes: Vec<String>,
}

fn locate_repo_root() -> Option<PathBuf> {
    let mut cur = std::env::current_dir().ok();
    while let Some(c) = cur.as_deref() {
        if c.join(TOOLCHAIN_SCRIPT).is_file() {
            return Some(c.to_path_buf());
        }
        cur = c.parent().map(|p| p.to_path_buf());
    }
    None
}

/// Fast probe (shutil.which per registered oracle language) -- language -> available bool.
/// Read-only, no install attempted. This is what a setup wizard step or a "this project needs
/// Rust" banner should call first to decide whether to offer an install button at all.
#[tauri::command]
pub async fn list_toolchains() -> Result<HashMap<String, bool>, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({TOOLCHAIN_SCRIPT} missing)"))?;

    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(TOOLCHAIN_SCRIPT)?;
    cmd.arg("list");
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(15))
        .map_err(|e| format!("could not run toolchain installer: {e}"))?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("toolchain list exited non-zero: {stderr}"));
    }
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "toolchain list")
}

/// Installs the toolchain for one oracle language (winget on Windows, portable-zip fallback for
/// languages with no winget package, e.g. GnuCOBOL). Bounded to 10 minutes -- these are real
/// package downloads, not instant. `succeeded` reflects a RE-CHECKED oracle probe taken after
/// the install attempt, never the installer's own exit code alone; a PATH change frequently
/// doesn't take effect in the current process even when the install itself worked, and that
/// case is reported honestly via `notes`, not silently as success.
#[tauri::command]
pub async fn install_toolchain(language: String) -> Result<ToolchainInstallResult, String> {
    let root = locate_repo_root()
        .ok_or_else(|| format!("could not locate repo root ({TOOLCHAIN_SCRIPT} missing)"))?;

    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = crate::ipc_hive::helper_command(TOOLCHAIN_SCRIPT)?;
    cmd.arg("install");
    cmd.arg(&language);
    cmd.current_dir(&root);

    let output = run_with_timeout(cmd, Duration::from_secs(600))
        .map_err(|e| format!("could not run toolchain install: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    crate::python_json::parse_python_json(&stdout, "toolchain install").map_err(|e| {
        let stderr = String::from_utf8_lossy(&output.stderr);
        format!("{e} (stderr: {stderr})")
    })
}
