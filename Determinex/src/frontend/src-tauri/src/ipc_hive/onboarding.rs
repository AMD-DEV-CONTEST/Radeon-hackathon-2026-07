//! First-run onboarding: which provider button to press, and how to talk to this user.
//!
//! These exist as Tauri commands, not only as HTTP-bridge endpoints, because the frontend's
//! `invokeSafe` prefers Tauri IPC and only falls back to the bridge when Tauri is absent.
//! Shipping an onboarding feature to the bridge alone would leave it unreachable in the
//! desktop app — which is exactly what happened to `assess_idea_context` earlier today: the
//! Python side worked, every test passed, and the app quietly used the old code path.
//!
//! Reaching a command from the app needs three things, and missing any one of them looks
//! identical from the UI: a `#[tauri::command]`, its registration in `generate_handler!`, and
//! an entry in the ACL (`python scripts/dev/gen_tauri_acl.py`, guarded by
//! `tests/test_tauri_acl.py`).

use serde::{Deserialize, Serialize};
use std::process::{Command, Stdio};

use super::{project_root, resolve_python_exe};
use crate::ipc_envelope::Envelope;
use crate::win_process::HideConsoleExt;

#[derive(Deserialize, Serialize)]
pub struct VerifyProviderPayload {
    pub id: String,
}

#[derive(Deserialize, Serialize)]
pub struct SetReaderLevelPayload {
    pub level: String,
}

/// Run a helper script and hand back whatever JSON it printed.
///
/// Failures return an `Envelope::err` rather than `Err`, so the onboarding screen can render
/// a reason instead of throwing. A first-run screen that crashes on its own diagnostics is
/// worse than one that says "I could not check this".
fn run_json(script: &str, args: &[&str]) -> Result<Envelope<serde_json::Value>, String> {
    let path = project_root().join("scripts").join(script);
    if !path.exists() {
        return Ok(Envelope::err(format!("{script} not found")));
    }
    let python = match resolve_python_exe() {
        Ok(p) => p,
        Err(e) => return Ok(Envelope::err(format!("python not resolvable: {e}"))),
    };

    let mut argv: Vec<&str> = vec![path.to_str().unwrap()];
    argv.extend_from_slice(args);

    let output = Command::new(&python)
        .hide_console()
        .args(&argv)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("failed to run {script}: {e}"))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        let last = stderr
            .lines()
            .rev()
            .find(|l| !l.trim().is_empty())
            .unwrap_or("no detail");
        return Ok(Envelope::err(format!("{script} failed: {last}")));
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    match serde_json::from_str::<serde_json::Value>(stdout.trim()) {
        Ok(v) => Ok(Envelope::ok(v)),
        Err(e) => Ok(Envelope::err(format!("{script} returned non-JSON: {e}"))),
    }
}

/// What already works on this machine, and the ONE thing to do next.
#[tauri::command]
pub async fn provider_setup_report() -> Result<Envelope<serde_json::Value>, String> {
    run_json("determinex_provider_setup.py", &["report"])
}

/// Make one real call, so a green check means a call actually happened.
#[tauri::command]
pub async fn provider_setup_verify(
    payload: VerifyProviderPayload,
) -> Result<Envelope<serde_json::Value>, String> {
    run_json(
        "determinex_provider_setup.py",
        &["verify", "--id", payload.id.as_str()],
    )
}

/// The reader-level prescreen, and whether it still needs asking.
#[tauri::command]
pub async fn user_profile_get() -> Result<Envelope<serde_json::Value>, String> {
    run_json("determinex_user_profile.py", &["prescreen"])
}

/// Record how this user wants to be spoken to.
#[tauri::command]
pub async fn user_profile_set(
    payload: SetReaderLevelPayload,
) -> Result<Envelope<serde_json::Value>, String> {
    run_json(
        "determinex_user_profile.py",
        &["set", "--level", payload.level.as_str()],
    )
}
