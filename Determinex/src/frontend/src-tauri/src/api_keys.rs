use crate::db::DbState;
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use tauri::State;

#[derive(Deserialize)]
pub struct ApiKeysPayload {
    pub openai_key: Option<String>,
    pub anthropic_key: Option<String>,
    pub gemini_key: Option<String>,
    pub groq_key: Option<String>,
    pub deepseek_key: Option<String>,
    pub mistral_key: Option<String>,
    pub openrouter_key: Option<String>,
    pub kimi_key: Option<String>,
}

#[derive(Serialize)]
pub struct SuccessResponse {
    pub status: String,
}

#[tauri::command]
pub fn get_api_key_status(state: State<'_, DbState>) -> Result<HashMap<String, bool>, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    let mut stmt = conn
        .prepare("SELECT provider FROM api_keys WHERE api_key IS NOT NULL AND api_key != '' AND provider NOT LIKE '\\_\\_%' ESCAPE '\\'")
        .map_err(|e| e.to_string())?;

    let active_providers_iter = stmt
        .query_map([], |row| {
            let provider: String = row.get(0)?;
            Ok(provider)
        })
        .map_err(|e| e.to_string())?;

    let mut status = HashMap::new();
    // Default all known providers to false
    status.insert("openai".to_string(), false);
    status.insert("anthropic".to_string(), false);
    status.insert("gemini".to_string(), false);
    status.insert("groq".to_string(), false);
    status.insert("deepseek".to_string(), false);
    status.insert("mistral".to_string(), false);
    status.insert("openrouter".to_string(), false);
    status.insert("kimi".to_string(), false);

    for provider_res in active_providers_iter {
        if let Ok(provider) = provider_res {
            status.insert(provider, true);
        }
    }

    Ok(status)
}

#[tauri::command]
pub fn save_api_keys(
    keys: ApiKeysPayload,
    state: State<'_, DbState>,
) -> Result<SuccessResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    // SQLite upsert
    let upsert = |provider: &str, key_val: &Option<String>| -> Result<(), String> {
        if let Some(val) = key_val {
            if !val.trim().is_empty() {
                conn.execute(
                    "INSERT INTO api_keys (provider, api_key) VALUES (?1, ?2)
                     ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP",
                    (provider, val),
                ).map_err(|e| e.to_string())?;
            }
        }
        Ok(())
    };

    upsert("openai", &keys.openai_key)?;
    upsert("anthropic", &keys.anthropic_key)?;
    upsert("gemini", &keys.gemini_key)?;
    upsert("groq", &keys.groq_key)?;
    upsert("deepseek", &keys.deepseek_key)?;
    upsert("mistral", &keys.mistral_key)?;
    upsert("openrouter", &keys.openrouter_key)?;
    upsert("kimi", &keys.kimi_key)?;

    Ok(SuccessResponse {
        status: "success".to_string(),
    })
}

#[derive(Deserialize)]
pub struct ServiceKeyPayload {
    pub service: String,
    pub key: String,
}

#[tauri::command]
pub fn save_service_key(
    payload: ServiceKeyPayload,
    state: State<'_, DbState>,
) -> Result<SuccessResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;

    let env_var = match payload.service.to_uppercase().as_str() {
        "GITHUB" => "GITHUB_TOKEN",
        "SLACK" => "SLACK_WEBHOOK_URL",
        "FIGMA" => "FIGMA_KEY",
        "SENTRY" => "SENTRY_DSN",
        "LINEAR" => "LINEAR_API_KEY",
        "POSTHOG" => "POSTHOG_PROJECT_KEY",
        "AWS" => "AWS_ACCESS_KEY_ID",
        "STRIPE" => "STRIPE_API_KEY",
        "SOCIAL" => "SOCIAL_OAUTH_TOKEN",
        // Same row as save_api_keys -- a key saved through one dialog must be
        // visible to the other. These previously wrote "DEEPSEEK_API_KEY"/
        // "MISTRAL_API_KEY", a different row than save_api_keys's "deepseek"/
        // "mistral", so a key saved here was invisible to get_api_key_status.
        "DEEPSEEK" => "deepseek",
        "MISTRAL" => "mistral",
        "OPENROUTER" => "openrouter",
        other => return Err(format!("Unknown service: {}", other)),
    };

    if !payload.key.trim().is_empty() {
        conn.execute(
            "INSERT INTO api_keys (provider, api_key) VALUES (?1, ?2)
             ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP",
            (env_var, &payload.key),
        ).map_err(|e| e.to_string())?;
    }

    Ok(SuccessResponse {
        status: "success".to_string(),
    })
}

// Ollama's base URL isn't a secret -- stored in the same table (it's a
// generic local key-value store) under a dedicated row so it doesn't
// collide with the api-key boolean status map.
const OLLAMA_BASE_URL_ROW: &str = "__ollama_base_url";

#[tauri::command]
pub fn get_ollama_base_url(state: State<'_, DbState>) -> Result<Option<String>, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;
    let result: Result<String, _> = conn.query_row(
        "SELECT api_key FROM api_keys WHERE provider = ?1",
        [OLLAMA_BASE_URL_ROW],
        |row| row.get(0),
    );
    match result {
        Ok(url) => Ok(Some(url)),
        Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
        Err(e) => Err(e.to_string()),
    }
}

#[tauri::command]
pub fn save_ollama_base_url(url: String, state: State<'_, DbState>) -> Result<SuccessResponse, String> {
    let conn = state
        .conn
        .lock()
        .map_err(|e| format!("DbState mutex poisoned: {}", e))?;
    let trimmed = url.trim();
    if trimmed.is_empty() {
        conn.execute("DELETE FROM api_keys WHERE provider = ?1", [OLLAMA_BASE_URL_ROW])
            .map_err(|e| e.to_string())?;
    } else {
        conn.execute(
            "INSERT INTO api_keys (provider, api_key) VALUES (?1, ?2)
             ON CONFLICT(provider) DO UPDATE SET api_key=excluded.api_key, updated_at=CURRENT_TIMESTAMP",
            (OLLAMA_BASE_URL_ROW, trimmed),
        )
        .map_err(|e| e.to_string())?;
    }
    Ok(SuccessResponse {
        status: "success".to_string(),
    })
}
