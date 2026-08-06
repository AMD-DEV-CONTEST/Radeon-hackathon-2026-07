use serde::{Deserialize, Serialize};

/// Lifecycle state for a process-backed tool invocation.
/// Shared between structured pipeline and generic agent loop.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum ToolProcessStatus {
    Running,
    Succeeded,
    Failed,
}

/// A command launched by the agent as part of tool use.
/// Shared between structured pipeline and generic agent loop.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ToolProcess {
    pub id: u64,
    pub command: String,
    pub status: ToolProcessStatus,
    pub exit_code: Option<i32>,
}

/// User-visible state of a plan step.
/// Shared between structured pipeline and generic agent loop.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
pub enum PlanStepStatus {
    Pending,
    InProgress,
    WaitingUser,
    Blocked,
    Completed,
    Failed,
    Skipped,
    Cancelled,
}

/// A stable, user-visible unit in the run plan.
/// Shared between structured pipeline and generic agent loop.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PlanStep {
    pub id: String,
    pub title: String,
    pub detail: Option<String>,
    pub status: PlanStepStatus,
}

impl PlanStep {
    pub fn new(id: impl Into<String>, title: impl Into<String>) -> Self {
        Self {
            id: id.into(),
            title: title.into(),
            detail: None,
            status: PlanStepStatus::Pending,
        }
    }
}
