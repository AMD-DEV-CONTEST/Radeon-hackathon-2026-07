use anyhow::Result;
use futures::StreamExt;
use reqwest::Client;
use serde::Deserialize;
use std::time::{Duration, Instant};
use tokio::sync::mpsc;
use tracing::info;

use crate::chat::*;
use crate::profile::ModelProfile;
use agent_core::error::AgentError;
use agent_core::event::{ModelResult, TokenUsage};

/// Events during streaming
#[derive(Debug, Clone)]
pub enum StreamEvent {
    Token(String),
    ReasoningToken(String),
    Done {
        content: String,
        reasoning_content: Option<String>,
        finish_reason: String,
        usage: Option<ChatUsage>,
    },
    Error(String),
}

/// vLLM client for DGX Spark
#[derive(Clone)]
pub struct VllmClient {
    client: Client,
    profile: ModelProfile,
}

/// Basic model metadata returned by an OpenAI-compatible `/models` endpoint.
#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub struct AvailableModel {
    pub id: String,
    #[serde(default)]
    pub owned_by: String,
}

#[derive(Debug, Deserialize)]
struct ModelList {
    data: Vec<AvailableModel>,
}

impl VllmClient {
    pub fn new(profile: ModelProfile) -> Self {
        let client = Client::builder()
            .timeout(Duration::from_secs(profile.timeouts.model_secs))
            .pool_max_idle_per_host(0)
            .build()
            .unwrap_or_else(|e| {
                tracing::warn!(
                    "Failed to build custom HTTP client: {e}. Falling back to default client."
                );
                Client::new()
            });
        Self { client, profile }
    }

    /// Check if the model service is healthy
    pub async fn health_check(&self) -> Result<bool> {
        let resp = self
            .authorize(self.client.get(self.profile.models_url()))
            .timeout(Duration::from_secs(self.profile.timeouts.health_secs))
            .send()
            .await;
        match resp {
            Ok(r) => Ok(r.status().is_success()),
            Err(_) => Ok(false),
        }
    }

    /// List model IDs exposed by the configured endpoint.
    pub async fn list_models(&self) -> std::result::Result<Vec<AvailableModel>, AgentError> {
        let response = self
            .authorize(self.client.get(self.profile.models_url()))
            .timeout(Duration::from_secs(self.profile.timeouts.health_secs))
            .send()
            .await
            .map_err(|error| AgentError::InfrastructureError {
                detail: format!("Failed to list models: {error}"),
            })?;
        let status = response.status().as_u16();
        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(AgentError::TransportError { status, body });
        }
        response
            .json::<ModelList>()
            .await
            .map(|models| models.data)
            .map_err(|error| AgentError::InfrastructureError {
                detail: format!("Failed to parse model list: {error}"),
            })
    }

    /// Build a ChatRequest from messages.
    /// `max_tokens` is computed dynamically:
    ///   model_context_tokens - estimated_prompt_tokens - safety_tokens
    /// so the model always gets the maximum possible output budget.
    fn build_request(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
        tool_choice: Option<ToolChoice>,
    ) -> ChatRequest {
        // Rough estimate: 1 token ≈ 4 chars for English/code, 1.5 chars for CJK.
        // We use a conservative 4 chars/token to avoid severely overestimating XML/Code.
        let estimated_prompt_tokens: u32 = messages
            .iter()
            .map(|m| {
                let mut chars = m.content.as_deref().unwrap_or("").len();
                if let Some(calls) = &m.tool_calls {
                    for c in calls {
                        chars += c.function.name.len();
                        chars += c.function.arguments.len();
                    }
                }
                (chars as u32) / 4 + 10 // +10 for role/overhead per message
            })
            .sum();

        let dynamic_max = self
            .profile
            .context
            .model_context_tokens
            .saturating_sub(estimated_prompt_tokens)
            .saturating_sub(self.profile.context.safety_tokens);

        // Clamp: at least 4096, at most max_completion_tokens from profile
        let max_tokens = dynamic_max
            .max(4096)
            .min(self.profile.context.max_completion_tokens);

        ChatRequest {
            model: self.profile.model.name.clone(),
            messages,
            temperature: self.profile.sampling.temperature,
            top_p: self.profile.sampling.top_p,
            max_tokens,
            max_completion_tokens: Some(max_tokens),
            stream: false,
            tools,
            tool_choice,
            chat_template_kwargs: if !self.profile.thinking.enabled {
                Some(ChatTemplateKwargs {
                    enable_thinking: false,
                })
            } else {
                Some(ChatTemplateKwargs {
                    enable_thinking: true,
                })
            },
        }
    }

    /// Non-streaming chat completion. Returns ModelResult.
    pub async fn chat(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
        tool_choice: Option<ToolChoice>,
    ) -> std::result::Result<ModelResult, AgentError> {
        let max_attempts = self.profile.run.retry_http_5xx_count.max(1) as u32;
        let mut attempt = 1;

        loop {
            match self
                .chat_internal(messages.clone(), tools.clone(), tool_choice.clone())
                .await
            {
                Ok(res) => return Ok(res),
                Err(e) => {
                    if attempt >= max_attempts {
                        return Err(e);
                    }
                    tracing::warn!(
                        "Model API error (attempt {}/{}): {}. Retrying in 2 seconds...",
                        attempt,
                        max_attempts,
                        e
                    );
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    attempt += 1;
                }
            }
        }
    }

    async fn chat_internal(
        &self,
        messages: Vec<ChatMessage>,
        tools: Option<Vec<Tool>>,
        tool_choice: Option<ToolChoice>,
    ) -> std::result::Result<ModelResult, AgentError> {
        let request = self.build_request(messages, tools, tool_choice);
        let url = self.profile.chat_url();
        let start = Instant::now();

        let response = self
            .authorize(self.client.post(&url))
            .json(&request)
            .send()
            .await
            .map_err(|e| {
                if e.is_timeout() {
                    AgentError::Timeout {
                        seconds: self.profile.timeouts.model_secs,
                        state: "Generating".to_string(),
                    }
                } else {
                    AgentError::InfrastructureError {
                        detail: format!("HTTP request failed: {e}"),
                    }
                }
            })?;

        let status = response.status().as_u16();
        let elapsed = start.elapsed().as_secs_f64();

        if !response.status().is_success() {
            let body = response.text().await.unwrap_or_default();
            return Err(AgentError::TransportError { status, body });
        }

        let chat_response: ChatResponse =
            response
                .json()
                .await
                .map_err(|e| AgentError::InfrastructureError {
                    detail: format!("Failed to parse response JSON: {e}"),
                })?;

        let choice =
            chat_response
                .choices
                .first()
                .ok_or_else(|| AgentError::InfrastructureError {
                    detail: "No choices in response".to_string(),
                })?;

        let message = choice
            .message
            .as_ref()
            .ok_or_else(|| AgentError::InfrastructureError {
                detail: "No message in choice".to_string(),
            })?;

        let content = message.content.clone().unwrap_or_default();
        let reasoning_content = message.reasoning_content.clone();
        let tool_calls = message.tool_calls.clone().map(|calls| {
            calls
                .into_iter()
                .map(|tc| agent_core::event::ModelToolCall {
                    id: tc.id,
                    name: tc.function.name,
                    arguments: tc.function.arguments,
                })
                .collect()
        });
        let finish_reason = choice
            .finish_reason
            .clone()
            .unwrap_or_else(|| "unknown".to_string());

        let usage = chat_response
            .usage
            .map(|u| TokenUsage {
                prompt_tokens: u.prompt_tokens,
                completion_tokens: u.completion_tokens,
                total_tokens: u.total_tokens,
            })
            .unwrap_or(TokenUsage {
                prompt_tokens: 0,
                completion_tokens: 0,
                total_tokens: 0,
            });

        info!(
            status,
            finish_reason = %finish_reason,
            prompt_tokens = usage.prompt_tokens,
            completion_tokens = usage.completion_tokens,
            elapsed_secs = elapsed,
            "Model response received"
        );

        // finish_reason=tool_calls means the model wants to call tools.
        match finish_reason.as_str() {
            "stop" | "length" | "tool_calls" => {}
            other => {
                return Err(AgentError::IncompleteGeneration {
                    reason: other.to_string(),
                });
            }
        }

        if content.trim().is_empty() && tool_calls.is_none() {
            return Err(AgentError::IncompleteGeneration {
                reason: format!(
                    "empty content and no tools with finish_reason={}",
                    finish_reason
                ),
            });
        }

        // Warn when output was truncated so the executor can adapt
        if finish_reason == "length" {
            tracing::warn!(
                completion_tokens = usage.completion_tokens,
                "Model output truncated (finish_reason=length); partial content returned"
            );
        }

        Ok(ModelResult {
            content,
            reasoning_content,
            tool_calls,
            finish_reason,
            usage,
            elapsed_secs: elapsed,
            http_status: status,
        })
    }

    /// Streaming chat completion. Returns a receiver for StreamEvents.
    pub async fn chat_stream(
        &self,
        messages: Vec<ChatMessage>,
    ) -> std::result::Result<mpsc::Receiver<StreamEvent>, AgentError> {
        let mut request = self.build_request(messages, None, None);
        request.stream = true;
        let url = self.profile.chat_url();
        let timeout_secs = self.profile.timeouts.model_secs;

        let (tx, rx) = mpsc::channel(256);
        let client_clone = self.clone();

        tokio::spawn(async move {
            let max_attempts = client_clone.profile.run.retry_http_5xx_count.max(1) as u32;
            let mut attempt = 1;

            loop {
                let response = match client_clone
                    .authorize(client_clone.client.post(&url))
                    .json(&request)
                    .send()
                    .await
                {
                    Ok(res) => res,
                    Err(e) => {
                        let is_timeout = e.is_timeout();
                        let error_msg = if is_timeout {
                            format!("Timeout after {}s", timeout_secs)
                        } else {
                            format!("HTTP request failed: {}", e)
                        };

                        if attempt >= max_attempts {
                            tx.send(StreamEvent::Error(error_msg)).await.ok();
                            return;
                        }
                        tracing::warn!(
                            "Stream setup error (attempt {}/{}): {}. Retrying in 2 seconds...",
                            attempt,
                            max_attempts,
                            error_msg
                        );
                        tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                        attempt += 1;
                        continue;
                    }
                };

                let status = response.status().as_u16();
                if !response.status().is_success() {
                    let body = response.text().await.unwrap_or_default();
                    let error_msg = format!("HTTP {}: {}", status, body);
                    if attempt >= max_attempts {
                        tx.send(StreamEvent::Error(error_msg)).await.ok();
                        return;
                    }
                    tracing::warn!(
                        "Stream setup error (attempt {}/{}): {}. Retrying in 2 seconds...",
                        attempt,
                        max_attempts,
                        error_msg
                    );
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    attempt += 1;
                    continue;
                }

                let mut stream = response.bytes_stream();
                let mut buffer = String::new();
                let mut full_content = String::new();
                let mut full_reasoning = String::new();
                let mut last_finish_reason = String::new();
                let mut last_usage: Option<ChatUsage> = None;
                let mut stream_failed = false;

                while let Some(chunk_result) = stream.next().await {
                    match chunk_result {
                        Ok(bytes) => {
                            buffer.push_str(&String::from_utf8_lossy(&bytes));

                            while let Some(pos) = buffer.find('\n') {
                                let line = buffer[..pos].trim().to_string();
                                buffer = buffer[pos + 1..].to_string();

                                if line.is_empty() || line.starts_with(':') {
                                    continue;
                                }

                                if let Some(data) = line.strip_prefix("data: ") {
                                    if data.trim() == "[DONE]" {
                                        let reasoning = if full_reasoning.is_empty() {
                                            None
                                        } else {
                                            Some(full_reasoning.clone())
                                        };
                                        tx.send(StreamEvent::Done {
                                            content: full_content.clone(),
                                            reasoning_content: reasoning,
                                            finish_reason: last_finish_reason.clone(),
                                            usage: last_usage.clone(),
                                        })
                                        .await
                                        .ok();
                                        return;
                                    }

                                    if let Ok(chunk) = serde_json::from_str::<StreamChunk>(data) {
                                        if let Some(usage) = chunk.usage {
                                            last_usage = Some(usage);
                                        }
                                        for choice in &chunk.choices {
                                            if let Some(fr) = &choice.finish_reason {
                                                last_finish_reason = fr.clone();
                                            }
                                            if let Some(delta) = &choice.delta {
                                                if let Some(c) = &delta.content {
                                                    full_content.push_str(c);
                                                    tx.send(StreamEvent::Token(c.clone()))
                                                        .await
                                                        .ok();
                                                }
                                                if let Some(r) = &delta.reasoning_content {
                                                    full_reasoning.push_str(r);
                                                    tx.send(StreamEvent::ReasoningToken(r.clone()))
                                                        .await
                                                        .ok();
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                        Err(e) => {
                            let error_msg = format!("Stream error: {e}");
                            if attempt >= max_attempts {
                                tx.send(StreamEvent::Error(error_msg)).await.ok();
                                return;
                            }
                            tracing::warn!(
                                "Stream read error (attempt {}/{}): {}. Retrying in 2 seconds...",
                                attempt,
                                max_attempts,
                                error_msg
                            );
                            stream_failed = true;
                            break;
                        }
                    }
                }

                if stream_failed {
                    tokio::time::sleep(std::time::Duration::from_secs(2)).await;
                    attempt += 1;
                    continue;
                }

                // Stream ended without [DONE]
                let reasoning = if full_reasoning.is_empty() {
                    None
                } else {
                    Some(full_reasoning)
                };
                tx.send(StreamEvent::Done {
                    content: full_content,
                    reasoning_content: reasoning,
                    finish_reason: last_finish_reason,
                    usage: last_usage,
                })
                .await
                .ok();
                return;
            }
        });

        Ok(rx)
    }

    /// Get the profile
    pub fn profile(&self) -> &ModelProfile {
        &self.profile
    }

    fn authorize(&self, request: reqwest::RequestBuilder) -> reqwest::RequestBuilder {
        match self.profile.resolve_api_key() {
            Some(key) => request.bearer_auth(key),
            None => request,
        }
    }
}
