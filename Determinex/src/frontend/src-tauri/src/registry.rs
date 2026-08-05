use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::fs;
use tauri::command;

use crate::db::AppDataDir;

#[derive(Serialize)]
pub struct ToolRecord {
    pub name: String,
    pub status: String,
    pub r#type: String,
    pub requires: Option<String>,
}

#[derive(Serialize)]
pub struct ToolRegistryResponse {
    pub tools: Vec<ToolRecord>,
    pub total: usize,
    pub online: usize,
    pub coverage: String,
}

#[derive(Deserialize)]
pub struct CustomModelPayload {
    pub id: String,
    pub provider: String,
    pub name: String,
    pub desc: String,
    pub elo_rating: i32,
    pub context_window: i32,
    pub speed_ms_per_token: Option<i32>,
    pub tier_id: String,

    // ── Reaching a provider this build has never heard of ────────────────────
    //
    // Ryan, live: "users should be able to add future llms that dont have access
    // at the moment, we should make sure we are compatable with EVERYTHING."
    //
    // Without these, a custom entry could only ever NAME a model -- it could not
    // say where to send the request, so anything outside the built-in provider
    // table was unreachable no matter what you registered. Almost every vendor
    // and every local server (vLLM, llama.cpp, LM Studio, Ollama, OpenRouter,
    // Together, and whatever ships next) exposes an OpenAI-compatible /v1
    // endpoint, so a base URL plus a model id is enough to reach a model that
    // does not exist yet.
    /// OpenAI-compatible base URL, e.g. "https://api.example.com/v1".
    pub base_url: Option<String>,
    /// NAME of the environment variable holding the key -- never the key itself.
    /// The registry file is plain JSON on disk and is read by the Python engine;
    /// putting a secret in it would violate this repo's secret-hygiene rules and
    /// leak it into every backup of the app data directory.
    pub api_key_env: Option<String>,
}

#[derive(Serialize)]
pub struct StandardResponse {
    status: String,
    message: String,
}

#[command]
pub fn get_models_registry(app_data: tauri::State<'_, AppDataDir>) -> Result<Value, String> {
    let registry_path = app_data.0.join("models_registry.json");
    if registry_path.exists() {
        let content = fs::read_to_string(&registry_path).map_err(|e| e.to_string())?;
        let json: Value = serde_json::from_str(&content).map_err(|e| e.to_string())?;
        Ok(json)
    } else {
        // First-run default: empty registry structure
        Ok(serde_json::json!({
            "tiers": [],
            "tandem_presets": []
        }))
    }
}

/// The persisted shape of a custom model. Built in one place so the
/// existing-tier and new-tier paths below cannot drift: they previously wrote two
/// separate inline literals, which is how a new field gets added to one and
/// silently missed on the other.
fn model_entry(payload: &CustomModelPayload) -> Value {
    let mut entry = serde_json::json!({
        "id": payload.id,
        "provider": payload.provider,
        "name": payload.name,
        "desc": payload.desc,
        "elo_rating": payload.elo_rating,
        "context_window": payload.context_window,
        "speed_ms_per_token": payload.speed_ms_per_token,
        // Marks this as user-added, so the Python engine knows to register a
        // provider for it and the UI can tell it apart from a shipped entry.
        "custom": true,
    });
    // Only written when present -- an absent base_url means "a provider this
    // build already knows", and an empty string would look like a real endpoint.
    if let Some(url) = payload.base_url.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        entry["base_url"] = Value::String(url.to_string());
    }
    if let Some(env) = payload.api_key_env.as_deref().map(str::trim).filter(|s| !s.is_empty()) {
        entry["api_key_env"] = Value::String(env.to_string());
    }
    entry
}

#[command]
pub fn add_custom_registry_model(
    payload: CustomModelPayload,
    app_data: tauri::State<'_, AppDataDir>,
) -> Result<StandardResponse, String> {
    let registry_path = app_data.0.join("models_registry.json");

    // Load existing registry or initialize with empty default on first write
    let mut data: Value = if registry_path.exists() {
        let content = fs::read_to_string(&registry_path).map_err(|e| e.to_string())?;
        serde_json::from_str(&content).map_err(|e| e.to_string())?
    } else {
        serde_json::json!({ "tiers": [], "tandem_presets": [] })
    };

    let tiers = data.get_mut("tiers").and_then(|t| t.as_array_mut());

    if let Some(tiers_arr) = tiers {
        let mut found_tier = false;

        for tier in tiers_arr.iter_mut() {
            if tier["tier_id"] == payload.tier_id {
                let models = tier.get_mut("models").and_then(|m| m.as_array_mut());
                if let Some(models_arr) = models {
                    // Check if exists
                    if models_arr.iter().any(|m| m["id"] == payload.id) {
                        return Ok(StandardResponse {
                            status: "success".to_string(),
                            message: "Model already exists in this tier.".to_string(),
                        });
                    }

                    models_arr.push(model_entry(&payload));
                }
                found_tier = true;
                break;
            }
        }

        if !found_tier {
            tiers_arr.push(serde_json::json!({
                "tier_id": payload.tier_id,
                "title": "Custom / Experimental",
                "color": "text-pink-400",
                "models": [model_entry(&payload)]
            }));
        }
    }

    let updated_json = serde_json::to_string_pretty(&data).map_err(|e| e.to_string())?;
    fs::write(&registry_path, updated_json).map_err(|e| e.to_string())?;

    Ok(StandardResponse {
        status: "success".to_string(),
        message: "Model integrated successfully.".to_string(),
    })
}

#[command]
pub fn get_tool_registry() -> Result<ToolRegistryResponse, String> {
    // Ported static list from main.py TOOL_DEPS
    let tools_def = vec![
        ("Semantic_Router", "local", Some("ChromaDB")),
        ("Vault_Read_Write", "local", None),
        ("Quarantine_Write", "local", None),
        ("Terminal_Execute", "local", None),
        ("Docker_Execute", "local", Some("Docker Desktop")),
        ("Ast_Analyzer", "local", None),
        ("Snyk_Security_Scan", "cli", Some("snyk")),
        ("Browser_Controller", "local", None),
        ("Network_Probe", "local", None),
        ("SQL_Inspector", "local", None),
        ("Git_Operator", "local", Some("git")),
        ("Formatting_Engine", "cli", Some("ruff")),
        ("Internet_Researcher", "local", None),
        ("AST_Mutator", "pip", Some("libcst")),
        ("Pull_Request_Manager", "key", Some("GITHUB_TOKEN")),
        ("Ticket_Syncer", "key", Some("LINEAR_API_KEY")),
        ("Design_Translator", "key", Some("FIGMA_KEY")),
        ("Telemetry_Ingestor", "key", Some("SENTRY_DSN")),
        ("Communication_Relay", "key", Some("SLACK_WEBHOOK_URL")),
        ("Persona_Swarm", "local", None),
        ("PostHog_Introspector", "key", Some("POSTHOG_PROJECT_KEY")),
        ("Subagent_Recruiter", "local", Some("Any LLM key")),
        ("AWS_Secrets_Manager", "key", Some("AWS_ACCESS_KEY_ID")),
        ("Vision_Parser", "key", Some("OPENAI_API_KEY")),
        ("Whisper_Audio_Transcriber", "key", Some("OPENAI_API_KEY")),
        ("Hardware_IO_Bridge", "key", Some("HARDWARE_IO_ENABLED")),
        ("Fastlane_Release_Manager", "cli", Some("fastlane")),
        ("Financial_Automator", "key", Some("STRIPE_API_KEY")),
        ("Social_Relay", "key", Some("SOCIAL_OAUTH_TOKEN")),
        ("Trigger_Knowledge_Ingestion", "local", None),
    ];

    let mut tools = Vec::new();
    let mut online_count = 0;

    for (name, r#type, requires) in tools_def {
        let mut status = "online";
        if r#type == "key" && requires.is_some() {
            // For now, assume missing keys until connected in registry
            status = "needs_key";
        } else if r#type == "cli" || r#type == "pip" {
            // Assume online for static render, frontend manages UI fallback
            status = "online";
        }

        if status == "online" {
            online_count += 1;
        }

        tools.push(ToolRecord {
            name: name.to_string(),
            status: status.to_string(),
            r#type: r#type.to_string(),
            requires: requires.map(|s| s.to_string()),
        });
    }

    let total = tools.len();
    Ok(ToolRegistryResponse {
        tools,
        total,
        online: online_count,
        coverage: format!("{}/{}", online_count, total),
    })
}
