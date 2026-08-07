//! Scorecard types for qualification runs.
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RunResult {
    pub fixture_id: String,
    pub repeat: u32,
    pub pass_type: String,
    pub raw_json_valid: bool,
    pub validator_success: bool,
    pub expected_outcome_match: bool,
    pub requirement_recall: f64,
    pub hard_constraint_recall: f64,
    pub non_goal_recall: f64,
    pub claim_disposition_accuracy: f64,
    pub hard_failure: bool,
    pub failure_class: String,
    pub latency_ms: u64,
    pub timeout: bool,
    pub retry_count: u32,
    pub user_prompt: Option<String>,
    pub raw_output: String,
    pub peer_reviewed: bool,
    pub reviewer_model: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, Default)]
pub struct PassSummary {
    pub total_runs: u32,
    pub raw_json_valid: u32,
    pub validator_success: u32,
    pub outcome_match: u32,
    pub hard_failures: u32,
    pub mean_requirement_recall: f64,
    pub mean_hard_constraint_recall: f64,
    pub mean_non_goal_recall: f64,
    pub mean_claim_disposition_accuracy: f64,
    pub mean_latency_ms: f64,
    pub deterministic_repeat_agreement: f64,
    pub failure_classes: BTreeMap<String, u32>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Scorecard {
    pub model_name: String,
    pub artifact: String,
    pub quantization: String,
    pub runtime_backend: String,
    pub hardware_worker_id: String,
    pub suite_id: String,
    pub policy_version: String,
    pub first_pass: PassSummary,
    pub guardrailed: PassSummary,
    pub runs: Vec<RunResult>,
    pub qualification_state: String,
    pub standard_suite_ranking_score: f64,
    pub peer_reviewed_pipeline_pass: bool,
    pub final_reviewer_model: Option<String>,
}
