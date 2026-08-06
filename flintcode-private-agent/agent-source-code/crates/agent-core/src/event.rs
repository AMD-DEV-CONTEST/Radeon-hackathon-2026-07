use crate::error::AgentError;
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

/// Token usage from a model response
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenUsage {
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub total_tokens: u32,
}

/// Context budget calculated during preflight
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextBudget {
    pub model_context: u32,
    pub prompt_limit: u32,
    pub completion_limit: u32,
    pub safety_reserve: u32,
    pub estimated_prompt: u32,
}

impl ContextBudget {
    /// Whether the estimated prompt fits within budget
    pub fn admits(&self) -> bool {
        self.estimated_prompt <= self.prompt_limit
            && self.estimated_prompt + self.completion_limit + self.safety_reserve
                <= self.model_context
    }

    /// How many tokens are remaining for prompt content
    pub fn remaining_prompt_tokens(&self) -> u32 {
        self.prompt_limit.saturating_sub(self.estimated_prompt)
    }
}

/// Loaded task package metadata
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TaskPackage {
    pub name: String,
    pub task_file: PathBuf,
    pub files: Vec<PathBuf>,
    pub acceptance_spec: Option<serde_json::Value>,
}

/// Generic Tool Call structure emitted by models
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelToolCall {
    pub id: String,
    pub name: String,
    pub arguments: String, // JSON arguments
}

/// Result from model inference
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelResult {
    pub content: String,
    pub reasoning_content: Option<String>,
    pub tool_calls: Option<Vec<ModelToolCall>>,
    pub finish_reason: String,
    pub usage: TokenUsage,
    pub elapsed_secs: f64,
    pub http_status: u16,
}

/// Severity level for a compiler diagnostic.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub enum ErrorSeverity {
    Error,
    Warning,
    Note,
}

/// A single structured compiler diagnostic.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CompilerError {
    pub file: Option<String>,
    pub line: Option<u32>,
    pub column: Option<u32>,
    pub code: Option<String>, // e.g. "E0308"
    pub message: String,
    pub severity: ErrorSeverity,
}

/// Result from a validation gate
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationResult {
    /// Validation level (0-6)
    pub level: u8,
    pub level_name: String,
    pub passed: bool,
    pub error_count: u32,
    pub warning_count: u32,
    pub suggestion_count: u32,
    /// Actionable errors for repair diagnostic
    pub actionable_errors: Vec<String>,
    /// Structured compiler errors parsed from `--message-format=json`
    #[serde(default)]
    pub structured_errors: Vec<CompilerError>,
    /// Full diagnostic output (may be truncated)
    pub diagnostic: String,
    pub elapsed_secs: f64,
}

/// Export consent record
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExportConsent {
    pub domain: String,
    pub files: Vec<String>,
    pub total_bytes: u64,
    pub purpose: String,
    pub approved: bool,
    pub approved_by: Option<String>,
}

/// Events that drive the pipeline state machine.
/// TUI and headless runner produce these; the reducer consumes them.
#[derive(Debug)]
pub enum RunEvent {
    /// A task package was loaded and parsed
    TaskLoaded(TaskPackage),
    /// Task loading failed
    TaskLoadFailed(String),
    /// Preflight checks passed, budget is safe
    PreflightPassed(ContextBudget),
    /// Preflight checks failed
    PreflightFailed(String),
    /// An interactive client must ask the user before continuing.
    ConsentRequired { action: String },
    /// User granted consent for external operation
    ConsentGranted(ExportConsent),
    /// User denied consent
    ConsentDenied(String),
    /// Model generation request started
    ModelStarted { attempt: u8 },
    /// Incremental token from a streaming generation request (display-only).
    ModelToken(String),
    /// Model generation completed successfully
    ModelCompleted(ModelResult),
    /// Usage from an auxiliary model call that does not advance the pipeline.
    ModelUsageRecorded(TokenUsage),
    /// Model generation failed (HTTP error, timeout, etc.)
    ModelFailed(AgentError),
    /// A process-backed tool command is about to be launched.
    ToolProcessStarted { id: u64, command: String },
    /// A process-backed tool command exited or failed to launch.
    ToolProcessFinished {
        id: u64,
        success: bool,
        exit_code: Option<i32>,
    },
    /// Validation gate completed
    ValidationCompleted(ValidationResult),
    /// Repair cycle scheduled
    RepairScheduled { attempt: u8 },
    /// Final artifact written to disk
    FinalArtifactWritten(PathBuf),
    /// User requested cancellation
    CancelRequested,
    /// Unrecoverable error
    Failed(AgentError),
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_respects_the_explicit_prompt_limit() {
        let budget = ContextBudget {
            model_context: 65_536,
            prompt_limit: 48_000,
            completion_limit: 4_096,
            safety_reserve: 8_192,
            estimated_prompt: 50_000,
        };

        assert!(!budget.admits());
        assert_eq!(budget.remaining_prompt_tokens(), 0);
    }
}
