use reqwest::Client;
use serde::{Deserialize, Serialize};
use std::time::Duration;
use tauri::Manager;
use rusqlite::{OptionalExtension, Row};

use super::types::OrchestratorError;
use super::pipeline_models::ModelRoute;

pub const OLLAMA_BASE: &str = "http://localhost:11434/api/generate";
pub const OLLAMA_TIMEOUT_SECS: u64 = 120;
pub const CLOUD_TIMEOUT_SECS: u64 = 60;
pub const CONFIDENCE_THRESHOLD: f32 = 0.75;
pub const MAX_PROMPT_BYTES: usize = 512 * 1024;

#[derive(Serialize)]
pub struct OllamaOptions {
    pub num_ctx: u32,
}

#[derive(Serialize)]
pub struct OllamaRequest<'a> {
    pub model: &'a str,
    pub prompt: &'a str,
    pub stream: bool,
    pub format: &'a str,
    pub keep_alive: i32,
    pub options: OllamaOptions,
}

#[derive(Deserialize)]
pub struct OllamaResponse {
    pub response: String,
    pub done: bool,
}

#[derive(Serialize)]
pub struct OpenAIMessage<'a> {
    pub role: &'a str,
    pub content: &'a str,
}

#[derive(Serialize)]
pub struct OpenAIRequest<'a> {
    pub model: &'a str,
    pub messages: Vec<OpenAIMessage<'a>>,
    pub response_format: Option<serde_json::Value>,
}

#[derive(Deserialize)]
pub struct OpenAIResponse {
    pub choices: Vec<OpenAIChoice>,
}

#[derive(Deserialize)]
pub struct OpenAIChoice {
    pub message: OpenAIMessageData,
}

#[derive(Deserialize)]
pub struct OpenAIMessageData {
    pub content: String,
}

pub async fn call_model(
    client: &Client,
    model_route: &ModelRoute,
    prompt: &str,
    app_handle: &tauri::AppHandle,
) -> Result<String, OrchestratorError> {
    let is_offline = {
        let state = app_handle.state::<crate::db::DbState>();
        let db = state.conn.lock().unwrap();
        let mut stmt = db.prepare("SELECT value FROM settings WHERE key = 'networkPolicy'").unwrap();
        let policy: String = stmt.query_row([], |row: &Row| row.get(0)).unwrap_or_else(|_| "offline".to_string());
        policy == "offline" || policy == "cloaked"
    };

    match model_route {
        ModelRoute::Ollama { model } => {
            call_ollama(client, model, prompt).await
        }
        _ => {
            if is_offline {
                return Err(OrchestratorError::transport(
                    "cloud_route_blocked_by_offline_policy".to_string()
                ));
            }
            call_cloud(client, model_route, prompt, app_handle).await
        }
    }
}

// ─── OpenRouter transport ──────────────────────────────────────────────────────
// OpenRouter is OpenAI-compatible but requires:
//   - Base URL:  https://openrouter.ai/api/v1/chat/completions
//   - Auth:      Authorization: Bearer $OPENROUTER_API_KEY
//   - Headers:   HTTP-Referer (site URL), X-Title (app name) — for rankings
// Free models (pricing.prompt == "0") work with any valid key and cost $0.
// Rate limits vary by model; the 1.5s inter_call_pause in litellm_config.yaml
// keeps us well within the shared free-tier limits.
async fn call_openrouter(
    client: &Client,
    model: &str,
    prompt: &str,
    app_handle: &tauri::AppHandle,
) -> Result<String, OrchestratorError> {
    // Read key from DB first; fall back to env var so dev-mode .env works too.
    let api_key = {
        let from_db = {
            let state = app_handle.state::<crate::db::DbState>();
            let db = state.conn.lock().unwrap();
            let mut stmt = db.prepare("SELECT value FROM api_keys WHERE provider = 'openrouter'").unwrap();
            stmt.query_row([], |row: &Row| row.get::<_, String>(0)).optional().unwrap_or(None)
        };
        match from_db {
            Some(k) if !k.is_empty() => k,
            _ => {
                // Fall back to environment variable (works when running from dev terminal)
                std::env::var("OPENROUTER_API_KEY")
                    .or_else(|_| std::env::var("OPENROUTER_API_KEY_2"))
                    .map_err(|_| OrchestratorError::transport(
                        "No OpenRouter API key found. Set OPENROUTER_API_KEY in .env or add it via Settings → API Keys.".to_string()
                    ))?
            }
        }
    };

    let safe_prompt = if prompt.len() > MAX_PROMPT_BYTES {
        let mut end = MAX_PROMPT_BYTES;
        while !prompt.is_char_boundary(end) {
            end -= 1;
        }
        log::warn!("[Orchestrator/OpenRouter] Prompt for {} is {} bytes, truncating.", model, prompt.len());
        &prompt[..end]
    } else {
        prompt
    };

    let body = OpenAIRequest {
        model,
        messages: vec![OpenAIMessage { role: "user", content: safe_prompt }],
        response_format: Some(serde_json::json!({ "type": "json_object" })),
    };

    log::info!("[Orchestrator/OpenRouter] Calling model={}", model);

    let response = client
        .post("https://openrouter.ai/api/v1/chat/completions")
        .header("Authorization", format!("Bearer {}", api_key))
        .header("HTTP-Referer", "https://determinex.ai")
        .header("X-Title", "Determinex IDE")
        .json(&body)
        .timeout(Duration::from_secs(CLOUD_TIMEOUT_SECS * 2)) // free tier can be slower
        .send()
        .await
        .map_err(|e| OrchestratorError::transport(format!("OpenRouter transport error: {}", e)))?;

    if !response.status().is_success() {
        let status = response.status();
        let text = response.text().await.unwrap_or_default();
        return Err(OrchestratorError::transport(format!(
            "OpenRouter HTTP {} for model {}: {}",
            status, model, text
        )));
    }

    let parsed: OpenAIResponse = response.json().await.map_err(|e| {
        OrchestratorError::transport(format!("Failed to parse OpenRouter JSON: {}", e))
    })?;

    if let Some(choice) = parsed.choices.into_iter().next() {
        Ok(choice.message.content)
    } else {
        Err(OrchestratorError::transport(format!(
            "OpenRouter returned no choices for model {}",
            model
        )))
    }
}

async fn call_cloud(
    client: &Client,
    model_route: &ModelRoute,
    prompt: &str,
    app_handle: &tauri::AppHandle,
) -> Result<String, OrchestratorError> {
    let (api_key_name, base_url, model_name, expects_json_format) = match model_route {
        ModelRoute::DeepSeek { model } => ("deepseek", "https://api.deepseek.com/chat/completions", model, true),
        ModelRoute::Mistral { model } => ("mistral", "https://api.mistral.ai/v1/chat/completions", model, true),
        ModelRoute::Groq { model } => ("groq", "https://api.groq.com/openai/v1/chat/completions", model, true),
        ModelRoute::OpenAI { model } => ("openai", "https://api.openai.com/v1/chat/completions", model, true),
        ModelRoute::Anthropic { model } => ("anthropic", "https://api.anthropic.com/v1/messages", model, false), // simplistic placeholder
        ModelRoute::Gemini { model } => ("gemini", "https://generativelanguage.googleapis.com/v1beta/models/", model, false),
        ModelRoute::OpenRouter { model } => {
            // Routed above via call_openrouter — this arm is unreachable.
            return call_openrouter(client, model, prompt, app_handle).await;
        }
        ModelRoute::Ollama { .. } => unreachable!(),
    };

    let api_key = {
        let state = app_handle.state::<crate::db::DbState>();
        let db = state.conn.lock().unwrap();
        let mut stmt = db.prepare("SELECT value FROM api_keys WHERE provider = ?").unwrap();
        let key: Option<String> = stmt.query_row([api_key_name], |row: &Row| row.get(0)).optional().unwrap_or(None);
        match key {
            Some(k) if !k.is_empty() => k,
            _ => return Err(OrchestratorError::transport(format!("No API key configured for provider: {}", api_key_name))),
        }
    };

    // For simplicity, treating all these as OpenAI compatible if they are. (DeepSeek, Mistral, Groq, OpenAI).
    // Anthropic and Gemini would need their specific payloads if invoked.
    if !expects_json_format {
        return Err(OrchestratorError::transport(format!("Provider {} not fully implemented for native cloud transport yet.", api_key_name)));
    }

    let safe_prompt = if prompt.len() > MAX_PROMPT_BYTES {
        let mut end = MAX_PROMPT_BYTES;
        while !prompt.is_char_boundary(end) {
            end -= 1;
        }
        &prompt[..end]
    } else {
        prompt
    };

    let body = OpenAIRequest {
        model: model_name,
        messages: vec![OpenAIMessage { role: "user", content: safe_prompt }],
        response_format: Some(serde_json::json!({ "type": "json_object" })),
    };

    let response = client
        .post(base_url)
        .header("Authorization", format!("Bearer {}", api_key))
        .json(&body)
        .timeout(Duration::from_secs(CLOUD_TIMEOUT_SECS))
        .send()
        .await
        .map_err(|e| OrchestratorError::transport(format!("Cloud transport error: {}", e)))?;

    if !response.status().is_success() {
        let text = response.text().await.unwrap_or_default();
        return Err(OrchestratorError::transport(format!("Cloud HTTP Error: {}", text)));
    }

    let parsed: OpenAIResponse = response.json().await.map_err(|e| {
        OrchestratorError::transport(format!("Failed to parse cloud JSON: {}", e))
    })?;

    if let Some(choice) = parsed.choices.into_iter().next() {
        Ok(choice.message.content)
    } else {
        Err(OrchestratorError::transport("Cloud response had no choices".to_string()))
    }
}

pub async fn call_ollama(
    client: &Client,
    model: &str,
    prompt: &str,
) -> Result<String, OrchestratorError> {
    let safe_prompt = if prompt.len() > MAX_PROMPT_BYTES {
        let mut end = MAX_PROMPT_BYTES;
        while !prompt.is_char_boundary(end) {
            end -= 1;
        }
        log::warn!(
            "[Orchestrator] Prompt for {} is {} bytes, truncating.",
            model, prompt.len()
        );
        &prompt[..end]
    } else {
        prompt
    };

    let body = OllamaRequest {
        model,
        prompt: safe_prompt,
        stream: false,
        format: "json",
        keep_alive: 0,
        options: OllamaOptions { num_ctx: 2048 },
    };

    let response = client
        .post(OLLAMA_BASE)
        .json(&body)
        .timeout(Duration::from_secs(OLLAMA_TIMEOUT_SECS))
        .send()
        .await
        .map_err(|e| {
            if e.is_timeout() {
                OrchestratorError::transport("Ollama inference timed out".to_string())
            } else if e.is_connect() {
                OrchestratorError::transport("Cannot reach Ollama".to_string())
            } else {
                OrchestratorError::transport(format!("Ollama transport error: {}", e))
            }
        })?;

    if !response.status().is_success() {
        return Err(OrchestratorError::transport(format!("Ollama HTTP {}", response.status())));
    }

    let ollama_resp: OllamaResponse = response.json().await.map_err(|e| {
        OrchestratorError::transport(format!("Failed to parse Ollama envelope: {}", e))
    })?;

    if !ollama_resp.done {
        return Err(OrchestratorError::transport("Ollama response was not marked done".to_string()));
    }

    Ok(ollama_resp.response)
}
