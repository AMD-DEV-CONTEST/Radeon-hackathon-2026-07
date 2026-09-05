use anyhow::Result;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use std::path::Path;
use tokio::sync::mpsc;
use tracing::info;

use crate::executor::PipelineExecutor;
use agent_core::reducer::SideEffect;
use agent_core::run_controller::RunController;
use agent_core::state::PipelineState;
use model_vllm::profile::ModelProfile;

/// Evaluation suite plan loaded from TOML
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SuitePlan {
    pub suite: SuiteMetadata,
    pub cases: Vec<TestCase>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SuiteMetadata {
    pub name: String,
    pub description: String,
    #[serde(default = "default_version")]
    pub version: String,
}

fn default_version() -> String {
    "1.0".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TestCase {
    pub name: String,
    pub task: String, // relative path to task package dir
    pub workflow: String,
    #[serde(default)]
    pub build_target: Option<String>, // e.g. "rust-lib-core"
    #[serde(default = "default_expect")]
    pub expect: String, // "completed", "preflight_rejected", "failed"
    #[serde(default = "default_timeout")]
    pub timeout_secs: u64,
    #[serde(default)]
    pub patches: Option<std::collections::HashMap<String, String>>,
}

fn default_expect() -> String {
    "completed".to_string()
}
fn default_timeout() -> u64 {
    600
}

/// Result of running a single test case
#[derive(Debug, Clone, Serialize)]
pub struct CaseResult {
    pub name: String,
    pub expected: String,
    pub actual: String,
    pub pass: bool,
    pub pass_at_1: bool,
    pub pass_after_repair: bool,
    pub attempts: u8,
    pub prompt_tokens: u32,
    pub completion_tokens: u32,
    pub elapsed_secs: f64,
    pub error: Option<String>,
}

/// Result of an entire suite run
#[derive(Debug, Clone, Serialize)]
pub struct SuiteResult {
    pub suite_name: String,
    pub profile: String,
    pub started_at: String,
    pub completed_at: String,
    pub total_cases: usize,
    pub passed: usize,
    pub failed: usize,
    pub pass_at_1_rate: f64,
    pub pass_after_repair_rate: f64,
    pub cases: Vec<CaseResult>,
}

impl SuitePlan {
    /// Load a suite plan from TOML
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let plan: Self = toml::from_str(&content)?;
        Ok(plan)
    }
}

/// Run a complete evaluation suite
pub async fn run_suite(
    plan: &SuitePlan,
    profile: &ModelProfile,
    output_root: &Path,
    base_dir: &Path, // base directory for resolving task paths
) -> Result<SuiteResult> {
    let suite_start = Utc::now();
    let mut case_results = Vec::new();
    let mut pass_count = 0;
    let mut pass_at_1_count = 0;
    let mut pass_after_repair_count = 0;

    info!(suite = %plan.suite.name, cases = plan.cases.len(), "Starting evaluation suite");
    eprintln!(
        "\n═══ Suite: {} ({} cases) ═══\n",
        plan.suite.name,
        plan.cases.len()
    );

    for (i, case) in plan.cases.iter().enumerate() {
        eprintln!("[{}/{}] {} ...", i + 1, plan.cases.len(), case.name);
        let case_start = std::time::Instant::now();

        let task_path = base_dir.join(&case.task);
        let run_id = format!("{}-{}", plan.suite.name, case.name);

        // Create channels
        let (side_effect_tx, mut side_effect_rx) = mpsc::channel::<SideEffect>(64);
        let (mut controller, event_tx) =
            RunController::new(run_id.clone(), profile.run.max_repairs, side_effect_tx);

        // Create executor
        let mut executor = PipelineExecutor::new(
            profile.clone(),
            event_tx.clone(),
            output_root.to_path_buf(),
            run_id.clone(),
        );

        // Load the task
        executor.load_task_from_path(&task_path).await;

        if let Some(ref target) = case.build_target {
            executor.set_build_target(target.clone());
        }

        if let Some(ref patches) = case.patches {
            executor.set_patches(patches.clone());
        }

        // Run controller and executor concurrently
        let mut controller_handle = tokio::spawn(async move {
            controller.run_to_completion().await;
            controller
        });

        // Process side effects until controller finishes
        let controller = loop {
            tokio::select! {
                Some(effect) = side_effect_rx.recv() => {
                    executor.handle(effect).await;
                }
                res = &mut controller_handle => {
                    let c = res?;
                    side_effect_rx.close();
                    while let Some(effect) = side_effect_rx.recv().await {
                        executor.handle(effect).await;
                    }
                    break c;
                }
            }
        };

        let elapsed = case_start.elapsed().as_secs_f64();

        // Determine result
        let actual_state = match &controller.state.state {
            PipelineState::Completed => "completed",
            PipelineState::Failed { error } => {
                if error.contains("Budget exceeded") || error.contains("budget") {
                    "preflight_rejected"
                } else {
                    "failed"
                }
            }
            PipelineState::Cancelled => "cancelled",
            PipelineState::SkippedByPolicy { .. } => "skipped",
            _ => "unknown",
        };

        let pass = actual_state == case.expect;
        let pass_at_1 = actual_state == "completed" && controller.state.current_attempt <= 1;
        let pass_after_repair = actual_state == "completed" && controller.state.current_attempt > 1;

        if pass {
            pass_count += 1;
        }
        if pass_at_1 {
            pass_at_1_count += 1;
        }
        if pass_after_repair {
            pass_after_repair_count += 1;
        }

        let error = match &controller.state.state {
            PipelineState::Failed { error } => Some(error.clone()),
            _ => None,
        };

        let status_icon = if pass { "✓" } else { "✗" };
        eprintln!(
            "  {} {} (expected: {}, got: {}, {:.1}s)",
            status_icon, case.name, case.expect, actual_state, elapsed
        );

        case_results.push(CaseResult {
            name: case.name.clone(),
            expected: case.expect.clone(),
            actual: actual_state.to_string(),
            pass,
            pass_at_1,
            pass_after_repair,
            attempts: controller.state.current_attempt,
            prompt_tokens: 0, // TODO: capture from model result
            completion_tokens: 0,
            elapsed_secs: elapsed,
            error,
        });
    }

    let suite_end = Utc::now();
    let total = plan.cases.len();
    let completed_count = case_results
        .iter()
        .filter(|c| c.actual == "completed")
        .count();

    let result = SuiteResult {
        suite_name: plan.suite.name.clone(),
        profile: profile.model.name.clone(),
        started_at: suite_start.to_rfc3339(),
        completed_at: suite_end.to_rfc3339(),
        total_cases: total,
        passed: pass_count,
        failed: total - pass_count,
        pass_at_1_rate: if completed_count > 0 {
            pass_at_1_count as f64 / completed_count as f64
        } else {
            0.0
        },
        pass_after_repair_rate: if completed_count > 0 {
            pass_after_repair_count as f64 / completed_count as f64
        } else {
            0.0
        },
        cases: case_results,
    };

    // Print summary
    eprintln!("\n═══ Results ═══");
    eprintln!("Passed: {}/{}", pass_count, total);
    eprintln!("Pass@1: {:.0}%", result.pass_at_1_rate * 100.0);
    eprintln!(
        "Pass after repair: {:.0}%",
        result.pass_after_repair_rate * 100.0
    );

    Ok(result)
}

/// Generate a markdown report from suite results
pub fn format_suite_markdown(result: &SuiteResult) -> String {
    let mut md = String::new();
    md.push_str(&format!("# Evaluation Report: {}\n\n", result.suite_name));
    md.push_str(&format!("**Model:** {}\n\n", result.profile));
    md.push_str(&format!("**Started:** {}\n\n", result.started_at));
    md.push_str(&format!("**Completed:** {}\n\n", result.completed_at));

    md.push_str("## Summary\n\n");
    md.push_str(&format!("| Metric | Value |\n|--------|-------|\n"));
    md.push_str(&format!("| Total cases | {} |\n", result.total_cases));
    md.push_str(&format!("| Passed | {} |\n", result.passed));
    md.push_str(&format!("| Failed | {} |\n", result.failed));
    md.push_str(&format!(
        "| Pass@1 | {:.0}% |\n",
        result.pass_at_1_rate * 100.0
    ));
    md.push_str(&format!(
        "| Pass after repair | {:.0}% |\n\n",
        result.pass_after_repair_rate * 100.0
    ));

    md.push_str("## Cases\n\n");
    md.push_str("| # | Name | Expected | Actual | Pass | Attempts | Time |\n");
    md.push_str("|---|------|----------|--------|------|----------|------|\n");
    for (i, case) in result.cases.iter().enumerate() {
        let pass_icon = if case.pass { "✓" } else { "✗" };
        md.push_str(&format!(
            "| {} | {} | {} | {} | {} | {} | {:.1}s |\n",
            i + 1,
            case.name,
            case.expected,
            case.actual,
            pass_icon,
            case.attempts,
            case.elapsed_secs
        ));
    }

    if result.cases.iter().any(|c| c.error.is_some()) {
        md.push_str("\n## Errors\n\n");
        for case in &result.cases {
            if let Some(error) = &case.error {
                md.push_str(&format!("### {}\n\n```\n{}\n```\n\n", case.name, error));
            }
        }
    }

    md
}
