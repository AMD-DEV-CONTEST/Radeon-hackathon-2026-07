use crate::error::AgentError;
use crate::event::RunEvent;
use crate::shared::PlanStepStatus;
use crate::state::{PipelineState, RunState};
use tracing::{error, info, warn};

/// Side-effect commands emitted by the reducer.
/// The run controller executes these outside the reducer.
#[derive(Debug, Clone)]
pub enum SideEffect {
    /// Load and parse a task package
    LoadTask { path: std::path::PathBuf },
    /// Run preflight checks (budget, permissions, workspace)
    RunPreflight,
    /// Show consent dialog for external operation
    RequestConsent {
        action: String,
        domain: String,
        files: Vec<String>,
        bytes: u64,
    },
    /// Send a generation request to the model
    Generate { attempt: u8 },
    /// Run local validation (L0-L2) on the candidate
    RunLocalValidation { attempt: u8 },
    /// Run domain validation (L3, e.g. TeaQL evaluate)
    RunDomainValidation { attempt: u8 },
    /// Run build validation (L4-L6, cargo check/test)
    RunBuildValidation { attempt: u8 },
    /// Create and send a repair request
    Repair { attempt: u8 },
    /// Write final artifact to disk
    WriteFinalArtifact,
    /// Record failure and clean up
    RecordFailure { error: String },
    /// No side effect
    None,
}

/// Pure state transition function.
/// Given the current RunState and an event, produce a new state and side effect.
pub fn reduce(state: &mut RunState, event: RunEvent) -> SideEffect {
    match (&state.state, event) {
        // ── Idle → LoadingTask ──
        (PipelineState::Idle, RunEvent::TaskLoaded(task)) => {
            info!(task = %task.name, "Task loaded");
            state.task_name = Some(task.name.clone());
            state.state = PipelineState::LoadingTask;
            state.start_stage("loading_task");
            // Task is loaded, move to preflight
            state.state = PipelineState::Preflight;
            state.start_stage("preflight");
            state.activate_plan_step(
                "preflight",
                "Check context budget and workspace permissions",
            );
            SideEffect::RunPreflight
        }

        (PipelineState::Idle, RunEvent::TaskLoadFailed(reason)) => {
            error!(%reason, "Task load failed");
            state.state = PipelineState::Failed {
                error: reason.clone(),
            };
            state.activate_plan_step("preflight", "Task loading failed");
            state.mark_current_plan_step(PlanStepStatus::Failed, reason.clone());
            SideEffect::RecordFailure { error: reason }
        }

        // ── Preflight → Generating or Failed ──
        (PipelineState::Preflight, RunEvent::PreflightPassed(budget)) => {
            info!(
                estimated = budget.estimated_prompt,
                limit = budget.prompt_limit,
                "Preflight passed — budget admits"
            );
            state.context_budget = Some(budget);
            state.complete_current_stage();
            state.complete_plan_step("preflight");
            state.current_attempt = 1;
            state.state = PipelineState::Generating { attempt: 1 };
            state.start_stage("generate_1");
            state.activate_plan_step("generate", "Ask the local model to generate a candidate");
            SideEffect::Generate { attempt: 1 }
        }

        (PipelineState::Preflight, RunEvent::PreflightFailed(reason)) => {
            warn!(%reason, "Preflight failed");
            state.complete_current_stage();
            state.mark_current_plan_step(PlanStepStatus::Failed, reason.clone());
            state.state = PipelineState::Failed {
                error: reason.clone(),
            };
            SideEffect::RecordFailure { error: reason }
        }

        // ── Any active state → AwaitingConsent ──
        (current, RunEvent::ConsentRequired { action }) if current.is_active() => {
            info!(%action, "Waiting for interactive user consent");
            state.mark_current_plan_step(PlanStepStatus::WaitingUser, action.clone());
            state.state = PipelineState::AwaitingConsent { action };
            SideEffect::None
        }

        // ── AwaitingConsent ──
        (PipelineState::AwaitingConsent { .. }, RunEvent::ConsentGranted(_)) => {
            info!("Consent granted, proceeding to preflight");
            state.state = PipelineState::Preflight;
            state.activate_plan_step("preflight", "Consent granted; inspect the task again");
            SideEffect::RunPreflight
        }

        (PipelineState::AwaitingConsent { .. }, RunEvent::ConsentDenied(reason)) => {
            info!(%reason, "Consent denied");
            state.mark_current_plan_step(PlanStepStatus::Cancelled, reason);
            state.state = PipelineState::Cancelled;
            SideEffect::None
        }

        // ── Generating → LocalValidation or Failed ──
        (PipelineState::Generating { attempt }, RunEvent::ModelCompleted(result)) => {
            let attempt = *attempt;
            info!(
                attempt,
                finish_reason = %result.finish_reason,
                prompt_tokens = result.usage.prompt_tokens,
                completion_tokens = result.usage.completion_tokens,
                elapsed = result.elapsed_secs,
                "Model completed"
            );
            state.record_model_usage(result.usage.clone());
            state.complete_current_stage();
            state.complete_plan_step("generate");
            state.state = PipelineState::LocalValidation { attempt };
            state.start_stage(format!("local_validation_{attempt}"));
            state.activate_plan_step("local_validation", "Parse and inspect the candidate");
            SideEffect::RunLocalValidation { attempt }
        }

        (PipelineState::Generating { .. }, RunEvent::ModelFailed(err)) => {
            error!(%err, "Model failed");
            state.complete_current_stage();
            state.mark_current_plan_step(PlanStepStatus::Failed, err.to_string());
            // HTTP 4xx: do NOT retry
            if let AgentError::TransportError { status, .. } = &err {
                if *status >= 400 && *status < 500 {
                    state.state = PipelineState::Failed {
                        error: format!("HTTP {status} — not retryable"),
                    };
                    return SideEffect::RecordFailure {
                        error: err.to_string(),
                    };
                }
            }
            state.state = PipelineState::Failed {
                error: err.to_string(),
            };
            SideEffect::RecordFailure {
                error: err.to_string(),
            }
        }

        // ── Streaming token (display-only, no state change) ──
        (_, RunEvent::ModelToken(_)) => SideEffect::None,

        // ── Auxiliary model call usage ──
        (current, RunEvent::ModelUsageRecorded(usage)) if current.is_active() => {
            state.record_model_usage(usage);
            SideEffect::None
        }

        // ── Process-backed tool lifecycle ──
        (_, RunEvent::ToolProcessStarted { id, command }) => {
            state.start_tool_process(id, command);
            SideEffect::None
        }

        (
            _,
            RunEvent::ToolProcessFinished {
                id,
                success,
                exit_code,
            },
        ) => {
            state.finish_tool_process(id, success, exit_code);
            SideEffect::None
        }

        // ── LocalValidation → DomainValidation or Repairing or Failed ──
        (PipelineState::LocalValidation { attempt }, RunEvent::ValidationCompleted(result)) => {
            let attempt = *attempt;
            state.validation_history.push(result.clone());
            if result.passed {
                info!("Local validation passed, proceeding to domain validation");
                state.complete_current_stage();
                state.complete_plan_step("local_validation");
                state.state = PipelineState::DomainValidation { attempt };
                state.start_stage(format!("domain_validation_{attempt}"));
                state.activate_plan_step(
                    "domain_validation",
                    "Run TeaQL domain semantic validation",
                );
                SideEffect::RunDomainValidation { attempt }
            } else if attempt <= state.max_repairs {
                warn!(
                    errors = result.error_count,
                    attempt, "Local validation failed — scheduling repair"
                );
                state.complete_current_stage();
                let next = attempt + 1;
                state.state = PipelineState::Repairing { attempt: next };
                state.activate_plan_step(
                    "generate",
                    format!("L1–L2 validation failed; prepare automatic repair {next}"),
                );
                SideEffect::Repair { attempt: next }
            } else {
                error!("Local validation failed and repair limit reached");
                state.complete_current_stage();
                state.state = PipelineState::Failed {
                    error: format!(
                        "Local validation: {} errors, repair limit reached",
                        result.error_count
                    ),
                };
                state.mark_current_plan_step(
                    PlanStepStatus::Failed,
                    format!("{} errors; repair limit reached", result.error_count),
                );
                SideEffect::RecordFailure {
                    error: format!(
                        "Validation L{}: {} errors",
                        result.level, result.error_count
                    ),
                }
            }
        }

        // ── DomainValidation → BuildValidation or Repairing or Failed ──
        (PipelineState::DomainValidation { attempt }, RunEvent::ValidationCompleted(result)) => {
            let attempt = *attempt;
            state.validation_history.push(result.clone());
            if result.passed {
                info!(
                    errors = result.error_count,
                    warnings = result.warning_count,
                    "Domain validation passed"
                );
                state.complete_current_stage();
                state.complete_plan_step("domain_validation");
                state.state = PipelineState::BuildValidation { attempt };
                state.start_stage(format!("build_validation_{attempt}"));
                state.activate_plan_step(
                    "build_validation",
                    "Generate code and run cargo check/test",
                );
                SideEffect::RunBuildValidation { attempt }
            } else if result.error_count > 0 && attempt <= state.max_repairs {
                warn!(
                    errors = result.error_count,
                    "Domain validation failed — scheduling repair"
                );
                state.complete_current_stage();
                let next = attempt + 1;
                state.state = PipelineState::Repairing { attempt: next };
                state.activate_plan_step(
                    "generate",
                    format!("L3 validation failed; prepare automatic repair {next}"),
                );
                SideEffect::Repair { attempt: next }
            } else {
                error!("Domain validation failed, repair limit reached");
                state.complete_current_stage();
                state.state = PipelineState::Failed {
                    error: format!("Domain validation: {} errors", result.error_count),
                };
                state.mark_current_plan_step(
                    PlanStepStatus::Failed,
                    format!("{} errors; repair limit reached", result.error_count),
                );
                SideEffect::RecordFailure {
                    error: format!("TeaQL: {} errors", result.error_count),
                }
            }
        }

        // ── BuildValidation → Finalizing or Repairing or Failed ──
        (PipelineState::BuildValidation { attempt }, RunEvent::ValidationCompleted(result)) => {
            let attempt = *attempt;
            state.validation_history.push(result.clone());
            if result.passed {
                info!("Build validation passed — finalizing");
                state.complete_current_stage();
                state.complete_plan_step("build_validation");
                state.state = PipelineState::Finalizing;
                state.start_stage("finalizing");
                state.activate_plan_step("finalize", "Write the final result and run artifact");
                SideEffect::WriteFinalArtifact
            } else if attempt <= state.max_repairs {
                warn!("Build validation failed — scheduling repair");
                state.complete_current_stage();
                let next = attempt + 1;
                state.state = PipelineState::Repairing { attempt: next };
                state.activate_plan_step(
                    "generate",
                    format!("Build validation failed; prepare automatic repair {next}"),
                );
                SideEffect::Repair { attempt: next }
            } else {
                error!("Build failed and repair limit reached");
                state.complete_current_stage();
                state.state = PipelineState::Failed {
                    error: format!("Build: {} errors, repair limit reached", result.error_count),
                };
                state.mark_current_plan_step(
                    PlanStepStatus::Failed,
                    format!("{} errors; repair limit reached", result.error_count),
                );
                SideEffect::RecordFailure {
                    error: format!("Build L{}: {} errors", result.level, result.error_count),
                }
            }
        }

        // ── Repairing → Generating ──
        (PipelineState::Repairing { attempt }, RunEvent::RepairScheduled { attempt: _ }) => {
            let attempt = *attempt;
            info!(attempt, "Repair request prepared, starting generation");
            state.current_attempt = attempt;
            state.state = PipelineState::Generating { attempt };
            state.start_stage(format!("generate_{attempt}"));
            state.activate_plan_step("generate", format!("Run automatic repair {attempt}"));
            SideEffect::Generate { attempt }
        }

        // ── Finalizing → Completed ──
        (PipelineState::Finalizing, RunEvent::FinalArtifactWritten(path)) => {
            info!(path = %path.display(), "Final artifact written");
            state.complete_current_stage();
            state.complete_plan_step("finalize");
            state.state = PipelineState::Completed;
            SideEffect::None
        }

        // ── Cancel from any active state ──
        (s, RunEvent::CancelRequested) if s.is_active() => {
            warn!(state = %state.state, "Cancel requested");
            state.complete_current_stage();
            state.mark_current_plan_step(PlanStepStatus::Cancelled, "Task cancelled by user");
            state.state = PipelineState::Cancelled;
            SideEffect::None
        }

        // ── Infrastructure failure from any active state ──
        (s, RunEvent::Failed(err)) if s.is_active() => {
            error!(%err, "Infrastructure failure");
            state.complete_current_stage();
            state.mark_current_plan_step(PlanStepStatus::Failed, err.to_string());
            state.state = PipelineState::Failed {
                error: err.to_string(),
            };
            SideEffect::RecordFailure {
                error: err.to_string(),
            }
        }

        // ── Unhandled transitions ──
        (current_state, event) => {
            warn!(
                state = %current_state,
                event = ?std::mem::discriminant(&event),
                "Unhandled event in current state"
            );
            SideEffect::None
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::event::{ContextBudget, ModelResult, TokenUsage, ValidationResult};

    fn new_run() -> RunState {
        RunState::new("test-run-001".to_string(), 1)
    }

    #[test]
    fn test_happy_path() {
        let mut run = new_run();
        assert_eq!(run.state, PipelineState::Idle);

        // Load task → Preflight
        let task = crate::event::TaskPackage {
            name: "test-task".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        let effect = reduce(&mut run, RunEvent::TaskLoaded(task));
        assert!(matches!(effect, SideEffect::RunPreflight));
        assert!(matches!(run.state, PipelineState::Preflight));

        // Preflight → Generating
        let budget = ContextBudget {
            model_context: 65536,
            prompt_limit: 48000,
            completion_limit: 4096,
            safety_reserve: 8192,
            estimated_prompt: 3000,
        };
        let effect = reduce(&mut run, RunEvent::PreflightPassed(budget));
        assert!(matches!(effect, SideEffect::Generate { attempt: 1 }));
        assert_eq!(
            run.current_plan_step().map(|(_, step)| step.id.as_str()),
            Some("generate")
        );

        // Generating → LocalValidation
        let model_result = ModelResult {
            content: "<root>...</root>".to_string(),
            reasoning_content: None,
            finish_reason: "stop".to_string(),
            tool_calls: None,
            usage: TokenUsage {
                prompt_tokens: 3000,
                completion_tokens: 2000,
                total_tokens: 5000,
            },
            elapsed_secs: 10.5,
            http_status: 200,
        };
        let effect = reduce(&mut run, RunEvent::ModelCompleted(model_result));
        assert!(matches!(
            effect,
            SideEffect::RunLocalValidation { attempt: 1 }
        ));
        assert_eq!(run.token_totals.input_tokens, 3000);
        assert_eq!(run.token_totals.output_tokens, 2000);

        // LocalValidation → DomainValidation
        let val_result = ValidationResult {
            level: 1,
            level_name: "parse".to_string(),
            passed: true,
            error_count: 0,
            warning_count: 0,
            suggestion_count: 0,
            actionable_errors: vec![],
            structured_errors: vec![],
            diagnostic: String::new(),
            elapsed_secs: 0.1,
        };
        let effect = reduce(&mut run, RunEvent::ValidationCompleted(val_result));
        assert!(matches!(
            effect,
            SideEffect::RunDomainValidation { attempt: 1 }
        ));

        // DomainValidation → BuildValidation
        let val_result = ValidationResult {
            level: 3,
            level_name: "domain".to_string(),
            passed: true,
            error_count: 0,
            warning_count: 5,
            suggestion_count: 2,
            actionable_errors: vec![],
            structured_errors: vec![],
            diagnostic: String::new(),
            elapsed_secs: 1.2,
        };
        let effect = reduce(&mut run, RunEvent::ValidationCompleted(val_result));
        assert!(matches!(
            effect,
            SideEffect::RunBuildValidation { attempt: 1 }
        ));

        // BuildValidation → Finalizing → Completed
        let val_result = ValidationResult {
            level: 5,
            level_name: "build".to_string(),
            passed: true,
            error_count: 0,
            warning_count: 0,
            suggestion_count: 0,
            actionable_errors: vec![],
            structured_errors: vec![],
            diagnostic: String::new(),
            elapsed_secs: 5.0,
        };
        let effect = reduce(&mut run, RunEvent::ValidationCompleted(val_result));
        assert!(matches!(effect, SideEffect::WriteFinalArtifact));

        let effect = reduce(&mut run, RunEvent::FinalArtifactWritten("final.xml".into()));
        assert!(matches!(effect, SideEffect::None));
        assert_eq!(run.state, PipelineState::Completed);
        assert!(
            run.plan
                .iter()
                .all(|step| step.status == PlanStepStatus::Completed)
        );
        assert_eq!(run.validation_history.len(), 3);
    }

    #[test]
    fn test_repair_flow() {
        let mut run = new_run();

        // Fast-forward to LocalValidation
        let task = crate::event::TaskPackage {
            name: "test".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        reduce(&mut run, RunEvent::TaskLoaded(task));
        let budget = ContextBudget {
            model_context: 65536,
            prompt_limit: 48000,
            completion_limit: 4096,
            safety_reserve: 8192,
            estimated_prompt: 3000,
        };
        reduce(&mut run, RunEvent::PreflightPassed(budget));
        let model_result = ModelResult {
            content: "bad xml".to_string(),
            reasoning_content: None,
            finish_reason: "stop".to_string(),
            tool_calls: None,
            usage: TokenUsage {
                prompt_tokens: 3000,
                completion_tokens: 500,
                total_tokens: 3500,
            },
            elapsed_secs: 5.0,
            http_status: 200,
        };
        reduce(&mut run, RunEvent::ModelCompleted(model_result));

        // LocalValidation fails → Repairing
        let val_result = ValidationResult {
            level: 1,
            level_name: "parse".to_string(),
            passed: false,
            error_count: 3,
            warning_count: 0,
            suggestion_count: 0,
            actionable_errors: vec!["XML parse error".to_string()],
            structured_errors: vec![],
            diagnostic: "line 1: unclosed tag".to_string(),
            elapsed_secs: 0.01,
        };
        let effect = reduce(&mut run, RunEvent::ValidationCompleted(val_result));
        assert!(matches!(effect, SideEffect::Repair { attempt: 2 }));
        assert!(matches!(run.state, PipelineState::Repairing { attempt: 2 }));
    }

    #[test]
    fn test_http_4xx_no_retry() {
        let mut run = new_run();
        let task = crate::event::TaskPackage {
            name: "test".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        reduce(&mut run, RunEvent::TaskLoaded(task));
        let budget = ContextBudget {
            model_context: 65536,
            prompt_limit: 48000,
            completion_limit: 4096,
            safety_reserve: 8192,
            estimated_prompt: 57000,
        };
        // Even if preflight passes (shouldn't in real code), simulate 400
        reduce(&mut run, RunEvent::PreflightPassed(budget));

        let err = AgentError::TransportError {
            status: 400,
            body: "context_length_exceeded".to_string(),
        };
        let effect = reduce(&mut run, RunEvent::ModelFailed(err));
        assert!(matches!(effect, SideEffect::RecordFailure { .. }));
        assert!(matches!(run.state, PipelineState::Failed { .. }));
    }

    #[test]
    fn test_cancel() {
        let mut run = new_run();
        let task = crate::event::TaskPackage {
            name: "test".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        reduce(&mut run, RunEvent::TaskLoaded(task));
        let budget = ContextBudget {
            model_context: 65536,
            prompt_limit: 48000,
            completion_limit: 4096,
            safety_reserve: 8192,
            estimated_prompt: 3000,
        };
        reduce(&mut run, RunEvent::PreflightPassed(budget));

        // Cancel while generating
        let effect = reduce(&mut run, RunEvent::CancelRequested);
        assert!(matches!(effect, SideEffect::None));
        assert_eq!(run.state, PipelineState::Cancelled);
    }

    #[test]
    fn test_interactive_consent_waits_for_user() {
        let mut run = new_run();
        let task = crate::event::TaskPackage {
            name: "test".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        reduce(&mut run, RunEvent::TaskLoaded(task));

        let effect = reduce(
            &mut run,
            RunEvent::ConsentRequired {
                action: "Allow local code generation?".to_string(),
            },
        );

        assert!(matches!(effect, SideEffect::None));
        assert!(matches!(run.state, PipelineState::AwaitingConsent { .. }));
        assert_eq!(
            run.current_plan_step().map(|(_, step)| step.status),
            Some(PlanStepStatus::WaitingUser)
        );
    }

    #[test]
    fn test_auxiliary_usage_updates_tokens_without_advancing_state() {
        let mut run = new_run();
        let task = crate::event::TaskPackage {
            name: "test".to_string(),
            task_file: "task.md".into(),
            files: vec![],
            acceptance_spec: None,
        };
        reduce(&mut run, RunEvent::TaskLoaded(task));
        let state_before = run.state.clone();

        let effect = reduce(
            &mut run,
            RunEvent::ModelUsageRecorded(TokenUsage {
                prompt_tokens: 8_000,
                completion_tokens: 600,
                total_tokens: 8_600,
            }),
        );

        assert!(matches!(effect, SideEffect::None));
        assert_eq!(run.state, state_before);
        assert_eq!(run.current_context_tokens(), Some(8_000));
        assert_eq!(run.token_totals.input_tokens, 8_000);
        assert_eq!(run.token_totals.output_tokens, 600);
    }

    #[test]
    fn test_tool_process_events_do_not_advance_pipeline() {
        let mut run = new_run();
        let state_before = run.state.clone();

        reduce(
            &mut run,
            RunEvent::ToolProcessStarted {
                id: 1,
                command: "cargo check".to_string(),
            },
        );
        reduce(
            &mut run,
            RunEvent::ToolProcessFinished {
                id: 1,
                success: true,
                exit_code: Some(0),
            },
        );

        assert_eq!(run.state, state_before);
        assert_eq!(run.tool_processes.len(), 1);
        assert_eq!(
            run.tool_processes[0].status,
            crate::shared::ToolProcessStatus::Succeeded
        );
    }
}
