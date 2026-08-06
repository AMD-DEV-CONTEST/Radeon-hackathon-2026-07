use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};

use crate::event::{ContextBudget, TokenUsage, ValidationResult};
use crate::shared::{PlanStep, PlanStepStatus, ToolProcess, ToolProcessStatus};

/// Cumulative model usage for a run.
#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct TokenTotals {
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub total_tokens: u64,
    pub model_calls: u32,
}

impl TokenTotals {
    fn record(&mut self, usage: &TokenUsage) {
        self.input_tokens += u64::from(usage.prompt_tokens);
        self.output_tokens += u64::from(usage.completion_tokens);
        self.total_tokens += u64::from(usage.total_tokens);
        self.model_calls += 1;
    }
}

/// Pipeline state — must be an explicit enum, never inferred from log text.
/// State transitions are handled exclusively by the reducer.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum PipelineState {
    /// No task loaded
    Idle,
    /// Loading and validating a task package
    LoadingTask,
    /// Checking budget, permissions, workspace access
    Preflight,
    /// Waiting for user consent (e.g., external data transfer)
    AwaitingConsent { action: String },
    /// Sending generation request to model
    Generating { attempt: u8 },
    /// Running local validation (L0-L2)
    LocalValidation { attempt: u8 },
    /// Running domain validation (L3, e.g. TeaQL evaluate)
    DomainValidation { attempt: u8 },
    /// Running build validation (L4-L6, cargo check/test)
    BuildValidation { attempt: u8 },
    /// Creating a fresh repair request
    Repairing { attempt: u8 },
    /// All gates passed, writing final artifact
    Finalizing,
    /// Terminal: success
    Completed,
    /// Terminal: failure
    Failed { error: String },
    /// Terminal: user cancelled
    Cancelled,
    /// Terminal: policy prevented the action (headless mode)
    SkippedByPolicy { reason: String },
}

impl PipelineState {
    /// Whether this is a terminal state
    pub fn is_terminal(&self) -> bool {
        matches!(
            self,
            PipelineState::Completed
                | PipelineState::Failed { .. }
                | PipelineState::Cancelled
                | PipelineState::SkippedByPolicy { .. }
        )
    }

    /// Machine-comparable outcome label for suite evaluation.
    /// Avoids fragile string-matching on error messages.
    pub fn outcome_label(&self) -> &'static str {
        match self {
            PipelineState::Completed => "completed",
            PipelineState::Cancelled => "cancelled",
            PipelineState::SkippedByPolicy { .. } => "skipped",
            PipelineState::Failed { .. } => "failed",
            _ => "unknown",
        }
    }

    /// Human-readable label for TUI display
    pub fn label(&self) -> &'static str {
        match self {
            PipelineState::Idle => "Idle",
            PipelineState::LoadingTask => "Loading Task",
            PipelineState::Preflight => "Preflight",
            PipelineState::AwaitingConsent { .. } => "Awaiting Consent",
            PipelineState::Generating { .. } => "Generating",
            PipelineState::LocalValidation { .. } => "Local Validation",
            PipelineState::DomainValidation { .. } => "Domain Validation",
            PipelineState::BuildValidation { .. } => "Build Validation",
            PipelineState::Repairing { .. } => "Repairing",
            PipelineState::Finalizing => "Finalizing",
            PipelineState::Completed => "Completed",
            PipelineState::Failed { .. } => "Failed",
            PipelineState::Cancelled => "Cancelled",
            PipelineState::SkippedByPolicy { .. } => "Skipped",
        }
    }

    /// Whether the state machine is currently active (not idle or terminal)
    pub fn is_active(&self) -> bool {
        !matches!(self, PipelineState::Idle) && !self.is_terminal()
    }
}

impl std::fmt::Display for PipelineState {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.label())
    }
}

/// Timing information for each pipeline stage
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StageTiming {
    pub stage: String,
    pub started: DateTime<Utc>,
    pub completed: Option<DateTime<Utc>>,
}

impl StageTiming {
    pub fn new(stage: impl Into<String>) -> Self {
        Self {
            stage: stage.into(),
            started: Utc::now(),
            completed: None,
        }
    }

    pub fn complete(&mut self) {
        self.completed = Some(Utc::now());
    }

    pub fn elapsed_secs(&self) -> f64 {
        let end = self.completed.unwrap_or_else(Utc::now);
        (end - self.started).num_milliseconds() as f64 / 1000.0
    }
}

/// Complete run state, owned by the reducer
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunState {
    pub run_id: String,
    pub state: PipelineState,
    pub task_name: Option<String>,
    pub timings: Vec<StageTiming>,
    pub current_attempt: u8,
    pub max_repairs: u8,
    pub created_at: DateTime<Utc>,
    /// First-class plan rendered by all clients.
    #[serde(default = "default_pipeline_plan")]
    pub plan: Vec<PlanStep>,
    /// Most recent admitted context budget.
    #[serde(default)]
    pub context_budget: Option<ContextBudget>,
    /// Usage reported by the most recent model call.
    #[serde(default)]
    pub last_model_usage: Option<TokenUsage>,
    /// Cumulative usage for the complete run.
    #[serde(default)]
    pub token_totals: TokenTotals,
    /// Structured validation history, including failed repair attempts.
    #[serde(default)]
    pub validation_history: Vec<ValidationResult>,
    /// Process-backed tool invocations in launch order.
    #[serde(default)]
    pub tool_processes: Vec<ToolProcess>,
}

impl RunState {
    pub fn new(run_id: String, max_repairs: u8) -> Self {
        Self {
            run_id,
            state: PipelineState::Idle,
            task_name: None,
            timings: Vec::new(),
            current_attempt: 0,
            max_repairs,
            created_at: Utc::now(),
            plan: default_pipeline_plan(),
            context_budget: None,
            last_model_usage: None,
            token_totals: TokenTotals::default(),
            validation_history: Vec::new(),
            tool_processes: Vec::new(),
        }
    }

    pub fn start_stage(&mut self, stage: impl Into<String>) {
        // Complete the previous stage if any
        if let Some(last) = self.timings.last_mut() {
            if last.completed.is_none() {
                last.complete();
            }
        }
        self.timings.push(StageTiming::new(stage));
    }

    pub fn complete_current_stage(&mut self) {
        if let Some(last) = self.timings.last_mut() {
            last.complete();
        }
    }

    /// Mark a plan step as active and attach the current concrete action.
    pub fn activate_plan_step(&mut self, id: &str, detail: impl Into<String>) {
        for step in &mut self.plan {
            if matches!(
                step.status,
                PlanStepStatus::InProgress | PlanStepStatus::WaitingUser
            ) {
                step.status = PlanStepStatus::Pending;
            }
        }
        if let Some(step) = self.plan.iter_mut().find(|step| step.id == id) {
            step.status = PlanStepStatus::InProgress;
            step.detail = Some(detail.into());
        }
    }

    /// Mark a plan step as completed.
    pub fn complete_plan_step(&mut self, id: &str) {
        if let Some(step) = self.plan.iter_mut().find(|step| step.id == id) {
            step.status = PlanStepStatus::Completed;
            step.detail = None;
        }
    }

    /// Mark the current plan step with a terminal or blocking status.
    pub fn mark_current_plan_step(&mut self, status: PlanStepStatus, detail: impl Into<String>) {
        if let Some(step) = self.plan.iter_mut().find(|step| {
            matches!(
                step.status,
                PlanStepStatus::InProgress | PlanStepStatus::WaitingUser
            )
        }) {
            step.status = status;
            step.detail = Some(detail.into());
        }
    }

    /// Current plan step and its one-based position.
    pub fn current_plan_step(&self) -> Option<(usize, &PlanStep)> {
        self.plan
            .iter()
            .enumerate()
            .find(|(_, step)| {
                matches!(
                    step.status,
                    PlanStepStatus::InProgress
                        | PlanStepStatus::WaitingUser
                        | PlanStepStatus::Blocked
                )
            })
            .map(|(index, step)| (index + 1, step))
    }

    /// Prompt tokens reported by the latest completed model call.
    pub fn current_context_tokens(&self) -> Option<u32> {
        self.last_model_usage
            .as_ref()
            .map(|usage| usage.prompt_tokens)
    }

    /// Record one model call without conflating cumulative usage with context size.
    pub fn record_model_usage(&mut self, usage: TokenUsage) {
        self.token_totals.record(&usage);
        self.last_model_usage = Some(usage);
    }

    /// Record a process before it starts so clients can render it immediately.
    pub fn start_tool_process(&mut self, id: u64, command: String) {
        self.tool_processes.push(ToolProcess {
            id,
            command,
            status: ToolProcessStatus::Running,
            exit_code: None,
        });
    }

    /// Update a previously launched process with its terminal result.
    pub fn finish_tool_process(&mut self, id: u64, success: bool, exit_code: Option<i32>) {
        if let Some(process) = self
            .tool_processes
            .iter_mut()
            .rev()
            .find(|process| process.id == id)
        {
            process.status = if success {
                ToolProcessStatus::Succeeded
            } else {
                ToolProcessStatus::Failed
            };
            process.exit_code = exit_code;
        }
    }
}

fn default_pipeline_plan() -> Vec<PlanStep> {
    vec![
        PlanStep::new("preflight", "Inspect task and workspace"),
        PlanStep::new("generate", "Generate candidate"),
        PlanStep::new("local_validation", "Run L1–L2 validation"),
        PlanStep::new("domain_validation", "Run L3 TeaQL validation"),
        PlanStep::new("build_validation", "Generate and compile code"),
        PlanStep::new("finalize", "Save final Artifact"),
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cumulative_usage_does_not_replace_current_context() {
        let mut run = RunState::new("run-1".to_string(), 2);
        run.record_model_usage(TokenUsage {
            prompt_tokens: 12_000,
            completion_tokens: 2_000,
            total_tokens: 14_000,
        });
        run.record_model_usage(TokenUsage {
            prompt_tokens: 18_000,
            completion_tokens: 3_000,
            total_tokens: 21_000,
        });

        assert_eq!(run.current_context_tokens(), Some(18_000));
        assert_eq!(run.token_totals.input_tokens, 30_000);
        assert_eq!(run.token_totals.output_tokens, 5_000);
        assert_eq!(run.token_totals.model_calls, 2);
    }

    #[test]
    fn activating_a_step_keeps_only_one_current_step() {
        let mut run = RunState::new("run-1".to_string(), 2);
        run.activate_plan_step("preflight", "checking");
        run.complete_plan_step("preflight");
        run.activate_plan_step("generate", "generating");

        let (position, step) = run.current_plan_step().expect("current plan step");
        assert_eq!(position, 2);
        assert_eq!(step.id, "generate");
        assert_eq!(
            run.plan
                .iter()
                .filter(|step| step.status == PlanStepStatus::InProgress)
                .count(),
            1
        );
    }

    #[test]
    fn tool_process_is_updated_in_place_when_it_finishes() {
        let mut run = RunState::new("run-1".to_string(), 2);
        run.start_tool_process(7, "cargo check".to_string());
        run.finish_tool_process(7, false, Some(101));

        assert_eq!(run.tool_processes.len(), 1);
        assert_eq!(run.tool_processes[0].status, ToolProcessStatus::Failed);
        assert_eq!(run.tool_processes[0].exit_code, Some(101));
    }
}
