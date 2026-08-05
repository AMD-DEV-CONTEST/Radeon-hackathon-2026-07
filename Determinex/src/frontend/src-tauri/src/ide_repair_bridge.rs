// CLAUDE LANE — IDE repair bridge.
//
// Locked under: locks/sentinel/TAURI_RUST_COMMAND_BRIDGE_LOCK_001.json
//
// Stable Tauri command surface that fronts the locked Python backend
// command surface (scripts/ide/backend_command_surface.py +
// tauri_backend_bridge.py). Every command here returns JSON-safe
// results and refuses to perform live model calls, source mutation,
// corpus writes, or training-eligibility changes.
//
// Wire-up: in src-tauri/src/lib.rs add `mod ide_repair_bridge;` near
// the other mod declarations, and append the command names below
// to the tauri::generate_handler! macro invocation. See
// docs/TAURI_RUST_COMMAND_BRIDGE.md for the integration recipe.
//
// All commands shell out to the project's Python interpreter via a
// short helper (`run_backend_command`), which is intentionally written
// against std::process::Command rather than the broader Tauri sidecar
// machinery so the Claude lane review surface is small.

// Python is resolved through `ipc_hive::resolve_python_exe()`, never `Command::new("python")`.
//
// That resolver exists for a specific reason: on Windows, PATH `python` is very
// often the Microsoft Store AppExecLink stub, which does not run Python -- it opens
// the Store. It also prefers the repo venv, so the interpreter that has the
// project's dependencies is the one used. Ten call sites across six files bypassed
// it and used bare `python`, which worked only on machines where PATH happened to
// resolve to a real interpreter.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::process::Command;
use crate::win_process::HideConsoleExt;

const PYTHON_DRIVER: &str = "scripts/ide/_tauri_driver.py";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct IdeRepairResponse {
    pub command: String,
    pub status: String,
    pub payload: serde_json::Value,
    pub source_mutation_authorized: bool,
    pub training_eligible: bool,
    pub notes: Vec<String>,
}

impl IdeRepairResponse {
    fn unknown(command: &str, reason: &str) -> Self {
        Self {
            command: command.to_string(),
            status: "TAURI_COMMAND_BLOCKED_UNKNOWN".to_string(),
            payload: serde_json::json!({}),
            source_mutation_authorized: false,
            training_eligible: false,
            notes: vec![reason.to_string()],
        }
    }

    fn backend_missing(command: &str, reason: &str) -> Self {
        Self {
            command: command.to_string(),
            status: "TAURI_RUST_COMMAND_BRIDGE_BLOCKED_BACKEND_MISSING".to_string(),
            payload: serde_json::json!({}),
            source_mutation_authorized: false,
            training_eligible: false,
            notes: vec![reason.to_string()],
        }
    }
}

/// Repo-root helper. Walks upward from the current working directory
/// looking for a `scripts/ide/_tauri_driver.py` marker. Returns None
/// if the marker is not found.
fn locate_repo_root() -> Option<PathBuf> {
    let cwd = std::env::current_dir().ok()?;
    let mut cur: Option<&std::path::Path> = Some(cwd.as_path());
    while let Some(c) = cur {
        if c.join(PYTHON_DRIVER).is_file() {
            return Some(c.to_path_buf());
        }
        cur = c.parent();
    }
    None
}

fn run_backend_command(command: &str, args_json: &str) -> IdeRepairResponse {
    let root = match locate_repo_root() {
        Some(r) => r,
        None => {
            return IdeRepairResponse::backend_missing(
                command,
                "could not locate repo root (scripts/ide/_tauri_driver.py missing)",
            )
        }
    };

    // Spawn `python scripts/ide/_tauri_driver.py <command> <args_json>`.
    // No shell. argv only.
    // Bundled-first (see ipc_hive::helper_command): this used to build
    // `python <root>/scripts/<name>.py`, which does not exist in an installed copy.
    let (mut cmd, _bundled) = match crate::ipc_hive::helper_command(PYTHON_DRIVER) {
        Ok(v) => v,
        // This function returns IdeRepairResponse, not Result, so it reports through
        // its own backend_missing constructor rather than `?`.
        Err(e) => return IdeRepairResponse::backend_missing(command, &e),
    };
    cmd.arg(command);
    cmd.arg(args_json);
    cmd.current_dir(&root);

    match cmd.output() {
        Ok(out) => {
            if !out.status.success() {
                let stderr = String::from_utf8_lossy(&out.stderr).to_string();
                return IdeRepairResponse::backend_missing(
                    command,
                    &format!("python driver exited {:?}: {stderr}", out.status.code()),
                );
            }
            let stdout = String::from_utf8_lossy(&out.stdout).to_string();
            match serde_json::from_str::<IdeRepairResponse>(&stdout) {
                Ok(r) => r,
                Err(e) => IdeRepairResponse::backend_missing(
                    command,
                    &format!("malformed JSON from driver: {e}"),
                ),
            }
        }
        Err(e) => IdeRepairResponse::backend_missing(
            command,
            &format!("could not spawn python driver: {e}"),
        ),
    }
}

// ---------------------------------------------------------------------------
// Tauri commands. Names match the locked TauriBridge.
// ---------------------------------------------------------------------------

#[tauri::command]
pub fn open_workspace(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("open_workspace", &args)
}

#[tauri::command]
pub fn get_workspace_status(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("get_workspace_status", &args)
}

#[tauri::command]
pub fn get_model_route_status(task_class: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "task_class": task_class }).to_string();
    run_backend_command("get_model_route_status", &args)
}

#[tauri::command]
pub fn diagnose_dry_run(workspace: String, task_class: String) -> IdeRepairResponse {
    let args = serde_json::json!({
        "workspace": workspace, "task_class": task_class,
    })
    .to_string();
    run_backend_command("diagnose_dry_run", &args)
}

#[tauri::command]
pub fn diagnose_live_opt_in(
    workspace: String,
    task_class: String,
    opt_in: bool,
) -> IdeRepairResponse {
    let args = serde_json::json!({
        "workspace": workspace, "task_class": task_class, "opt_in": opt_in,
    })
    .to_string();
    run_backend_command("diagnose_live_opt_in", &args)
}

#[tauri::command]
pub fn generate_patch_plan(workspace: String, opt_in: bool) -> IdeRepairResponse {
    let args = serde_json::json!({
        "workspace": workspace, "opt_in": opt_in,
    })
    .to_string();
    run_backend_command("generate_patch_plan", &args)
}

#[tauri::command]
pub fn verify_temp_patch(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("verify_temp_patch", &args)
}

#[tauri::command]
pub fn get_human_approval_packet(workspace: String, unified_diff: String) -> IdeRepairResponse {
    let args = serde_json::json!({
        "workspace": workspace, "unified_diff": unified_diff,
    })
    .to_string();
    run_backend_command("get_human_approval_packet", &args)
}

#[tauri::command]
pub fn source_apply_dry_run(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("source_apply_dry_run", &args)
}

#[tauri::command]
pub fn get_repair_flow_state(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("get_repair_flow_state", &args)
}

#[tauri::command]
pub fn generate_llm_program_advisory(workspace: String, user_request: String) -> IdeRepairResponse {
    let args = serde_json::json!({
        "workspace": workspace, "user_request": user_request,
    })
    .to_string();
    run_backend_command("generate_llm_program_advisory", &args)
}

#[tauri::command]
pub fn preview_idea_oracle(idea_text: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "idea_text": idea_text }).to_string();
    run_backend_command("preview_idea_oracle", &args)
}

#[tauri::command]
pub fn build_idea(idea_text: String, opt_in: bool, model_id: Option<String>) -> IdeRepairResponse {
    let args = serde_json::json!({
        "idea_text": idea_text,
        "opt_in": opt_in,
        "model_id": model_id.unwrap_or_default(),
    })
    .to_string();
    run_backend_command("build_idea", &args)
}

#[tauri::command]
pub fn repair_diagnose(workspace: String) -> IdeRepairResponse {
    let args = serde_json::json!({ "workspace": workspace }).to_string();
    run_backend_command("repair_diagnose", &args)
}

#[tauri::command]
pub fn get_governance_status() -> IdeRepairResponse {
    run_backend_command("get_governance_status", "{}")
}

// ---------------------------------------------------------------------------
// Unified product shell commands. These are read-only view-model snapshots that
// already route through scripts/ide/_tauri_driver.py and IDEBackendCommandSurface.
// They do not mutate source, grant approval, execute ProgramBench, or open
// training eligibility.
// ---------------------------------------------------------------------------

fn run_unified_product_command(command: &str) -> IdeRepairResponse {
    run_backend_command(command, "{}")
}

#[tauri::command]
pub fn get_unified_product_navigation_model() -> IdeRepairResponse {
    run_unified_product_command("get_unified_product_navigation_model")
}

#[tauri::command]
pub fn get_idea_lab_workflow_state() -> IdeRepairResponse {
    run_unified_product_command("get_idea_lab_workflow_state")
}

#[tauri::command]
pub fn get_repo_clinic_workflow_state() -> IdeRepairResponse {
    run_unified_product_command("get_repo_clinic_workflow_state")
}

#[tauri::command]
pub fn get_maintenance_bay_workflow_state() -> IdeRepairResponse {
    run_unified_product_command("get_maintenance_bay_workflow_state")
}

#[tauri::command]
pub fn get_learning_studio_workflow_state() -> IdeRepairResponse {
    run_unified_product_command("get_learning_studio_workflow_state")
}

// Rung 7 of DETERMINEX_LIVE_REACT_UNIFIED_PRODUCT_SHELL_SERIES: Learning Studio content
// generation. Read-only (grounds explanations in the verified corpus + real files);
// non-authorizing (every output is gated through learning_studio_workflow.evaluate() before
// this returns). `workspace` is optional and only used by explain_this_repo/explain_this_file.
#[tauri::command]
pub fn generate_learning_studio_content(
    mode: String,
    context: String,
    workspace: Option<String>,
) -> IdeRepairResponse {
    let args = serde_json::json!({
        "mode": mode,
        "context": context,
        "workspace": workspace.unwrap_or_default(),
    })
    .to_string();
    run_backend_command("generate_learning_studio_content", &args)
}

// Maintenance Bay live scan: composes the 5 existing scripts/security/*.py scanners
// (secret_scan, dependency_scan, verify_lockfiles, license_scan, container_scan) into one
// read-only advisory result via security_gate.run_all(). Never applies an update, never
// authorizes anything -- a "blocked" gate is a finding to review, not source mutation.
// Can take several seconds (dependency_scan shells out to pip-audit over the whole
// environment); intentionally NOT auto-fetched on panel mount, only on explicit request.
#[tauri::command]
pub fn run_maintenance_bay_scan() -> IdeRepairResponse {
    run_backend_command("run_maintenance_bay_scan", "{}")
}

// Direct corpus query surface (2026-07-16): the ONE canonical read-only corpus API
// (scripts/determinex_corpus_api.py -- ask/maturity_report/timeline) exposed as its own
// command, instead of being reachable only through the two Learning Studio modes that
// happen to call ask() internally. `query` is the free-text question (or a topic filter
// for maturity/timeline modes); `mode` selects "ask" (default), "maturity", or "timeline".
// No search/ranking logic lives here or in the Python handler -- pure wiring.
#[tauri::command]
pub fn query_corpus(query: String, mode: Option<String>) -> IdeRepairResponse {
    let args = serde_json::json!({
        "corpus_query": query,
        "corpus_mode": mode.unwrap_or_else(|| "ask".to_string()),
    })
    .to_string();
    run_backend_command("query_corpus", &args)
}

// What this machine can actually do, and what it has actually spent (2026-07-30).
//
// Two things had no user-visible surface. The accelerator was detected only via `nvidia-smi`, so an
// AMD or Apple rig reported CPU-only and was driven at the lowest tier -- 0 resident models, 1
// parallel step -- while holding more memory than the top tier requires. And
// `determinex_usage_ledger` was already referenced by passport.rs, but its latency and cost figures
// never reached the UI, so "local is free and fast" was a claim rather than a reading.
//
// Read-only and pure wiring: the payload is assembled in the Python backend surface, which is where
// hive.hardware and the ledger live. Nothing here decides anything.
#[tauri::command]
pub fn get_runtime_capability_status() -> IdeRepairResponse {
    run_backend_command("get_runtime_capability_status", "{}")
}

#[tauri::command]
pub fn get_proof_operator_center_state() -> IdeRepairResponse {
    run_unified_product_command("get_proof_operator_center_state")
}

#[tauri::command]
pub fn get_user_level_teaching_windows() -> IdeRepairResponse {
    run_unified_product_command("get_user_level_teaching_windows")
}

#[tauri::command]
pub fn get_unified_splash_demo_spec() -> IdeRepairResponse {
    run_unified_product_command("get_unified_splash_demo_spec")
}

#[tauri::command]
pub fn get_idea_lab_verified_demo_status() -> IdeRepairResponse {
    run_unified_product_command("get_idea_lab_verified_demo_status")
}

#[tauri::command]
pub fn get_repo_clinic_verified_demo_status() -> IdeRepairResponse {
    run_unified_product_command("get_repo_clinic_verified_demo_status")
}

#[tauri::command]
pub fn get_maintenance_bay_verified_demo_status() -> IdeRepairResponse {
    run_unified_product_command("get_maintenance_bay_verified_demo_status")
}

#[tauri::command]
pub fn get_learning_studio_verified_demo_status() -> IdeRepairResponse {
    run_unified_product_command("get_learning_studio_verified_demo_status")
}

#[tauri::command]
pub fn get_proof_operator_center_milestone_dashboard_status() -> IdeRepairResponse {
    run_unified_product_command("get_proof_operator_center_milestone_dashboard_status")
}

// The list of registered commands. Frontend tests pin this so the
// Tauri command surface cannot drift silently.
pub const IDE_REPAIR_COMMANDS: &[&str] = &[
    "open_workspace",
    "get_workspace_status",
    "get_model_route_status",
    "diagnose_dry_run",
    "diagnose_live_opt_in",
    "generate_patch_plan",
    "verify_temp_patch",
    "get_human_approval_packet",
    "source_apply_dry_run",
    "get_repair_flow_state",
    "generate_llm_program_advisory",
    "preview_idea_oracle",
    "build_idea",
    "repair_diagnose",
    "get_governance_status",
];

#[allow(dead_code)]
pub const UNIFIED_PRODUCT_READ_ONLY_COMMANDS: &[&str] = &[
    "get_unified_product_navigation_model",
    "get_idea_lab_workflow_state",
    "get_repo_clinic_workflow_state",
    "get_maintenance_bay_workflow_state",
    "get_learning_studio_workflow_state",
    "get_proof_operator_center_state",
    "get_user_level_teaching_windows",
    "get_unified_splash_demo_spec",
    "get_idea_lab_verified_demo_status",
    "get_repo_clinic_verified_demo_status",
    "get_maintenance_bay_verified_demo_status",
    "get_learning_studio_verified_demo_status",
    "get_proof_operator_center_milestone_dashboard_status",
];
// NOTE: generate_learning_studio_content (rung 7) is deliberately NOT in this frozen list --
// it's real per-call computation (mode+context args), not a static view-model snapshot, same
// reason preview_idea_oracle/repair_diagnose/build_idea live outside this set too. It's still
// registered in tauri::generate_handler! in lib.rs and has its own #[tauri::command] above.
// NOTE: query_corpus is deliberately NOT in this frozen list either -- same reasoning
// (real per-call query+search, not a static view-model snapshot).

#[cfg(test)]
mod tests {
    use super::IDE_REPAIR_COMMANDS;

    #[test]
    fn flagship_commands_are_exposed_to_tauri() {
        for command in [
            "preview_idea_oracle",
            "build_idea",
            "repair_diagnose",
            "get_governance_status",
        ] {
            assert!(
                IDE_REPAIR_COMMANDS.contains(&command),
                "missing flagship Tauri command: {command}"
            );
        }
    }
}
