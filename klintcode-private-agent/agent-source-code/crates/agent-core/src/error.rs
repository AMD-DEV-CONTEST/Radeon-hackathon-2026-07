use std::path::PathBuf;
use thiserror::Error;

/// Agent-level errors with structured classification
#[derive(Debug, Error)]
pub enum AgentError {
    #[error("Task package invalid: {reason}")]
    TaskInvalid { reason: String },

    #[error("Context budget exceeded: estimated {estimated} > limit {limit}")]
    BudgetExceeded { estimated: u32, limit: u32 },

    #[error("Model transport error: HTTP {status}: {body}")]
    TransportError { status: u16, body: String },

    #[error("Model returned non-stop finish_reason: {reason}")]
    IncompleteGeneration { reason: String },

    #[error("Validation failed at level {level}: {summary}")]
    ValidationFailed { level: u8, summary: String },

    #[error("Repair limit reached: {attempts}/{max_repairs}")]
    RepairLimitReached { attempts: u8, max_repairs: u8 },

    #[error("Infrastructure error (not model-repairable): {detail}")]
    InfrastructureError { detail: String },

    #[error("Operation cancelled by user")]
    Cancelled,

    #[error("Consent required for: {action}")]
    ConsentRequired { action: String },

    #[error("Policy denied: {action} on {target}")]
    PolicyDenied { action: String, target: String },

    #[error("Workspace access denied: {path}")]
    WorkspaceAccessDenied { path: PathBuf },

    #[error("Timeout after {seconds}s in state {state}")]
    Timeout { seconds: u64, state: String },

    #[error("Loop detected: {pattern} after {iterations} iterations")]
    LoopDetected { pattern: String, iterations: usize },

    #[error("{0}")]
    Other(#[from] anyhow::Error),
}

/// Whether an error is retryable via model repair
impl AgentError {
    pub fn is_model_repairable(&self) -> bool {
        matches!(
            self,
            AgentError::ValidationFailed { .. } | AgentError::IncompleteGeneration { .. }
        )
    }

    pub fn is_infrastructure(&self) -> bool {
        matches!(
            self,
            AgentError::InfrastructureError { .. } | AgentError::Timeout { .. }
        )
    }

    pub fn is_loop(&self) -> bool {
        matches!(self, AgentError::LoopDetected { .. })
    }
}
