use serde::{Deserialize, Serialize};

use crate::shared::{PlanStep, PlanStepStatus, ToolProcess};

/// State for the generic agent loop
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum GenericPipelineState {
    /// No task loaded
    Idle,
    /// Loading task package
    LoadingContext,
    /// Preflight budget and permissions check
    Preflight,
    /// Agent is waiting for user consent
    AwaitingConsent { action: String },
    /// Agent is thinking / generating response or tool calls
    Reasoning,
    /// Agent is executing a requested tool
    ExecutingTool { tool_call: String },
    /// Finalizing the run (saving state/artifacts)
    Finalizing,
    /// Terminal: success
    Completed,
    /// Terminal: failure
    Failed { error: String },
    /// Terminal: user cancelled
    Cancelled,
}

impl GenericPipelineState {
    pub fn is_active(&self) -> bool {
        !matches!(
            self,
            GenericPipelineState::Idle
                | GenericPipelineState::Completed
                | GenericPipelineState::Failed { .. }
                | GenericPipelineState::Cancelled
        )
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GenericRunState {
    pub run_id: String,
    pub state: GenericPipelineState,
    pub steps: Vec<PlanStep>,
    pub current_step: Option<String>,
    pub active_tools: Vec<ToolProcess>,
    pub tool_id_counter: u64,
}

impl GenericRunState {
    pub fn new(run_id: String) -> Self {
        Self {
            run_id,
            state: GenericPipelineState::Idle,
            steps: vec![],
            current_step: None,
            active_tools: vec![],
            tool_id_counter: 0,
        }
    }

    pub fn is_active(&self) -> bool {
        self.state.is_active()
    }

    pub fn mark_step(&mut self, status: PlanStepStatus) {
        if let Some(id) = &self.current_step {
            if let Some(step) = self.steps.iter_mut().find(|s| s.id == *id) {
                step.status = status;
            }
        }
    }
}
