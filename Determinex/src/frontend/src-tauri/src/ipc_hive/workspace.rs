use serde::Deserialize;
use tauri::State;

use crate::ipc_envelope::Envelope;
use super::{hive_command, project_root, HiveProcessMap};

// ─────────────────────────────────────────────────────────────────────────────
// ENTERPRISE CODEBASE EXPLORER IPC
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Deserialize)]
pub struct ExploreWorkspacePayload {
    pub workspace_path: String,
}

#[derive(Deserialize)]
pub struct DiagnoseWorkspacePayload {
    pub workspace_path: String,
    pub issue: String,
}

#[derive(Deserialize)]
pub struct FixWorkspacePayload {
    pub workspace_path: String,
    pub issue: String,
    #[serde(default)]
    pub out_path: Option<String>,
}

/// Explore an existing codebase: scan files, detect build system, run
/// shadow compilation, and return a diagnostic report.
///
/// This is the enterprise "load workspace" entry point. The frontend calls
/// this when the user opens an existing project (vs creating one from spec).
///
/// Spawns `determinex_hive.py explore --workspace PATH --json` as a subprocess.
/// Returns the full workspace report as JSON.
#[tauri::command]
pub async fn explore_workspace(
    payload: ExploreWorkspacePayload,
    _process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<serde_json::Value>, String> {
    log::info!("[IPC] explore_workspace: {}", payload.workspace_path);

    let root = project_root();

    // Prefer the BUNDLED engine binary; fall back to the repo script only in a dev
    // checkout. This used to require `python <repo>/scripts/determinex_hive.py`
    // unconditionally, so on an installed copy with no repo present it could not
    // run at all -- the shipped app depended on the development tree.
    let (mut cmd, standalone) = hive_command("explore")?;
    log::info!("[IPC] explore_workspace via {}", if standalone { "bundled engine" } else { "repo script" });
    let output = cmd
        .args(["--workspace", &payload.workspace_path, "--json"])
        .current_dir(&root)
        .output()
        .map_err(|e| format!("Failed to spawn explore: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Ok(Envelope::err(format!("explore failed: {}", stderr)));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    // parse_python_json tolerates stray prints ahead of the payload. Without
    // it, a single library print downgraded a perfectly good structured result
    // to the "raw" branch below, and the UI silently lost explanation /
    // relevant_files. Raw stays as the genuine last resort.
    match crate::python_json::parse_python_json::<serde_json::Value>(&stdout, "hive") {
        Ok(data) => Ok(Envelope::ok(data)),
        // Raw stays the genuine last resort, and stays inside `data` so callers
        // that check for `data.raw` still find it.
        Err(_) => Ok(Envelope::ok(serde_json::json!({ "raw": stdout.trim().to_string() }))),
    }
}

/// Diagnose: given a bug description, locate the most relevant files in
/// an existing codebase and return targets + traceback context.
///
/// Spawns `determinex_hive.py diagnose --workspace PATH --issue TEXT`.
#[tauri::command]
pub async fn diagnose_workspace(
    payload: DiagnoseWorkspacePayload,
    _process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<serde_json::Value>, String> {
    log::info!(
        "[IPC] diagnose_workspace: {} issue_len={}",
        payload.workspace_path,
        payload.issue.len()
    );

    let root = project_root();

    let (mut cmd, standalone) = hive_command("diagnose")?;
    log::info!("[IPC] diagnose_workspace via {}", if standalone { "bundled engine" } else { "repo script" });
    let output = cmd
        .args(["--workspace", &payload.workspace_path, "--issue", &payload.issue])
        .current_dir(&root)
        .output()
        .map_err(|e| format!("Failed to spawn diagnose: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Ok(Envelope::err(format!("diagnose failed: {}", stderr)));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    // parse_python_json tolerates stray prints ahead of the payload. Without
    // it, a single library print downgraded a perfectly good structured result
    // to the "raw" branch below, and the UI silently lost explanation /
    // relevant_files. Raw stays as the genuine last resort.
    match crate::python_json::parse_python_json::<serde_json::Value>(&stdout, "hive") {
        Ok(data) => Ok(Envelope::ok(data)),
        // Raw stays the genuine last resort, and stays inside `data` so callers
        // that check for `data.raw` still find it.
        Err(_) => Ok(Envelope::ok(serde_json::json!({ "raw": stdout.trim().to_string() }))),
    }
}

/// Fix: locate a bug and generate a compiler-verified patch.
///
/// Spawns `determinex_hive.py fix --workspace PATH --issue TEXT [--out PATH]`
/// as a background subprocess. This can take minutes for large repos.
#[tauri::command]
pub async fn fix_workspace(
    payload: FixWorkspacePayload,
    _process_map: State<'_, HiveProcessMap>,
) -> Result<Envelope<serde_json::Value>, String> {
    log::info!(
        "[IPC] fix_workspace: {} issue_len={}",
        payload.workspace_path,
        payload.issue.len()
    );

    let root = project_root();

    let mut args = vec![
        "--workspace".to_string(),
        payload.workspace_path.clone(),
        "--issue".to_string(),
        payload.issue.clone(),
    ];
    if let Some(ref out) = payload.out_path {
        args.push("--out".to_string());
        args.push(out.clone());
    }

    let (mut cmd, standalone) = hive_command("fix")?;
    log::info!("[IPC] fix_workspace via {}", if standalone { "bundled engine" } else { "repo script" });
    let output = cmd
        .args(&args)
        .current_dir(&root)
        .output()
        .map_err(|e| format!("Failed to spawn fix: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let stdout_text = String::from_utf8_lossy(&output.stdout);
        return Ok(Envelope::err(format!("fix failed: {}{}", stderr, stdout_text)));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    // parse_python_json tolerates stray prints ahead of the payload. Without
    // it, a single library print downgraded a perfectly good structured result
    // to the "raw" branch below, and the UI silently lost explanation /
    // relevant_files. Raw stays as the genuine last resort.
    match crate::python_json::parse_python_json::<serde_json::Value>(&stdout, "hive") {
        Ok(data) => Ok(Envelope::ok(data)),
        // Raw stays the genuine last resort, and stays inside `data` so callers
        // that check for `data.raw` still find it.
        Err(_) => Ok(Envelope::ok(serde_json::json!({ "raw": stdout.trim().to_string() }))),
    }
}
