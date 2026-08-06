use crate::error::AgentError;
use crate::event::{ContextBudget, ExportConsent, ModelResult, TaskPackage};

#[derive(Debug)]
pub enum GenericRunEvent {
    /// Context (prompts/skills) loaded successfully
    ContextLoaded(TaskPackage),
    ContextLoadFailed(String),
    PreflightPassed(ContextBudget),
    PreflightFailed(String),

    ConsentRequired {
        action: String,
    },
    ConsentGranted(ExportConsent),
    ConsentDenied(String),

    /// Model generating tokens (streaming)
    ModelToken(String),
    ModelThinking(String),
    /// Model finished reasoning phase
    ModelCompleted(ModelResult),
    ModelFailed(AgentError),

    /// Model emitted a tool execution block
    ToolCallRequested {
        command: String,
    },
    ToolExecutionStarted {
        id: u64,
        command: String,
    },
    /// Tool finished execution, output ready for the next reasoning loop
    ToolExecutionFinished {
        id: u64,
        success: bool,
        exit_code: Option<i32>,
        output: String,
    },

    /// Model indicated task completion
    TaskCompleted {
        summary: String,
    },
    /// Final artifact has been written to disk
    ArtifactWritten,

    CancelRequested,
    Failed(AgentError),
}
