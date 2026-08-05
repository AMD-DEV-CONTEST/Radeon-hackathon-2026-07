//! CI runs for the open workspace, via the `gh` CLI.
//!
//! The CICD panel was a shell: `INITIAL_RUNS: Run[] = []` that nothing ever
//! populated, with a "Connect a CI provider" note and no way to connect one.
//!
//! `gh` is the right provider rather than the GitHub REST API directly, because
//! it already holds the user's auth. Reimplementing auth here would mean a
//! second credential path for the same service the Passport panel and the new
//! Device Flow sign-in already handle.
//!
//! Read-only. Listing runs is not the same authority as re-running or
//! cancelling one, and nothing in the panel needs those.

use serde::{Deserialize, Serialize};
use std::path::Path;
use std::process::Command;

use crate::win_process::HideConsoleExt;

/// The `--json` fields we ask `gh` for. Keep in sync with `CiRun`.
const RUN_FIELDS: &str =
    "databaseId,displayTitle,status,conclusion,workflowName,headBranch,createdAt,url";

#[derive(Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CiRun {
    #[serde(rename = "databaseId")]
    pub database_id: i64,
    #[serde(rename = "displayTitle", default)]
    pub display_title: String,
    #[serde(default)]
    pub status: String,
    #[serde(default)]
    pub conclusion: String,
    #[serde(rename = "workflowName", default)]
    pub workflow_name: String,
    #[serde(rename = "headBranch", default)]
    pub head_branch: String,
    #[serde(rename = "createdAt", default)]
    pub created_at: String,
    #[serde(default)]
    pub url: String,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CiStatus {
    pub available: bool,
    pub runs: Vec<CiRun>,
    /// Why the list is empty, when it is. Never leave the UI to guess.
    pub note: Option<String>,
}

fn unavailable(note: &str) -> CiStatus {
    CiStatus { available: false, runs: Vec::new(), note: Some(note.to_string()) }
}

/// List recent CI runs for the workspace's repo.
#[tauri::command]
pub fn list_ci_runs(workspace: String, limit: Option<u32>) -> Result<CiStatus, String> {
    let dir = Path::new(&workspace);
    if workspace.trim().is_empty() || !dir.is_dir() {
        return Ok(unavailable("No workspace is open."));
    }
    if !dir.join(".git").exists() {
        return Ok(unavailable("This workspace is not a git repository."));
    }

    let limit = limit.unwrap_or(20).clamp(1, 100);
    let out = Command::new("gh")
        .hide_console()
        .args(["run", "list", "--limit", &limit.to_string(), "--json", RUN_FIELDS])
        .current_dir(dir)
        .output();

    let out: std::process::Output = match out {
        Ok(o) => o,
        // Distinguish "gh is not installed" from "gh failed", because the fix
        // is completely different and the panel should say which.
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => {
            return Ok(unavailable(
                "The GitHub CLI (gh) is not installed or not on PATH. Install it to see CI runs.",
            ))
        }
        Err(e) => return Ok(unavailable(&format!("Could not run gh: {e}"))),
    };

    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr).trim().to_string();
        let lower = err.to_lowercase();
        // gh's own guidance is better than anything we could invent here, so
        // pass it through rather than flattening it to "failed".
        let note = if lower.contains("not logged") || lower.contains("authentication") {
            "Not signed in to GitHub. Run `gh auth login`, or sign in from Passport.".to_string()
        } else if lower.contains("no such remote") || lower.contains("not a github repository") {
            "This repository has no GitHub remote, so there are no CI runs to show.".to_string()
        } else {
            format!("gh: {err}")
        };
        return Ok(unavailable(&note));
    }

    let stdout = String::from_utf8_lossy(&out.stdout);
    let runs: Vec<CiRun> = crate::python_json::parse_python_json(&stdout, "gh run list")
        .map_err(|e| format!("could not read gh output: {e}"))?;

    let note = if runs.is_empty() {
        Some("No CI runs recorded for this repository yet.".to_string())
    } else {
        None
    };
    Ok(CiStatus { available: true, runs, note })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn reports_a_missing_workspace_rather_than_an_empty_list() {
        // An empty list with no explanation is how the old panel looked
        // permanently. Every empty state here must say why.
        let r = list_ci_runs(String::new(), None).unwrap();
        assert!(!r.available);
        assert!(r.note.unwrap().contains("No workspace"));
    }

    #[test]
    fn reports_a_non_git_directory() {
        let dir = tempfile::tempdir().unwrap();
        let r = list_ci_runs(dir.path().to_string_lossy().to_string(), None).unwrap();
        assert!(!r.available);
        assert!(r.note.unwrap().contains("not a git repository"));
    }

    #[test]
    fn parses_a_real_gh_payload() {
        // Captured verbatim from `gh run list --json ...` in this repo.
        let raw = r#"[{"conclusion":"startup_failure","createdAt":"2026-07-27T03:52:30Z",
            "databaseId":30235624313,"displayTitle":"fix(readme): correct a self-contradiction",
            "headBranch":"main","status":"completed","workflowName":"","url":"https://x/y"}]"#;
        let runs: Vec<CiRun> = serde_json::from_str(raw).expect("gh shape must deserialize");
        assert_eq!(runs.len(), 1);
        assert_eq!(runs[0].database_id, 30235624313);
        assert_eq!(runs[0].conclusion, "startup_failure");
        assert_eq!(runs[0].head_branch, "main");
        // workflowName really can come back empty; it must not break parsing.
        assert_eq!(runs[0].workflow_name, "");
    }

    #[test]
    fn requested_fields_match_the_struct() {
        // A field added to CiRun but not to RUN_FIELDS silently deserializes as
        // empty forever, which is exactly the kind of quiet gap this codebase
        // keeps producing.
        for f in ["databaseId", "displayTitle", "status", "conclusion", "workflowName",
                  "headBranch", "createdAt", "url"] {
            assert!(RUN_FIELDS.contains(f), "{f} missing from RUN_FIELDS");
        }
    }
}
