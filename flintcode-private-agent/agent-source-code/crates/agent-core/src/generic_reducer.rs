use crate::generic_event::GenericRunEvent;
use crate::generic_state::{GenericPipelineState, GenericRunState};
use crate::shared::{ToolProcess, ToolProcessStatus};
use tracing::{error, info, warn};

#[derive(Debug, Clone)]
pub enum GenericSideEffect {
    RunPreflight,
    RequestConsent {
        action: String,
        domain: String,
        files: Vec<String>,
        bytes: u64,
    },
    /// Ask model to think and optionally emit tool calls
    Reason,
    /// Execute the requested tool
    ExecuteTool {
        command: String,
    },
    WriteFinalArtifact,
    RecordFailure {
        error: String,
    },
    None,
}

pub fn reduce(state: &mut GenericRunState, event: GenericRunEvent) -> GenericSideEffect {
    match (&state.state, event) {
        (GenericPipelineState::Idle, GenericRunEvent::ContextLoaded(task)) => {
            info!(task = %task.name, "Context loaded");
            state.state = GenericPipelineState::Preflight;
            GenericSideEffect::RunPreflight
        }
        (GenericPipelineState::Idle, GenericRunEvent::ContextLoadFailed(reason)) => {
            error!(%reason, "Context load failed");
            state.state = GenericPipelineState::Failed {
                error: reason.clone(),
            };
            GenericSideEffect::RecordFailure { error: reason }
        }
        (GenericPipelineState::Preflight, GenericRunEvent::PreflightPassed(_budget)) => {
            info!("Preflight passed, starting reasoning loop");
            state.state = GenericPipelineState::Reasoning;
            GenericSideEffect::Reason
        }
        (GenericPipelineState::Preflight, GenericRunEvent::PreflightFailed(reason)) => {
            warn!(%reason, "Preflight failed");
            state.state = GenericPipelineState::Failed {
                error: reason.clone(),
            };
            GenericSideEffect::RecordFailure { error: reason }
        }
        (GenericPipelineState::Reasoning, GenericRunEvent::ModelCompleted(_result)) => {
            // The executor parses the model's output and emits ToolCallRequested or TaskCompleted.
            GenericSideEffect::None
        }
        (GenericPipelineState::Reasoning, GenericRunEvent::ModelFailed(err)) => {
            error!(%err, "Model failed during reasoning");
            state.state = GenericPipelineState::Failed {
                error: err.to_string(),
            };
            GenericSideEffect::RecordFailure {
                error: err.to_string(),
            }
        }
        (GenericPipelineState::Reasoning, GenericRunEvent::ToolCallRequested { command }) => {
            info!(%command, "Model requested tool call");
            state.tool_id_counter += 1;
            let tool_id = state.tool_id_counter;
            state.active_tools.push(ToolProcess {
                id: tool_id,
                command: command.clone(),
                status: ToolProcessStatus::Running,
                exit_code: None,
            });
            state.state = GenericPipelineState::ExecutingTool {
                tool_call: command.clone(),
            };
            GenericSideEffect::ExecuteTool { command }
        }
        (GenericPipelineState::Reasoning, GenericRunEvent::TaskCompleted { summary: _ }) => {
            info!("Model completed the task");
            state.state = GenericPipelineState::Finalizing;
            GenericSideEffect::WriteFinalArtifact
        }
        (
            GenericPipelineState::ExecutingTool { .. },
            GenericRunEvent::ToolExecutionFinished {
                success,
                output: _,
                id: _,
                exit_code,
            },
        ) => {
            info!(success, "Tool execution finished");
            // Update the tool process record
            if let Some(tool) = state
                .active_tools
                .iter_mut()
                .rev()
                .find(|t| matches!(t.status, ToolProcessStatus::Running))
            {
                tool.status = if success {
                    ToolProcessStatus::Succeeded
                } else {
                    ToolProcessStatus::Failed
                };
                tool.exit_code = exit_code;
            }
            state.state = GenericPipelineState::Reasoning;
            GenericSideEffect::Reason
        }
        (GenericPipelineState::Finalizing, GenericRunEvent::ArtifactWritten) => {
            info!("Artifact written, run completed");
            state.state = GenericPipelineState::Completed;
            GenericSideEffect::None
        }
        (current, GenericRunEvent::Failed(err)) if current.is_active() => {
            error!(%err, "Pipeline failed");
            state.state = GenericPipelineState::Failed {
                error: err.to_string(),
            };
            GenericSideEffect::RecordFailure {
                error: err.to_string(),
            }
        }
        (current, GenericRunEvent::CancelRequested) if current.is_active() => {
            warn!("Run cancelled by user");
            state.state = GenericPipelineState::Cancelled;
            GenericSideEffect::None
        }
        _ => GenericSideEffect::None,
    }
}
