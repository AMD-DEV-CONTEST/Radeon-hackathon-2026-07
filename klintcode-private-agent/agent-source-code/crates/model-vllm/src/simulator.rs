//! Persistent, scripted model simulator for offline development and testing.
//!
//! The simulator is intentionally part of the production model crate rather
//! than a test-only mock. CLI, TUI, pipeline tests, and demos can all select it
//! through a model profile without starting an HTTP model service.

use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::sync::mpsc;

use agent_core::error::AgentError;
use agent_core::event::{ModelResult, TokenUsage};

use crate::chat::{ChatMessage, ChatUsage, Tool, ToolChoice};
use crate::client::StreamEvent;
use crate::profile::ModelProfile;
use crate::tokenizer::{estimate_messages_tokens, estimate_tokens};

/// A complete deterministic simulation script.
#[derive(Debug, Clone, Deserialize)]
pub struct SimulatorScenario {
    pub name: String,
    #[serde(default)]
    pub description: String,
    /// Reuse the last response after the scripted sequence is exhausted.
    #[serde(default)]
    pub repeat_last: bool,
    #[serde(default)]
    pub default_latency_ms: u64,
    #[serde(default = "default_stream_chunk_chars")]
    pub stream_chunk_chars: usize,
    #[serde(default)]
    pub stream_delay_ms: u64,
    pub responses: Vec<SimulatorResponse>,
}

/// One model call in a scripted scenario.
#[derive(Debug, Clone, Deserialize)]
pub struct SimulatorResponse {
    pub id: String,
    /// Optional substring that must occur in the combined request messages.
    pub when_contains: Option<String>,
    /// Inline response body.
    pub content: Option<String>,
    /// Response fixture relative to the scenario file.
    pub content_file: Option<PathBuf>,
    pub reasoning_content: Option<String>,
    #[serde(default = "default_finish_reason")]
    pub finish_reason: String,
    pub latency_ms: Option<u64>,
    #[serde(default = "default_http_status")]
    pub http_status: u16,
    pub usage: Option<SimulatorUsage>,
    pub error: Option<SimulatorError>,
}

/// Optional explicit usage. Missing values are estimated locally.
#[derive(Debug, Clone, Default, Deserialize)]
pub struct SimulatorUsage {
    pub prompt_tokens: Option<u32>,
    pub completion_tokens: Option<u32>,
    pub total_tokens: Option<u32>,
}

/// Failure injected by a scenario response.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum SimulatorError {
    Transport { status: u16, body: String },
    Timeout { seconds: u64 },
    Infrastructure { detail: String },
    Incomplete { reason: String },
}

/// Recorded simulator call for assertions and diagnostics.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct SimulatorCall {
    pub sequence: usize,
    pub response_id: String,
    pub message_count: usize,
    pub prompt_preview: String,
}

#[derive(Debug, Default)]
struct SimulatorState {
    next_response: usize,
    calls: Vec<SimulatorCall>,
}

/// Thread-safe scripted model simulator.
#[derive(Clone)]
pub struct SimulatorClient {
    profile: ModelProfile,
    scenario: Arc<SimulatorScenario>,
    state: Arc<Mutex<SimulatorState>>,
}

impl SimulatorClient {
    /// Load and validate a scenario.
    pub fn load(profile: ModelProfile, path: &Path) -> Result<Self, AgentError> {
        let source =
            std::fs::read_to_string(path).map_err(|error| AgentError::InfrastructureError {
                detail: format!(
                    "Failed to read simulator scenario {}: {error}",
                    path.display()
                ),
            })?;
        let mut scenario: SimulatorScenario =
            toml::from_str(&source).map_err(|error| AgentError::InfrastructureError {
                detail: format!(
                    "Failed to parse simulator scenario {}: {error}",
                    path.display()
                ),
            })?;

        if scenario.responses.is_empty() {
            return Err(AgentError::InfrastructureError {
                detail: format!(
                    "Simulator scenario {} contains no responses",
                    path.display()
                ),
            });
        }
        if scenario.stream_chunk_chars == 0 {
            return Err(AgentError::InfrastructureError {
                detail: "Simulator stream_chunk_chars must be greater than zero".to_string(),
            });
        }

        let scenario_dir = path.parent().unwrap_or_else(|| Path::new("."));
        for response in &mut scenario.responses {
            match (&response.content, &response.content_file, &response.error) {
                (Some(_), Some(_), _) => {
                    return Err(AgentError::InfrastructureError {
                        detail: format!(
                            "Simulator response {} has both content and content_file",
                            response.id
                        ),
                    });
                }
                (None, Some(fixture), None) => {
                    let fixture_path = scenario_dir.join(fixture);
                    response.content =
                        Some(std::fs::read_to_string(&fixture_path).map_err(|error| {
                            AgentError::InfrastructureError {
                                detail: format!(
                                    "Failed to read simulator fixture {}: {error}",
                                    fixture_path.display()
                                ),
                            }
                        })?);
                }
                (None, None, None) => {
                    return Err(AgentError::InfrastructureError {
                        detail: format!(
                            "Simulator response {} has neither content nor error",
                            response.id
                        ),
                    });
                }
                _ => {}
            }
        }

        Ok(Self {
            profile,
            scenario: Arc::new(scenario),
            state: Arc::new(Mutex::new(SimulatorState::default())),
        })
    }

    /// Execute one deterministic non-streaming model call.
    pub async fn chat(
        &self,
        messages: Vec<ChatMessage>,
        _tools: Option<Vec<Tool>>,
        _tool_choice: Option<ToolChoice>,
    ) -> Result<ModelResult, AgentError> {
        let response = self.take_response(&messages)?;
        let latency_ms = response
            .latency_ms
            .unwrap_or(self.scenario.default_latency_ms);
        if latency_ms > 0 {
            tokio::time::sleep(Duration::from_millis(latency_ms)).await;
        }

        if let Some(error) = response.error {
            return Err(map_simulator_error(error));
        }
        if !(200..300).contains(&response.http_status) {
            return Err(AgentError::TransportError {
                status: response.http_status,
                body: response.content.unwrap_or_default(),
            });
        }
        if response.finish_reason != "stop" {
            return Err(AgentError::IncompleteGeneration {
                reason: response.finish_reason,
            });
        }

        let content = response.content.unwrap_or_default();
        if content.trim().is_empty() {
            return Err(AgentError::IncompleteGeneration {
                reason: "empty simulator content with finish_reason=stop".to_string(),
            });
        }

        let usage = calculate_usage(&messages, &content, response.usage);
        Ok(ModelResult {
            content,
            reasoning_content: response.reasoning_content,
            tool_calls: None,
            finish_reason: response.finish_reason,
            usage,
            elapsed_secs: latency_ms as f64 / 1_000.0,
            http_status: response.http_status,
        })
    }

    /// Execute a model call and replay its response as stream events.
    pub async fn chat_stream(
        &self,
        messages: Vec<ChatMessage>,
    ) -> Result<mpsc::Receiver<StreamEvent>, AgentError> {
        let result = self.chat(messages, None, None).await?;
        let chunk_chars = self.scenario.stream_chunk_chars;
        let delay_ms = self.scenario.stream_delay_ms;
        let (tx, rx) = mpsc::channel(256);

        tokio::spawn(async move {
            if let Some(reasoning) = &result.reasoning_content {
                for chunk in char_chunks(reasoning, chunk_chars) {
                    if tx.send(StreamEvent::ReasoningToken(chunk)).await.is_err() {
                        return;
                    }
                    delay_stream(delay_ms).await;
                }
            }
            for chunk in char_chunks(&result.content, chunk_chars) {
                if tx.send(StreamEvent::Token(chunk)).await.is_err() {
                    return;
                }
                delay_stream(delay_ms).await;
            }
            let usage = ChatUsage {
                prompt_tokens: result.usage.prompt_tokens,
                completion_tokens: result.usage.completion_tokens,
                total_tokens: result.usage.total_tokens,
            };
            tx.send(StreamEvent::Done {
                content: result.content,
                reasoning_content: result.reasoning_content,
                finish_reason: result.finish_reason,
                usage: Some(usage),
            })
            .await
            .ok();
        });

        Ok(rx)
    }

    /// Reset the scripted response cursor and recorded calls.
    pub fn reset(&self) {
        if let Ok(mut state) = self.state.lock() {
            *state = SimulatorState::default();
        }
    }

    /// Snapshot recorded calls.
    pub fn calls(&self) -> Vec<SimulatorCall> {
        self.state
            .lock()
            .map(|state| state.calls.clone())
            .unwrap_or_default()
    }

    pub fn scenario_name(&self) -> &str {
        &self.scenario.name
    }

    pub fn profile(&self) -> &ModelProfile {
        &self.profile
    }

    fn take_response(&self, messages: &[ChatMessage]) -> Result<SimulatorResponse, AgentError> {
        let combined_prompt = messages
            .iter()
            .map(|message| message.content.as_deref().unwrap_or(""))
            .collect::<Vec<_>>()
            .join("\n");
        let mut state = self
            .state
            .lock()
            .map_err(|_| AgentError::InfrastructureError {
                detail: "Simulator state lock is poisoned".to_string(),
            })?;

        let response_index = if state.next_response < self.scenario.responses.len() {
            state.next_response
        } else if self.scenario.repeat_last {
            self.scenario.responses.len() - 1
        } else {
            return Err(AgentError::InfrastructureError {
                detail: format!(
                    "Simulator scenario {} exhausted after {} calls",
                    self.scenario.name, state.next_response
                ),
            });
        };
        let response = self.scenario.responses[response_index].clone();

        if let Some(expected) = &response.when_contains {
            if !combined_prompt.contains(expected) {
                return Err(AgentError::InfrastructureError {
                    detail: format!(
                        "Simulator response {} expected request containing {:?}",
                        response.id, expected
                    ),
                });
            }
        }

        let sequence = state.calls.len() + 1;
        state.calls.push(SimulatorCall {
            sequence,
            response_id: response.id.clone(),
            message_count: messages.len(),
            prompt_preview: combined_prompt.chars().take(160).collect(),
        });
        state.next_response += 1;
        Ok(response)
    }
}

fn calculate_usage(
    messages: &[ChatMessage],
    content: &str,
    configured: Option<SimulatorUsage>,
) -> TokenUsage {
    let message_pairs = messages
        .iter()
        .map(|message| {
            (
                message.role.clone(),
                message.content.clone().unwrap_or_default(),
            )
        })
        .collect::<Vec<_>>();
    let estimated_prompt = estimate_messages_tokens(&message_pairs);
    let estimated_completion = estimate_tokens(content);
    let configured = configured.unwrap_or_default();
    let prompt_tokens = configured.prompt_tokens.unwrap_or(estimated_prompt);
    let completion_tokens = configured.completion_tokens.unwrap_or(estimated_completion);
    let total_tokens = configured
        .total_tokens
        .unwrap_or(prompt_tokens.saturating_add(completion_tokens));
    TokenUsage {
        prompt_tokens,
        completion_tokens,
        total_tokens,
    }
}

fn map_simulator_error(error: SimulatorError) -> AgentError {
    match error {
        SimulatorError::Transport { status, body } => AgentError::TransportError { status, body },
        SimulatorError::Timeout { seconds } => AgentError::Timeout {
            seconds,
            state: "Simulator".to_string(),
        },
        SimulatorError::Infrastructure { detail } => AgentError::InfrastructureError { detail },
        SimulatorError::Incomplete { reason } => AgentError::IncompleteGeneration { reason },
    }
}

fn char_chunks(content: &str, chunk_chars: usize) -> Vec<String> {
    let chars = content.chars().collect::<Vec<_>>();
    chars
        .chunks(chunk_chars)
        .map(|chunk| chunk.iter().collect())
        .collect()
}

async fn delay_stream(delay_ms: u64) {
    if delay_ms > 0 {
        tokio::time::sleep(Duration::from_millis(delay_ms)).await;
    }
}

fn default_finish_reason() -> String {
    "stop".to_string()
}

fn default_http_status() -> u16 {
    200
}

fn default_stream_chunk_chars() -> usize {
    16
}

#[cfg(test)]
mod tests {
    use std::io::Write;

    use tempfile::NamedTempFile;

    use super::*;

    fn profile() -> ModelProfile {
        toml::from_str(include_str!("../../../profiles/simulator.toml")).expect("simulator profile")
    }

    fn scenario(source: &str) -> SimulatorClient {
        let mut file = NamedTempFile::new().expect("scenario file");
        file.write_all(source.as_bytes()).expect("write scenario");
        SimulatorClient::load(profile(), file.path()).expect("load simulator")
    }

    fn messages(content: &str) -> Vec<ChatMessage> {
        vec![ChatMessage {
            role: "user".to_string(),
            content: Some(content.to_string()),
            name: None,
            tool_calls: None,
            tool_call_id: None,
        }]
    }

    #[tokio::test]
    async fn scripted_calls_are_ordered_and_recorded() {
        let client = scenario(
            r#"
name = "ordered"

[[responses]]
id = "first"
when_contains = "create model"
content = "<root/>"

[responses.usage]
prompt_tokens = 120
completion_tokens = 20

[[responses]]
id = "second"
content = "<root repaired=\"true\"/>"
"#,
        );

        let first = client
            .chat(messages("create model"), None, None)
            .await
            .expect("first response");
        let second = client
            .chat(messages("repair"), None, None)
            .await
            .expect("second response");

        assert_eq!(first.usage.prompt_tokens, 120);
        assert_eq!(first.usage.completion_tokens, 20);
        assert!(second.content.contains("repaired"));
        assert_eq!(
            client
                .calls()
                .iter()
                .map(|call| call.response_id.as_str())
                .collect::<Vec<_>>(),
            vec!["first", "second"]
        );
    }

    #[tokio::test]
    async fn exhaustion_and_prompt_mismatch_fail_loudly() {
        let client = scenario(
            r#"
name = "strict"

[[responses]]
id = "only"
when_contains = "expected"
content = "done"
"#,
        );

        let mismatch = client
            .chat(messages("wrong"), None, None)
            .await
            .unwrap_err();
        assert!(mismatch.to_string().contains("expected request containing"));
        assert!(client.calls().is_empty());

        client
            .chat(messages("expected"), None, None)
            .await
            .expect("matching response");
        let exhausted = client
            .chat(messages("expected"), None, None)
            .await
            .unwrap_err();
        assert!(exhausted.to_string().contains("exhausted"));
    }

    #[tokio::test]
    async fn configured_failure_is_injected() {
        let client = scenario(
            r#"
name = "failure"

[[responses]]
id = "503"

[responses.error]
kind = "transport"
status = 503
body = "offline"
"#,
        );

        let error = client.chat(messages("test"), None, None).await.unwrap_err();
        assert!(matches!(
            error,
            AgentError::TransportError { status: 503, .. }
        ));
    }

    #[tokio::test]
    async fn streaming_replays_reasoning_content_and_usage() {
        let client = scenario(
            r#"
name = "stream"
stream_chunk_chars = 3

[[responses]]
id = "streamed"
content = "abcdef"
reasoning_content = "plan"

[responses.usage]
prompt_tokens = 10
completion_tokens = 6
"#,
        );
        let mut receiver = client
            .chat_stream(messages("test"))
            .await
            .expect("stream receiver");
        let mut events = Vec::new();
        while let Some(event) = receiver.recv().await {
            events.push(event);
        }

        assert!(
            events
                .iter()
                .any(|event| matches!(event, StreamEvent::ReasoningToken(_)))
        );
        assert_eq!(
            events
                .iter()
                .filter(|event| matches!(event, StreamEvent::Token(_)))
                .count(),
            2
        );
        assert!(matches!(
            events.last(),
            Some(StreamEvent::Done {
                usage: Some(ChatUsage {
                    prompt_tokens: 10,
                    completion_tokens: 6,
                    ..
                }),
                ..
            })
        ));
    }
}
