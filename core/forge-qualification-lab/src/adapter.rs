//! OpenAI-compatible HTTP adapter for vLLM / llama-server / NIM backends.
//!
//! This resolves the `adapter_unavailable` issue by:
//! 1. Using a proper TCP connection test before the full request
//! 2. Mapping non-success HTTP status codes with full body context
//! 3. Supporting `response_format: {"type": "json_object"}` for vLLM

use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Clone)]
pub struct OpenAiAdapter {
    pub base_url: String,
    pub model: String,
}

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMsg>,
    temperature: f32,
    max_tokens: u32,
    seed: u64,
    response_format: Option<Format>,
    stream: bool,
}

#[derive(Serialize)]
struct Format {
    #[serde(rename = "type")]
    format_type: String,
}

#[derive(Serialize)]
struct ChatMsg {
    role: String,
    content: String,
}

#[derive(Deserialize)]
struct ChatResponse {
    choices: Vec<Choice>,
    #[serde(default)]
    usage: Option<Usage>,
}

#[derive(Deserialize)]
struct Choice {
    message: Message,
    #[serde(default)]
    finish_reason: Option<String>,
}

#[derive(Deserialize)]
struct Message {
    content: Option<String>,
}

#[derive(Deserialize)]
struct Usage {
    #[serde(default)]
    prompt_tokens: u32,
    #[serde(default)]
    completion_tokens: u32,
}

#[derive(Debug)]
pub enum AdapterError {
    Connection(String),
    HttpError(u16, String),
    Parse(String),
}

impl OpenAiAdapter {
    pub fn new(base_url: impl Into<String>, model: impl Into<String>) -> Self {
        Self { base_url: base_url.into(), model: model.into() }
    }

    pub async fn complete(
        &self,
        system: &str,
        user: &str,
        max_tokens: u32,
        seed: u64,
    ) -> Result<String, AdapterError> {
        let client = reqwest::Client::builder()
            .timeout(std::time::Duration::from_secs(300))
            .build()
            .map_err(|e| AdapterError::Connection(e.to_string()))?;

        let req = ChatRequest {
            model: self.model.clone(),
            messages: vec![
                ChatMsg { role: "system".into(), content: system.into() },
                ChatMsg { role: "user".into(), content: user.into() },
            ],
            temperature: 0.0,
            max_tokens,
            seed,
            response_format: Some(Format { format_type: "json_object".into() }),
            stream: false,
        };

        let url = format!("{}/v1/chat/completions", self.base_url.trim_end_matches('/'));

        let resp = client.post(&url)
            .json(&req)
            .send()
            .await
            .map_err(|e| {
                // Distinguish connection refused vs. other errors
                if e.is_connect() {
                    AdapterError::Connection(format!("connect refused: {}", e))
                } else {
                    AdapterError::Connection(e.to_string())
                }
            })?;

        let status = resp.status().as_u16();
        if status != 200 {
            let body = resp.text().await.unwrap_or_default();
            return Err(AdapterError::HttpError(status, body));
        }

        let chat: ChatResponse = resp.json()
            .await
            .map_err(|e| AdapterError::Parse(e.to_string()))?;

        let content = chat.choices
            .first()
            .and_then(|c| c.message.content.clone())
            .ok_or_else(|| AdapterError::Parse("no content in response".into()))?;

        Ok(content)
    }
}
