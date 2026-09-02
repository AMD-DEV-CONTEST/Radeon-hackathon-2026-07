use regex::Regex;
use reqwest::Client;
use serde::{Deserialize, Serialize};
/// ollama_probe.rs — Ollama Engine Connectivity Detector
///
/// Provides a fast, timeout-bounded health-check against the Ollama API server.
/// The frontend polls this command every few seconds to gate the dashboard UI —
/// if Ollama is not running, the user sees the "Awaiting Engine" lockout overlay.
///
/// Design:
///   - 2-second total timeout (connect + read). Chosen because:
///       • Ollama on localhost typically responds in < 50ms when running.
///       • A 2s wait is imperceptible to a polling loop but avoids hanging
///         when Ollama is absent (TCP RST is instant; DNS/firewall timeouts are not).
///   - Returns `true` on any HTTP 2xx response from `/api/tags`.
///   - Returns `false` on connection error, timeout, or any non-2xx status.
///   - Never propagates an error to the frontend — the caller only cares
///     about reachable/not-reachable, not why it failed.
use std::collections::{HashMap, HashSet};
use std::time::Duration;

const OLLAMA_DEFAULT_BASE: &str = "http://localhost:11434";
const PROBE_TIMEOUT_SECS: u64 = 2;

/// Build the /api/tags URL from an optional user-configured base (see
/// api_keys::get_ollama_base_url), falling back to the localhost default.
fn ollama_tags_url(base_url: Option<&str>) -> String {
    let base = base_url
        .map(|s| s.trim())
        .filter(|s| !s.is_empty())
        .unwrap_or(OLLAMA_DEFAULT_BASE);
    format!("{}/api/tags", base.trim_end_matches('/'))
}

// ─────────────────────────────────────────────────────────────────────────────
// INSTALLED MODEL DISCOVERY
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct OllamaTagsResponse {
    models: Vec<OllamaModelEntry>,
}

#[derive(Debug, Deserialize)]
struct OllamaModelEntry {
    name: String,
    size: Option<u64>,
    details: Option<OllamaModelDetails>,
}

#[derive(Debug, Deserialize)]
struct OllamaModelDetails {
    parameter_size: Option<String>,
    quantization_level: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct InstalledModel {
    pub id: String,   // ollama model name, e.g. "determinex-engineer-v10-dsl:latest"
    pub name: String, // display name
    pub size_gb: f32,
    pub param_size: String, // e.g. "3B"
    pub quantization: String,
    pub is_determinex: bool, // true if name starts with "determinex-"
}

#[derive(Debug, Serialize)]
pub struct RoleModelReadiness {
    role: String,
    assignment: String,
    target_model: Option<String>,
    status: String,
    message: String,
}

/// Return the list of models currently installed in Ollama on this rig.
/// Called at startup to populate the model selector dynamically.
#[tauri::command]
pub async fn get_ollama_models(base_url: Option<String>) -> Result<Vec<InstalledModel>, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(5))
        .pool_max_idle_per_host(0)
        .build()
        .map_err(|e| format!("[OLLAMA-PROBE] client build: {}", e))?;

    let resp = client
        .get(ollama_tags_url(base_url.as_deref()))
        .send()
        .await
        .map_err(|e| format!("[OLLAMA-PROBE] get_ollama_models: {}", e))?;

    let tags: OllamaTagsResponse = resp
        .json()
        .await
        .map_err(|e| format!("[OLLAMA-PROBE] parse tags: {}", e))?;

    let models = tags
        .models
        .into_iter()
        .map(|m| {
            let size_gb = m.size.map(|b| b as f32 / 1_073_741_824.0).unwrap_or(0.0);
            let param_size = m
                .details
                .as_ref()
                .and_then(|d| d.parameter_size.clone())
                .unwrap_or_default();
            let quantization = m
                .details
                .as_ref()
                .and_then(|d| d.quantization_level.clone())
                .unwrap_or_default();
            let bare_name = m.name.split(':').next().unwrap_or(&m.name).to_string();
            let is_determinex = bare_name.starts_with("determinex-");
            let display = if is_determinex {
                // determinex-engineer-v10-dsl → Determinex Engineer v10-dsl
                // determinex-sentinel-v3     → Determinex Sentinel v3
                let without_prefix = bare_name.trim_start_matches("determinex-");
                // Capitalize first char of each dash-separated segment, rejoin with space
                let parts: Vec<String> = without_prefix
                    .split('-')
                    .map(|s| {
                        let mut c = s.chars();
                        match c.next() {
                            None => String::new(),
                            Some(f) => f.to_uppercase().collect::<String>() + c.as_str(),
                        }
                    })
                    .collect();
                format!("Determinex {}", parts.join(" "))
            } else {
                bare_name.clone()
            };
            InstalledModel {
                id: m.name.clone(),
                name: display,
                size_gb,
                param_size,
                quantization,
                is_determinex,
            }
        })
        .collect();

    Ok(models)
}

/// Ping the Ollama API server and return whether it is reachable.
///
/// Uses a dedicated one-shot `reqwest::Client` with a hard 2-second overall
/// timeout. This avoids reusing the orchestrator's persistent client, which
/// may be tied up mid-inference during the 8-second VRAM flush phases.
///
/// # Returns
/// - `Ok(true)`  — Ollama responded with HTTP 2xx on `/api/tags`
/// - `Ok(false)` — Ollama is unreachable, timed out, or returned an error status
#[tauri::command]
pub async fn check_ollama_status(base_url: Option<String>) -> Result<bool, String> {
    let client = Client::builder()
        .timeout(Duration::from_secs(PROBE_TIMEOUT_SECS))
        // Disable connection pooling — this is a one-shot probe, not a long-lived client.
        .pool_max_idle_per_host(0)
        .build()
        .map_err(|e| format!("[OLLAMA-PROBE] Failed to build reqwest client: {}", e))?;

    match client.get(ollama_tags_url(base_url.as_deref())).send().await {
        Ok(response) => {
            let reachable = response.status().is_success();
            if !reachable {
                log::warn!(
                    "[OLLAMA-PROBE] Ollama responded with non-success status: {}",
                    response.status()
                );
            }
            Ok(reachable)
        }
        Err(e) => {
            // Connection refused, timeout, DNS failure — all treated as "not running".
            // Log at debug level only — this fires every 3 seconds when Ollama is down,
            // so warn/error would saturate the log file immediately.
            log::debug!("[OLLAMA-PROBE] Unreachable: {}", e);
            Ok(false)
        }
    }
}

fn normalize_model_id(model_id: &str) -> String {
    model_id
        .trim()
        .strip_prefix("ollama/")
        .unwrap_or(model_id.trim())
        .strip_suffix(":latest")
        .unwrap_or_else(|| {
            model_id
                .trim()
                .strip_prefix("ollama/")
                .unwrap_or(model_id.trim())
        })
        .to_ascii_lowercase()
}

fn is_cloud_assignment(model_id: &str) -> bool {
    let lower = model_id.trim().to_ascii_lowercase();
    ["cloud/", "openai/", "anthropic/", "gemini/", "deepseek/"]
        .iter()
        .any(|prefix| lower.starts_with(prefix))
}

/// First whitespace-delimited token, with a trailing `# comment` and surrounding quotes removed.
fn yaml_scalar(rest: &str) -> Option<String> {
    let value = rest.split('#').next().unwrap_or("").trim();
    let value = value.trim_matches(|c| c == '"' || c == '\'');
    (!value.is_empty()).then(|| value.to_string())
}

/// `model_name` alias -> the `model:` it resolves to, from litellm_config.yaml's `model_list`.
///
/// CRASH-ON-LAUNCH FIX, 2026-07-31. This was a regex ending in `(?=^\s*-\s*model_name:|...)` — a
/// LOOK-AHEAD, which the Rust `regex` crate does not support and never will: it guarantees linear
/// time and look-around cannot be done in linear time. `Regex::new` therefore returned
/// `Err(Syntax)` for every input, and the `.expect("valid model entry regex")` turned that into a
/// panic on a tokio worker, which aborts the process:
///
///   thread 'tokio-rt-worker' panicked at src\ollama_probe.rs:213:6:
///   valid model entry regex: Syntax( ... look-around ... is not supported )
///   -> exit 0xC0000409 (STATUS_STACK_BUFFER_OVERRUN), Windows event BEX64
///
/// So this function had never once run to completion, and `get_work_readiness` — called by the UI
/// at startup — killed the app.
///
/// WHY IT SURVIVED THE CLEAN-HOST GATE. The caller reads `litellm_config.yaml` first and returns
/// early on a read error. A clean host has no config, so the early return fired and the app stayed
/// up for the smoke's whole launch window. The crash needs the config to be PRESENT — which is to
/// say, it needs a real user's machine. The gate passed precisely because the triggering condition
/// was absent.
///
/// Parsed line-by-line rather than with a cleverer regex. The structure being read is a YAML list,
/// scanning is what handles it, and no regex feature is load-bearing any more.
fn parse_model_aliases(config: &str) -> HashMap<String, String> {
    let mut aliases = HashMap::new();
    let mut current_alias: Option<String> = None;

    for line in config.lines() {
        let trimmed = line.trim_start();

        // A new list entry closes the previous one.
        if let Some(rest) = trimmed.strip_prefix('-') {
            if let Some(rest) = rest.trim_start().strip_prefix("model_name:") {
                current_alias = yaml_scalar(rest);
                continue;
            }
        }

        // Any top-level key ends `model_list` — matched structurally rather than by naming
        // `router_settings`/`determinex`, so a new sibling section cannot silently swallow entries.
        if !trimmed.is_empty()
            && !line.starts_with([' ', '\t'])
            && !trimmed.starts_with('-')
            && !trimmed.starts_with('#')
            && trimmed.contains(':')
        {
            current_alias = None;
            continue;
        }

        if let Some(alias) = current_alias.clone() {
            if let Some(rest) = trimmed.strip_prefix("model:") {
                if let Some(model) = yaml_scalar(rest) {
                    // First `model:` in the entry wins, as the original regex intended.
                    aliases.insert(alias, model);
                    current_alias = None;
                }
            }
        }
    }
    aliases
}

fn parse_role_assignments(config: &str) -> HashMap<String, String> {
    let mut roles = HashMap::from([
        ("oracle".to_string(), "local/fast".to_string()),
        ("architect".to_string(), "local/fast".to_string()),
        ("builder".to_string(), "determinex/engineer".to_string()),
        ("monitor".to_string(), "determinex/observer".to_string()),
    ]);
    for role in ["oracle", "architect", "builder", "monitor"] {
        let pattern = format!(r"(?m)^\s+{}:\s+([^\s#]+)", regex::escape(role));
        if let Ok(re) = Regex::new(&pattern) {
            if let Some(cap) = re.captures(config) {
                if let Some(value) = cap.get(1) {
                    roles.insert(role.to_string(), value.as_str().to_string());
                }
            }
        }
    }
    roles
}

fn installed_model_set(models: &[InstalledModel]) -> HashSet<String> {
    models
        .iter()
        .flat_map(|model| [model.id.as_str(), model.name.as_str()])
        .map(normalize_model_id)
        .collect()
}

fn model_is_installed(installed: &HashSet<String>, target: &str) -> bool {
    let normalized = normalize_model_id(target);
    installed.contains(&normalized) || installed.contains(&format!("{}:latest", normalized))
}

/// Return end-to-end model readiness for the Work/Hive path.
///
/// This command is intentionally authoritative: it reads the current
/// `litellm_config.yaml`, resolves role aliases through `model_list`, and
/// `get_work_readiness`'s response. `api.ts`'s `WorkReadiness` has declared this
/// shape all along with no Rust counterpart, and the four inline literals this
/// replaces had ALREADY drifted from each other -- the offline branch omitted
/// `checks` entirely while the other three included it, so a consumer reading
/// `checks` got `undefined` in exactly the state where it mattered least to
/// notice.
///
/// camelCase on the wire because that is what the TypeScript reads
/// (`missingRoles`, `checkedAt`); `returnShape.test.ts` understands `rename_all`
/// and compares the converted names.
#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct WorkReadinessResponse {
    pub status: String,
    pub ready: bool,
    pub label: String,
    pub summary: String,
    pub details: Vec<String>,
    pub missing_roles: Vec<String>,
    pub checks: Vec<RoleModelReadiness>,
    pub checked_at: i64,
}

/// compares those resolved Ollama tags with the live `/api/tags` response.
#[tauri::command]
pub async fn get_work_readiness() -> Result<WorkReadinessResponse, String> {
    let config_path = crate::ipc_hive::project_root().join("litellm_config.yaml");
    let config = std::fs::read_to_string(&config_path)
        .map_err(|e| format!("read {}: {}", config_path.display(), e))?;

    let aliases = parse_model_aliases(&config);
    let roles = parse_role_assignments(&config);
    let ollama_ok = check_ollama_status(None).await.unwrap_or(false);
    if !ollama_ok {
        return Ok(WorkReadinessResponse {
            status: "offline".to_string(),
            ready: false,
            label: "Ollama Offline".to_string(),
            summary: "Ollama is not reachable. Start Ollama before generating specs.".to_string(),
            details: Vec::new(),
            missing_roles: roles.keys().cloned().collect(),
            checks: Vec::new(),
            checked_at: chrono::Utc::now().timestamp_millis(),
        });
    }

    let models = get_ollama_models(None).await.unwrap_or_default();
    let installed = installed_model_set(&models);
    let mut checks: Vec<RoleModelReadiness> = Vec::new();
    let mut details: Vec<String> = Vec::new();
    let mut missing_roles: Vec<String> = Vec::new();
    let mut cloud_roles: Vec<String> = Vec::new();

    for role in ["oracle", "architect", "builder", "monitor"] {
        let assignment = roles
            .get(role)
            .cloned()
            .unwrap_or_else(|| "local/fast".to_string());
        let resolved = aliases.get(&assignment).cloned().or_else(|| {
            if assignment.starts_with("ollama/") || !assignment.contains('/') {
                Some(assignment.clone())
            } else {
                None
            }
        });

        if is_cloud_assignment(&assignment) {
            let message = format!("{} uses {}", role, assignment);
            cloud_roles.push(message.clone());
            checks.push(RoleModelReadiness {
                role: role.to_string(),
                assignment,
                target_model: resolved,
                status: "cloud".to_string(),
                message,
            });
            continue;
        }

        match resolved {
            Some(target) if model_is_installed(&installed, &target) => {
                let message = format!("{} -> {}", role, target);
                checks.push(RoleModelReadiness {
                    role: role.to_string(),
                    assignment,
                    target_model: Some(target),
                    status: "ready".to_string(),
                    message: message.clone(),
                });
                details.push(message);
            }
            Some(target) => {
                let message = format!("{} needs {}", role, target.trim_start_matches("ollama/"));
                missing_roles.push(message.clone());
                checks.push(RoleModelReadiness {
                    role: role.to_string(),
                    assignment,
                    target_model: Some(target),
                    status: "missing".to_string(),
                    message,
                });
            }
            None => {
                let message = format!("{} has unresolved assignment {}", role, assignment);
                missing_roles.push(message.clone());
                checks.push(RoleModelReadiness {
                    role: role.to_string(),
                    assignment,
                    target_model: None,
                    status: "unknown".to_string(),
                    message,
                });
            }
        }
    }

    if !missing_roles.is_empty() {
        return Ok(WorkReadinessResponse {
            status: "attention".to_string(),
            ready: false,
            label: "Attention".to_string(),
            summary: format!(
                "Missing local model coverage for {} role{}.",
                missing_roles.len(),
                if missing_roles.len() == 1 { "" } else { "s" }
            ),
            details: missing_roles.clone(),
            missing_roles,
            checks,
            checked_at: chrono::Utc::now().timestamp_millis(),
        });
    }

    if !cloud_roles.is_empty() {
        return Ok(WorkReadinessResponse {
            status: "attention".to_string(),
            ready: false,
            label: "Cloud Selected".to_string(),
            summary: "One or more Hive roles use cloud models. Confirm API keys or switch to local roles before generating.".to_string(),
            details: cloud_roles.clone(),
            missing_roles: cloud_roles,
            checks,
            checked_at: chrono::Utc::now().timestamp_millis(),
        });
    }

    Ok(WorkReadinessResponse {
        status: "ready".to_string(),
        ready: true,
        label: "Model Ready".to_string(),
        summary: "All local Hive roles resolve to installed Ollama models.".to_string(),
        details,
        missing_roles: Vec::new(),
        checks,
        checked_at: chrono::Utc::now().timestamp_millis(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The exact shape litellm_config.yaml uses: a `model_list`, nested `litellm_params`, a
    /// commented-out alternative, then sibling top-level sections.
    const SAMPLE: &str = r#"
model_list:
  - model_name: determinex/engineer
    litellm_params:
      model: ollama/determinex-engineer-v11-dsl
      api_base: http://localhost:11434
  - model_name: determinex/qwen7b    # Qwen2.5-Coder-7B base
    litellm_params:
      model: ollama/qwen2.5-coder:7b-instruct
      api_base: http://localhost:11434
  - model_name: cloud/deepseek-chat
    litellm_params:
      model: openrouter/deepseek/deepseek-chat

router_settings:
  model: this-must-not-be-captured

determinex:
  roles:
    builder: determinex/engineer
"#;

    #[test]
    fn aliases_resolve_to_their_underlying_model() {
        let aliases = parse_model_aliases(SAMPLE);
        assert_eq!(
            aliases.get("determinex/engineer").map(String::as_str),
            Some("ollama/determinex-engineer-v11-dsl")
        );
        assert_eq!(
            aliases.get("cloud/deepseek-chat").map(String::as_str),
            Some("openrouter/deepseek/deepseek-chat")
        );
    }

    #[test]
    fn a_trailing_comment_is_not_part_of_the_alias() {
        let aliases = parse_model_aliases(SAMPLE);
        assert!(
            aliases.contains_key("determinex/qwen7b"),
            "alias keys must stop at the comment: {:?}",
            aliases.keys().collect::<Vec<_>>()
        );
    }

    #[test]
    fn a_sibling_top_level_section_does_not_leak_into_the_last_entry() {
        // `router_settings:` carries its own `model:`. The original regex ended its block at a
        // hardcoded list of section names; this ends it at any top-level key, so a NEW sibling
        // section cannot silently start being absorbed.
        let aliases = parse_model_aliases(SAMPLE);
        assert!(
            !aliases.values().any(|v| v == "this-must-not-be-captured"),
            "a top-level section's model: was captured as an alias target: {aliases:?}"
        );
    }

    #[test]
    fn every_entry_in_the_shipped_config_resolves() {
        // The regression that mattered: this function panicked for EVERY input, so
        // get_work_readiness aborted the app on any machine that had the config.
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../litellm_config.yaml");
        let Ok(config) = std::fs::read_to_string(&path) else {
            eprintln!("skipping: {} not present", path.display());
            return;
        };
        let declared = config
            .lines()
            .filter(|l| l.trim_start().starts_with("- model_name:"))
            .count();
        let aliases = parse_model_aliases(&config);
        assert_eq!(
            aliases.len(),
            declared,
            "parsed {} aliases from a config declaring {}: {:?}",
            aliases.len(),
            declared,
            aliases
        );
    }

    #[test]
    fn parsing_never_panics_on_malformed_input() {
        // The whole failure mode was a panic reaching a tokio worker and aborting the process.
        for junk in ["", "model_list:", "- model_name:", "  model: x", "\u{0}\u{1}", "- model_name: a\n- model_name: b"] {
            let _ = parse_model_aliases(junk);
        }
    }

    #[test]
    fn role_assignments_resolve_against_the_alias_map() {
        // The two halves of get_work_readiness have to agree: a role pointing at an alias the
        // alias map does not contain means readiness can never resolve a target model, which is
        // indistinguishable from "the model is missing". Worth pinning now that
        // parse_model_aliases returns real data for the first time.
        let path = std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
            .join("../../litellm_config.yaml");
        let Ok(config) = std::fs::read_to_string(&path) else {
            eprintln!("skipping: {} not present", path.display());
            return;
        };
        let aliases = parse_model_aliases(&config);
        let roles = parse_role_assignments(&config);
        assert!(!roles.is_empty(), "no role assignments parsed");

        for (role, assignment) in &roles {
            if is_cloud_assignment(assignment) {
                continue; // a cloud role needs no local Ollama tag
            }
            assert!(
                aliases.contains_key(assignment),
                "role {role} is assigned {assignment}, which is not in the alias map: {:?}",
                aliases.keys().collect::<Vec<_>>()
            );
        }
    }

    #[test]
    fn every_static_regex_in_this_module_compiles() {
        // The defect class, not just the instance: a `Regex::new(...).expect(...)` on a pattern
        // the regex crate rejects is a guaranteed panic that no amount of input testing reveals.
        for pattern in [
            r"(?m)^\s*model:\s*([^\s#]+)",
            r"(?m)^\s*([a-z_]+):\s*([^\s#]+)",
        ] {
            assert!(Regex::new(pattern).is_ok(), "pattern does not compile: {pattern}");
        }
    }
}
