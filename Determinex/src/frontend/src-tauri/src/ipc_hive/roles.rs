use serde::{Deserialize, Serialize};
use tauri::Manager;

use super::{project_root, sessions_dir};
use crate::ipc_envelope::Envelope;

// ─────────────────────────────────────────────────────────────────────────────
// LIST HIVE SESSIONS — Project Library
// ─────────────────────────────────────────────────────────────────────────────

/// Summary of a single Hive build session, returned by list_hive_sessions.
#[derive(Serialize)]
pub struct SessionSummary {
    pub session_id: String,
    pub lang: String,
    pub project_name: String,
    /// Derived: "complete" | "failed" | "in_progress" | "pending"
    pub status: String,
    pub step_count: usize,
    pub complete_count: usize,
    pub failed_count: usize,
    pub created_at: String,
    pub updated_at: String,
    pub project_root: String,
}

/// Scan sessions/ directory, read every manifest.json that has a `steps` array,
/// and return a summary list sorted newest-first.
///
/// Sessions without `steps` (explore sessions) are silently skipped — they have
/// a different schema (`workspace_path`, `report`, etc.) not relevant here.
/// Capped at 100 sessions to bound IPC payload size.
#[tauri::command]
pub async fn list_hive_sessions() -> Result<Envelope<Vec<SessionSummary>>, String> {
    let sessions = sessions_dir();

    if !sessions.exists() {
        return Ok(Envelope::ok(Vec::new()));
    }

    let entries =
        std::fs::read_dir(&sessions).map_err(|e| format!("Cannot read sessions dir: {}", e))?;

    let mut summaries: Vec<SessionSummary> = Vec::new();

    for entry in entries.flatten() {
        let path = entry.path();
        if !path.is_dir() {
            continue;
        }

        let manifest = path.join("manifest.json");
        if !manifest.exists() {
            continue;
        }

        let content = match std::fs::read_to_string(&manifest) {
            Ok(c) => c,
            Err(_) => continue,
        };
        let data: serde_json::Value = match serde_json::from_str(&content) {
            Ok(d) => d,
            Err(_) => continue,
        };

        // Skip non-Hive sessions (they have no "steps" key or it is null)
        let steps_arr = match data["steps"].as_array() {
            Some(a) => a,
            None => continue,
        };

        let step_count = steps_arr.len();
        if step_count == 0 {
            continue; // Generated DAG isn't ready yet — skip silently
        }

        let complete_count = steps_arr
            .iter()
            .filter(|s| s["status"].as_str() == Some("complete"))
            .count();
        let failed_count = steps_arr
            .iter()
            .filter(|s| s["status"].as_str() == Some("failed"))
            .count();
        let in_progress_count = steps_arr
            .iter()
            .filter(|s| s["status"].as_str() == Some("in_progress"))
            .count();

        let status = if complete_count == step_count {
            "complete"
        } else if failed_count > 0
            && in_progress_count == 0
            && complete_count + failed_count == step_count
        {
            "failed"
        } else if in_progress_count > 0 {
            "in_progress"
        } else {
            "pending"
        };

        // Extract project name from spec file first H1 comment if stored, else "Unnamed Project"
        let spec_content = data["spec"].as_str().unwrap_or("");
        let project_name = spec_content
            .lines()
            .find(|l| l.trim_start().starts_with("# "))
            .map(|l| l.trim_start_matches('#').trim().to_string())
            .filter(|n| !n.is_empty())
            .unwrap_or_else(|| "Unnamed Project".to_string());

        summaries.push(SessionSummary {
            session_id: data["session_id"].as_str().unwrap_or("").to_string(),
            lang: data["lang"].as_str().unwrap_or("").to_string(),
            project_name,
            status: status.to_string(),
            step_count,
            complete_count,
            failed_count,
            created_at: data["created_at"].as_str().unwrap_or("").to_string(),
            updated_at: data["updated_at"].as_str().unwrap_or("").to_string(),
            project_root: data["project_root"].as_str().unwrap_or("").to_string(),
        });
    }

    // Sort newest first by created_at (ISO8601 string sort is safe)
    summaries.sort_by(|a, b| b.created_at.cmp(&a.created_at));

    // Cap at 100 to bound IPC payload size
    summaries.truncate(100);

    Ok(Envelope::ok(summaries))
}

// ─────────────────────────────────────────────────────────────────────────────
// ROLE ASSIGNMENT — read / write determinex.roles in litellm_config.yaml
// ─────────────────────────────────────────────────────────────────────────────

const DEFAULT_ORACLE: &str = "local/fast";
const DEFAULT_ARCHITECT: &str = "local/fast";
const DEFAULT_BUILDER: &str = "determinex/engineer";
const DEFAULT_MONITOR: &str = "determinex/observer";

/// Role -> model assignments. `api.ts` has declared this exact shape as
/// `RoleAssignments` since before there was any Rust type to check it against;
/// `returnShape.test.ts` now pins the two together.
#[derive(Serialize, Deserialize, Clone)]
pub struct RoleAssignments {
    pub oracle: String,
    pub architect: String,
    pub builder: String,
    pub monitor: String,
}

/// Reported by the role writers so the UI can show which file it touched.
#[derive(Serialize)]
pub struct ConfigPathResponse {
    pub config_path: String,
}

/// `get_role_assignments` also reports which file it read, which the envelope's
/// generic `data` cannot express on its own.
#[derive(Serialize)]
pub struct RoleAssignmentsResponse {
    pub oracle: String,
    pub architect: String,
    pub builder: String,
    pub monitor: String,
    pub config_path: String,
}

fn default_roles_json() -> serde_json::Value {
    serde_json::json!({
        "oracle": DEFAULT_ORACLE,
        "architect": DEFAULT_ARCHITECT,
        "builder": DEFAULT_BUILDER,
        "monitor": DEFAULT_MONITOR,
    })
}

fn role_config_path(app: &tauri::AppHandle) -> std::path::PathBuf {
    if let Ok(path) = std::env::var("DETERMINEX_LITELLM_CONFIG") {
        let p = std::path::PathBuf::from(path);
        if !p.as_os_str().is_empty() {
            return p;
        }
    }

    let repo_config = project_root().join("litellm_config.yaml");
    if repo_config.exists() {
        return repo_config;
    }

    app.path()
        .app_data_dir()
        .unwrap_or_else(|_| project_root())
        .join("litellm_config.yaml")
}

fn parse_roles_json(config: &str) -> serde_json::Value {
    let mut roles = default_roles_json();
    for role in ["oracle", "architect", "builder", "monitor"] {
        let pattern = format!(r"(?m)^\s*{}:\s*([^\s#]+)", regex::escape(role));
        if let Ok(re) = regex::Regex::new(&pattern) {
            if let Some(caps) = re.captures(config) {
                if let Some(value) = caps.get(1) {
                    roles[role] = serde_json::Value::String(value.as_str().to_string());
                }
            }
        }
    }
    roles
}

fn default_config_text(assignments: &serde_json::Value) -> String {
    format!(
        "determinex:\n  roles:\n    oracle: {}\n    architect: {}\n    builder: {}\n    monitor: {}\n",
        assignments["oracle"].as_str().unwrap_or(DEFAULT_ORACLE),
        assignments["architect"]
            .as_str()
            .unwrap_or(DEFAULT_ARCHITECT),
        assignments["builder"].as_str().unwrap_or(DEFAULT_BUILDER),
        assignments["monitor"].as_str().unwrap_or(DEFAULT_MONITOR)
    )
}

fn upsert_roles(mut config: String, assignments: &serde_json::Value) -> String {
    let mut replaced_any = false;
    for role in ["oracle", "architect", "builder", "monitor"] {
        let Some(value) = assignments.get(role).and_then(|v| v.as_str()) else {
            continue;
        };
        let pattern = format!(r"(?m)^(\s*{}:\s*)[^\s#]+(.*)$", regex::escape(role));
        if let Ok(re) = regex::Regex::new(&pattern) {
            if re.is_match(&config) {
                replaced_any = true;
                config = re
                    .replace_all(&config, |caps: &regex::Captures| {
                        format!(
                            "{}{}{}",
                            &caps[1],
                            value,
                            caps.get(2).map(|m| m.as_str()).unwrap_or("")
                        )
                    })
                    .to_string();
            }
        }
    }
    if replaced_any {
        return config;
    }
    if !config.trim().is_empty() && !config.ends_with('\n') {
        config.push('\n');
    }
    config.push_str(&default_config_text(assignments));
    config
}

/// Read a `serde_json::Value` of role names into the typed struct, falling back
/// per-field so a partially-written config still yields a complete answer.
fn roles_from_json(v: &serde_json::Value) -> RoleAssignments {
    let pick = |k: &str, d: &str| v.get(k).and_then(|x| x.as_str()).unwrap_or(d).to_string();
    RoleAssignments {
        oracle: pick("oracle", DEFAULT_ORACLE),
        architect: pick("architect", DEFAULT_ARCHITECT),
        builder: pick("builder", DEFAULT_BUILDER),
        monitor: pick("monitor", DEFAULT_MONITOR),
    }
}

/// Return the current role-to-model assignments from litellm_config.yaml.
#[tauri::command]
pub async fn get_role_assignments(
    app: tauri::AppHandle,
) -> Result<Envelope<RoleAssignmentsResponse>, String> {
    let config_path = role_config_path(&app);
    let path_text = config_path.to_string_lossy().to_string();
    let roles = if config_path.exists() {
        let config = std::fs::read_to_string(&config_path).unwrap_or_default();
        roles_from_json(&parse_roles_json(&config))
    } else {
        roles_from_json(&default_roles_json())
    };
    Ok(Envelope::ok(RoleAssignmentsResponse {
        oracle: roles.oracle,
        architect: roles.architect,
        builder: roles.builder,
        monitor: roles.monitor,
        config_path: path_text,
    }))
}

/// Persist updated role assignments back into litellm_config.yaml.
/// Performs surgical line replacement — preserves all comments and formatting.
#[tauri::command]
pub async fn set_role_assignments(
    app: tauri::AppHandle,
    assignments: serde_json::Value,
) -> Result<Envelope<ConfigPathResponse>, String> {
    let config_path = role_config_path(&app);
    if let Some(parent) = config_path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| format!("create config dir: {}", e))?;
    }
    let current = std::fs::read_to_string(&config_path).unwrap_or_default();
    let next = if current.trim().is_empty() {
        default_config_text(&assignments)
    } else {
        upsert_roles(current, &assignments)
    };
    std::fs::write(&config_path, next).map_err(|e| format!("write role config: {}", e))?;
    Ok(Envelope::ok(ConfigPathResponse { config_path: config_path.to_string_lossy().to_string() }))
}

// ─────────────────────────────────────────────────────────────────────────────
// ARTIFACT HANDOFF — Reveal session output in native file manager
// ─────────────────────────────────────────────────────────────────────────────

/// Open the session directory in the OS file manager (Explorer / Finder / Nautilus).
///
/// Called from HiveBuildLoop when a session reaches phase == "done".
/// Uses the `opener` crate which shells out to the correct platform command:
///   Windows: explorer.exe <path>
///   macOS:   open <path>
///   Linux:   xdg-open <path>
#[tauri::command]
pub async fn reveal_session_output(session_id: String) -> Result<(), String> {
    let output_dir = sessions_dir().join(&session_id);
    if !output_dir.exists() {
        return Err(format!(
            "Session directory not found: {}",
            output_dir.display()
        ));
    }
    opener::open(&output_dir).map_err(|e| format!("Failed to open file manager: {}", e))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn missing_config_defaults_to_local_first_roles() {
        // Asserted through the TYPED struct now, not by indexing a Value: a typo
        // in a key used to yield Value::Null and compare unequal for the wrong
        // reason, and a missing field could not be distinguished from a wrong one.
        let roles = roles_from_json(&parse_roles_json(""));
        assert_eq!(roles.oracle, "local/fast");
        assert_eq!(roles.architect, "local/fast");
        assert_eq!(roles.builder, "determinex/engineer");
        assert_eq!(roles.monitor, "determinex/observer");
    }

    #[test]
    fn upsert_roles_creates_config_when_missing() {
        let roles = serde_json::json!({
            "oracle": "cloud/claude-fast",
            "architect": "local/fast",
            "builder": "ollama/qwen2.5-coder:3b-instruct",
            "monitor": "determinex/observer"
        });
        let config = upsert_roles(String::new(), &roles);
        assert!(config.contains("determinex:"));
        assert!(config.contains("oracle: cloud/claude-fast"));
        assert!(config.contains("builder: ollama/qwen2.5-coder:3b-instruct"));
    }

    #[test]
    fn upsert_roles_preserves_existing_comments() {
        let roles = serde_json::json!({
            "oracle": "local/fast",
            "architect": "local/fast",
            "builder": "determinex/engineer",
            "monitor": "determinex/observer"
        });
        let config = "determinex:\n  roles:\n    oracle: cloud/old # keep\n    builder: cloud/old\n";
        let updated = upsert_roles(config.to_string(), &roles);
        assert!(updated.contains("oracle: local/fast # keep"));
        assert!(updated.contains("builder: determinex/engineer"));
    }
}
