use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use std::path::PathBuf;

use crate::ipc_hive::project_root;

pub const CLAIM_BOUNDARY: &str = "This proves one bounded GUI-to-Hive workflow. It does not prove universal IDE support, all-language support, clean-host support, or release readiness.";

#[derive(Deserialize)]
pub struct FirstGuiHiveIpcEvidencePayload {
    pub request: Value,
    pub result: Value,
    pub claim_boundary: String,
}

#[derive(Serialize)]
struct EvidenceWriteResult {
    evidence_path: String,
    proof_report_path: String,
    files: Vec<String>,
}

fn evidence_dir() -> PathBuf {
    project_root()
        .join("assurance")
        .join("evidence")
        .join("first_gui_hive_ipc")
}

fn repo_relative(path: &PathBuf) -> String {
    path.strip_prefix(project_root())
        .unwrap_or(path.as_path())
        .to_string_lossy()
        .replace('\\', "/")
}

fn write_pretty_json(path: &PathBuf, value: &Value) -> Result<(), String> {
    let body = serde_json::to_string_pretty(value)
        .map_err(|e| format!("Cannot serialize {}: {}", path.display(), e))?;
    fs::write(path, format!("{}\n", body))
        .map_err(|e| format!("Cannot write {}: {}", path.display(), e))
}

fn transcript_markdown(request: &Value, result: &Value) -> String {
    let task = request.get("task").and_then(Value::as_str).unwrap_or("");
    let language = request
        .get("language_hint")
        .and_then(Value::as_str)
        .unwrap_or("");
    let mode = request.get("mode").and_then(Value::as_str).unwrap_or("");
    let status = result
        .get("status")
        .and_then(Value::as_str)
        .unwrap_or("BLOCKED_EXACT");
    let session_id = result
        .get("session_id")
        .and_then(Value::as_str)
        .unwrap_or("");

    format!(
        "# First GUI Hive IPC Transcript\n\n\
         Status: `{}`\n\n\
         Session: `{}`\n\n\
         Task: {}\n\n\
         Language hint: `{}`\n\n\
         Mode: `{}`\n\n\
         Commands run:\n{}\n\n\
         Claim boundary:\n{}\n",
        status,
        session_id,
        task,
        language,
        mode,
        result
            .get("commands_run")
            .and_then(Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(Value::as_str)
                    .map(|cmd| format!("- `{}`", cmd))
                    .collect::<Vec<_>>()
                    .join("\n")
            })
            .unwrap_or_else(|| "- `UNKNOWN`".to_string()),
        CLAIM_BOUNDARY
    )
}

#[tauri::command]
/// Writes the first-GUI-Hive-IPC evidence bundle and returns the manifest it
/// wrote, verbatim.
///
/// Untyped on purpose: the return IS the evidence record, and an evidence record
/// that has been reshaped by a struct is no longer evidence.
pub fn record_first_gui_hive_ipc_evidence(
    payload: FirstGuiHiveIpcEvidencePayload,
) -> Result<Value, String> {
    if payload.claim_boundary != CLAIM_BOUNDARY {
        return Err("claim boundary mismatch for first GUI Hive IPC evidence".to_string());
    }

    let dir = evidence_dir();
    fs::create_dir_all(&dir).map_err(|e| format!("Cannot create {}: {}", dir.display(), e))?;

    let request_path = dir.join("request.json");
    let result_path = dir.join("result.json");
    let transcript_path = dir.join("transcript.md");
    let boundary_path = dir.join("claim_boundary.md");

    let mut result = payload.result;
    if let Some(obj) = result.as_object_mut() {
        obj.insert(
            "evidence_path".to_string(),
            Value::String(repo_relative(&result_path)),
        );
        obj.insert(
            "proof_report_path".to_string(),
            Value::String(repo_relative(&transcript_path)),
        );
    }

    write_pretty_json(&request_path, &payload.request)?;
    write_pretty_json(&result_path, &result)?;
    fs::write(
        &transcript_path,
        transcript_markdown(&payload.request, &result),
    )
    .map_err(|e| format!("Cannot write {}: {}", transcript_path.display(), e))?;
    fs::write(&boundary_path, format!("{}\n", CLAIM_BOUNDARY))
        .map_err(|e| format!("Cannot write {}: {}", boundary_path.display(), e))?;

    let response = EvidenceWriteResult {
        evidence_path: repo_relative(&result_path),
        proof_report_path: repo_relative(&transcript_path),
        files: vec![
            repo_relative(&request_path),
            repo_relative(&result_path),
            repo_relative(&transcript_path),
            repo_relative(&boundary_path),
        ],
    };

    Ok(serde_json::json!({
        "ok": true,
        "data": response,
    }))
}
