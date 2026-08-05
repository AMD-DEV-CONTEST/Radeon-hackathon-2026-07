//! Read the workspace's `.env` for the Env Manager panel.
//!
//! Ryan: "fix the envmanager if its not supposed to do that, im confused as to
//! what you mean?" -- fair. My earlier hedge was wrong. This is the user's own
//! `.env`, on their own machine, in their own local IDE. Showing it is normal
//! (every IDE does). The rules that actually matter are narrower:
//!
//!   * never log a value -- log lines outlive the window and get pasted into
//!     issues;
//!   * never hand back every value at once -- the list is masked, and a value
//!     is only returned for a key the user explicitly clicks;
//!   * never read outside the open workspace.
//!
//! Read-only on purpose. Writing `.env` is a separate decision with its own
//! blast radius (a bad write loses working credentials), and nothing in the
//! panel needs it to be useful.

use serde::Serialize;
use std::path::{Path, PathBuf};
use tauri::State;

use crate::fs::{is_safe_path, WorkspaceRoot};

#[derive(Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub struct EnvEntry {
    pub key: String,
    /// Masked preview, never the full value.
    pub preview: String,
    pub length: usize,
    /// True when the name looks credential-ish, so the UI can warn louder.
    pub looks_secret: bool,
}

/// Mask a value: keep enough to recognise it, never enough to use it.
fn mask(value: &str) -> String {
    let n = value.chars().count();
    if n == 0 {
        return "(empty)".into();
    }
    if n <= 8 {
        return "•".repeat(n);
    }
    // Token prefixes (ghp_, sk-, github_pat_) are public, documented markers and
    // are the single most useful thing for telling two keys apart at a glance.
    let head: String = value.chars().take(4).collect();
    format!("{head}{}", "•".repeat((n - 4).min(24)))
}

fn looks_secret(key: &str) -> bool {
    let k = key.to_ascii_uppercase();
    ["KEY", "TOKEN", "SECRET", "PASSWORD", "PASSWD", "CREDENTIAL", "API", "AUTH"]
        .iter()
        .any(|m| k.contains(m))
}

/// Parse `.env` text into entries. Split out so it is testable without a file.
fn parse_env(text: &str) -> Vec<EnvEntry> {
    let mut out = Vec::new();
    for raw in text.lines() {
        let line = raw.trim();
        // Skip blanks, comments, and `export FOO=bar` is still FOO=bar.
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((k, v)) = line.split_once('=') else {
            continue;
        };
        let key = k.trim().to_string();
        if key.is_empty() {
            continue;
        }
        // Strip one layer of matching quotes, the way dotenv does.
        let v = v.trim();
        let v = v
            .strip_prefix('"')
            .and_then(|s| s.strip_suffix('"'))
            .or_else(|| v.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')))
            .unwrap_or(v);
        out.push(EnvEntry {
            preview: mask(v),
            length: v.chars().count(),
            looks_secret: looks_secret(&key),
            key,
        });
    }
    out
}

fn env_path(workspace: &str) -> PathBuf {
    Path::new(workspace).join(".env")
}

fn guard(workspace_root: &Path, target: &Path) -> Result<(), String> {
    if !is_safe_path(workspace_root, target) {
        return Err("Access denied: .env is outside the open workspace.".to_string());
    }
    Ok(())
}

/// The project the user has actually opened.
///
/// Distinct from [`WorkspaceRoot`] on purpose. WorkspaceRoot is the FILE BROWSER's root and is set
/// to the system drive (`C:\`) so the picker can reach a project anywhere -- which means
/// `is_safe_path(WorkspaceRoot, target)` only ever asserts "somewhere on C:". This module's own
/// contract, stated at the top of the file, is "never read outside the open workspace", and against
/// a drive-root boundary that was not being enforced: `reveal_env_var` would return cleartext from
/// any `.env` on the drive, including this repository's own, which holds live provider keys.
///
/// Browsing broadly and reading credentials are different privileges, so they get different roots.
/// `None` means no project has been opened yet, and credential reads are refused outright rather
/// than falling back to the browse root.
#[derive(Default)]
pub struct ProjectRoot(pub std::sync::Mutex<Option<PathBuf>>);

/// Record the project the user opened. Called by the frontend when the workspace changes.
///
/// Also grants the file browser access to it. On Windows the browse root is the SYSTEM drive,
/// so a project on any other drive was unreadable and the explorer came up empty behind
/// "outside workspace boundary 'C:\'". Granting happens here, and only here, because this is
/// the one place that knows the user CHOSE this directory -- the widening is an explicit user
/// action, not a blanket "all drives are fine".
#[tauri::command]
pub fn set_project_root(
    path: String,
    state: State<'_, ProjectRoot>,
    workspace: State<'_, WorkspaceRoot>,
) -> Result<(), String> {
    let candidate = PathBuf::from(&path);
    if !candidate.is_dir() {
        return Err(format!("not a directory: {path}"));
    }
    let resolved = candidate
        .canonicalize()
        .map_err(|e| format!("could not resolve {path}: {e}"))?;
    workspace.grant(resolved.clone());
    let mut slot = state
        .0
        .lock()
        .map_err(|e| format!("ProjectRoot mutex poisoned: {e}"))?;
    *slot = Some(resolved);
    Ok(())
}

/// Whether `target` may be read given the opened project.
///
/// Pure so it can be unit-tested without a running app -- the failure mode being guarded against
/// (a credential read escaping the project) is not observable from the UI.
fn project_guard(project: Option<&Path>, target: &Path) -> Result<(), String> {
    let Some(root) = project else {
        return Err(
            "Access denied: no project is open. Open a project before reading its .env.".to_string(),
        );
    };
    // Compare resolved paths so `..` traversal and symlinks cannot escape. The target's parent is
    // resolved rather than the target itself, because `.env` may not exist yet.
    let parent = target.parent().unwrap_or(target);
    let resolved_parent = parent.canonicalize().unwrap_or_else(|_| parent.to_path_buf());
    let resolved_root = root.canonicalize().unwrap_or_else(|_| root.to_path_buf());
    if !resolved_parent.starts_with(&resolved_root) {
        return Err("Access denied: .env is outside the open project.".to_string());
    }
    Ok(())
}

/// Masked listing. Safe to call freely -- carries no usable secret.
#[tauri::command]
pub fn list_env_vars(
    workspace: String,
    root: State<'_, WorkspaceRoot>,
    project: State<'_, ProjectRoot>,
) -> Result<Vec<EnvEntry>, String> {
    let path = env_path(&workspace);
    guard(&root.0, &path)?;
    // Masked, but the KEY NAMES still describe someone's project, so the same boundary applies.
    let opened = project
        .0
        .lock()
        .map_err(|e| format!("ProjectRoot mutex poisoned: {e}"))?
        .clone();
    project_guard(opened.as_deref(), &path)?;
    if !path.exists() {
        return Ok(Vec::new());
    }
    let text = std::fs::read_to_string(&path).map_err(|e| format!("could not read .env: {e}"))?;
    Ok(parse_env(&text))
}

/// Return ONE value, for a key the user explicitly asked to reveal.
///
/// Deliberately one key per call rather than a bulk "give me everything"
/// variant: a single click should not put the whole credential set into the
/// webview. The value is never logged.
#[tauri::command]
pub fn reveal_env_var(
    workspace: String,
    key: String,
    root: State<'_, WorkspaceRoot>,
    project: State<'_, ProjectRoot>,
) -> Result<String, String> {
    let path = env_path(&workspace);
    guard(&root.0, &path)?;
    // The one command in this app that returns a usable credential in cleartext, so it gets the
    // project boundary rather than the drive-wide browse root. Before this, `workspace` could be
    // ANY directory and the answer was any `.env` on C: -- including this repository's own.
    let opened = project
        .0
        .lock()
        .map_err(|e| format!("ProjectRoot mutex poisoned: {e}"))?
        .clone();
    project_guard(opened.as_deref(), &path)?;
    let text = std::fs::read_to_string(&path).map_err(|e| format!("could not read .env: {e}"))?;
    for raw in text.lines() {
        let line = raw.trim();
        if line.is_empty() || line.starts_with('#') {
            continue;
        }
        let line = line.strip_prefix("export ").unwrap_or(line);
        let Some((k, v)) = line.split_once('=') else {
            continue;
        };
        if k.trim() != key {
            continue;
        }
        let v = v.trim();
        let v = v
            .strip_prefix('"')
            .and_then(|s| s.strip_suffix('"'))
            .or_else(|| v.strip_prefix('\'').and_then(|s| s.strip_suffix('\'')))
            .unwrap_or(v);
        return Ok(v.to_string());
    }
    Err(format!("{key} is not set in .env"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_pairs_comments_blanks_and_export() {
        let entries = parse_env(
            "# a comment\n\nFOO=bar\nexport BAZ=qux\n  SPACED = value \nnot_a_pair\n",
        );
        let keys: Vec<&str> = entries.iter().map(|e| e.key.as_str()).collect();
        assert_eq!(keys, vec!["FOO", "BAZ", "SPACED"]);
    }

    #[test]
    fn strips_one_layer_of_quotes() {
        let e = parse_env("A=\"quoted\"\nB='single'\n");
        assert_eq!(e[0].length, 6);
        assert_eq!(e[1].length, 6);
    }

    #[test]
    fn never_leaks_a_usable_value_in_the_listing() {
        let secret = "ghp_EXAMPLE_NOT_REAL_000000000000000000";
        let e = parse_env(&format!("GITHUB_TOKEN={secret}"));
        let p = &e[0].preview;
        // The prefix is a public marker and is the useful part; the rest must
        // be gone, and the preview must never contain the whole value.
        assert!(p.starts_with("ghp_"), "prefix should survive: {p}");
        assert!(!p.contains("ABCDEFGH"), "body leaked into preview: {p}");
        assert!(p.contains('•'), "value must be masked: {p}");
        // Precise version of "not usable": nothing past the public prefix
        // survives, so the preview cannot be pasted anywhere as a credential.
        let revealed: String = p.chars().filter(|c| *c != '•').collect();
        assert_eq!(revealed, "ghp_", "only the public prefix may survive: {revealed}");
        assert!(secret.chars().count() > revealed.chars().count());
    }

    #[test]
    fn short_values_are_fully_masked() {
        // Too short to show a prefix without effectively showing the value.
        let e = parse_env("PIN=1234");
        assert_eq!(e[0].preview, "••••");
    }

    #[test]
    fn empty_value_is_reported_as_empty_not_masked() {
        let e = parse_env("EMPTY=");
        assert_eq!(e[0].preview, "(empty)");
        assert_eq!(e[0].length, 0);
    }

    #[test]
    fn flags_credential_shaped_names() {
        let e = parse_env("GITHUB_TOKEN=x\nAPI_KEY=y\nPORT=3000\nDB_PASSWORD=z\n");
        let flagged: Vec<(&str, bool)> =
            e.iter().map(|x| (x.key.as_str(), x.looks_secret)).collect();
        assert_eq!(
            flagged,
            vec![("GITHUB_TOKEN", true), ("API_KEY", true), ("PORT", false), ("DB_PASSWORD", true)]
        );
    }

    #[test]
    fn preview_length_is_bounded_for_very_long_values() {
        let e = parse_env(&format!("BIG={}", "x".repeat(4000)));
        assert!(e[0].preview.chars().count() <= 28, "preview must not be huge");
        assert_eq!(e[0].length, 4000, "true length is still reported");
    }

    // ── project boundary ────────────────────────────────────────────────────────────────────
    //
    // This module's contract, stated at the top of the file, is "never read outside the open
    // workspace". It was not enforced: the only check was is_safe_path against WorkspaceRoot, and
    // WorkspaceRoot is the system drive (C:\) so the file browser can open a project anywhere. So
    // reveal_env_var returned cleartext from ANY .env on the drive -- including this repository's
    // own, which holds live provider keys. These cover the guard that now enforces the contract.

    #[test]
    fn refuses_a_credential_read_when_no_project_is_open() {
        let target = std::env::temp_dir().join("some-project").join(".env");
        let err = project_guard(None, &target).unwrap_err();
        assert!(err.contains("no project is open"), "unexpected message: {err}");
    }

    #[test]
    fn allows_an_env_inside_the_open_project() {
        let root = std::env::temp_dir().join("dtx-guard-allow");
        std::fs::create_dir_all(&root).unwrap();
        let target = root.join(".env");
        project_guard(Some(&root), &target).expect("an .env inside the open project must be allowed");
    }

    #[test]
    fn allows_an_env_that_does_not_exist_yet_inside_the_project() {
        // The panel is opened before a .env necessarily exists; the guard resolves the PARENT so a
        // missing file is not mistaken for an escape.
        let root = std::env::temp_dir().join("dtx-guard-missing");
        std::fs::create_dir_all(&root).unwrap();
        let target = root.join(".env");
        let _ = std::fs::remove_file(&target);
        project_guard(Some(&root), &target).expect("a not-yet-created .env must still be allowed");
    }

    #[test]
    fn refuses_an_env_in_a_sibling_directory() {
        let base = std::env::temp_dir().join("dtx-guard-sibling");
        let open = base.join("opened");
        let other = base.join("elsewhere");
        std::fs::create_dir_all(&open).unwrap();
        std::fs::create_dir_all(&other).unwrap();
        let err = project_guard(Some(&open), &other.join(".env")).unwrap_err();
        assert!(err.contains("outside the open project"), "unexpected message: {err}");
    }

    #[test]
    fn refuses_dot_dot_traversal_out_of_the_project() {
        // The concrete exploit shape: pass a workspace that walks up out of the opened project.
        let base = std::env::temp_dir().join("dtx-guard-traverse");
        let open = base.join("opened");
        let secrets = base.join("secrets");
        std::fs::create_dir_all(&open).unwrap();
        std::fs::create_dir_all(&secrets).unwrap();
        let escaped = open.join("..").join("secrets").join(".env");
        assert!(
            project_guard(Some(&open), &escaped).is_err(),
            "`..` traversal must not escape the open project"
        );
    }
}
