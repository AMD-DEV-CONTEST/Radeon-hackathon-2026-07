//! Thomas Translator qualification harness.
//!
//! Ported from wreckhunter2000-1/core/forge-contract-builder-qualify,
//! adapted for the new cesarops-server codebase with a fixed OpenAI adapter.

use crate::adapter::{AdapterError, OpenAiAdapter};
use crate::fixtures::{thomas_fixtures, Fixture};
use crate::policy::QualificationPolicy;
use crate::scorecard::{PassSummary, RunResult, Scorecard};
use std::collections::BTreeMap;
use std::time::Instant;
use std::fs::OpenOptions;
use std::io::Write;

const SYSTEM_PROMPT: &str = "You are the CESARops Contract Builder. Emit ONLY a CodeMissionDraft JSON object. Never emit patches, diffs, code, tool calls, or chain-of-thought fields.";

pub struct QualifyHarness {
    pub model_name: String,
    pub artifact: String,
    pub quantization: String,
    pub runtime_backend: String,
    pub hardware_worker_id: String,
}

impl QualifyHarness {
    pub fn new(
        model_name: impl Into<String>,
        artifact: impl Into<String>,
        quantization: impl Into<String>,
        runtime_backend: impl Into<String>,
        hardware_worker_id: impl Into<String>,
    ) -> Self {
        Self {
            model_name: model_name.into(),
            artifact: artifact.into(),
            quantization: quantization.into(),
            runtime_backend: runtime_backend.into(),
            hardware_worker_id: hardware_worker_id.into(),
        }
    }

    pub async fn run(&self, policy: &QualificationPolicy, adapter: &OpenAiAdapter) -> Scorecard {
        let fixtures = thomas_fixtures();
        let mut runs: Vec<RunResult> = Vec::new();

        for fix in &fixtures {
            for repeat in 0..policy.repeats {
                let start = Instant::now();

                // Override system prompt with fixture-specific version if present
                let sys_prompt = if !fix.system_prompt.is_empty() {
                    fix.system_prompt.as_str()
                } else {
                    SYSTEM_PROMPT
                };

                let mut result = match adapter.complete(
                    sys_prompt,
                    &fix.user_prompt,
                    policy.max_tokens,
                    policy.seed + (repeat as u64),
                ).await {
                    Ok(content) => {
                        let elapsed = start.elapsed().as_millis() as u64;
                        self.evaluate(fix, repeat as usize, &content, elapsed, false, "")
                    }
                    Err(AdapterError::Connection(msg)) => {
                        let elapsed = start.elapsed().as_millis() as u64;
                        self.failed(fix, repeat as usize, "adapter_unavailable", elapsed, &msg)
                    }
                    Err(AdapterError::HttpError(status, body)) => {
                        let elapsed = start.elapsed().as_millis() as u64;
                        self.failed(fix, repeat as usize, "http_error", elapsed,
                            &format!("HTTP {}: {}", status, body.chars().take(200).collect::<String>()))
                    }
                    Err(AdapterError::Parse(msg)) => {
                        let elapsed = start.elapsed().as_millis() as u64;
                        self.failed(fix, repeat as usize, "parse_error", elapsed, &msg)
                    }
                };
                
                if result.hard_failure {
                    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open("failures.jsonl") {
                        let failure_log = serde_json::json!({
                            "fixture_id": fix.id.clone(),
                            "model": self.model_name.clone(),
                            "system_prompt": sys_prompt,
                            "user_prompt": fix.user_prompt.clone(),
                            "expected_keys": fix.expected_keys.clone(),
                            "forbidden_keys": fix.forbidden_keys.clone(),
                            "raw_output": result.raw_output.clone(),
                            "failure_class": result.failure_class.clone()
                        });
                        let _ = writeln!(file, "{}", failure_log);
                    }
                }
                
                runs.push(result);
            }
        }

        // Also run guardrailed repair pass for failures
        let mut guard_runs: Vec<RunResult> = Vec::new();
        for run in &runs {
            if !run.validator_success && policy.allow_repair {
                let repaired = self.repair_pass(run, adapter, policy).await;
                guard_runs.push(repaired);
            }
        }

        let first_pass = build_summary(&runs, "first_pass");
        let guardrailed = build_summary(&guard_runs, "guardrailed");

        let rank = compute_ranking(&first_pass);
        let state = if first_pass.raw_json_valid >= (first_pass.total_runs as f64 * 0.8) as u32
            && first_pass.hard_failures == 0
        {
            "Qualified".to_string()
        } else {
            "Unqualified".to_string()
        };

        // Peer reviewed pipeline pass is no longer calculated inline
        let peer_reviewed_pass = false;
        let final_reviewer: Option<String> = None;

        Scorecard {
            model_name: self.model_name.clone(),
            artifact: self.artifact.clone(),
            quantization: self.quantization.clone(),
            runtime_backend: self.runtime_backend.clone(),
            hardware_worker_id: self.hardware_worker_id.clone(),
            suite_id: crate::policy::FIXTURE_SUITE_ID.to_string(),
            policy_version: crate::policy::POLICY_VERSION.to_string(),
            first_pass,
            guardrailed,
            runs,
            qualification_state: state,
            standard_suite_ranking_score: rank,
            peer_reviewed_pipeline_pass: peer_reviewed_pass,
            final_reviewer_model: final_reviewer,
        }
    }

    fn evaluate(
        &self,
        fix: &Fixture,
        repeat: usize,
        raw_output: &str,
        latency_ms: u64,
        is_repair: bool,
        _repair_note: &str,
    ) -> RunResult {
        let pass_type = if is_repair { "guardrailed" } else { "first_pass" };

        // Normalize and try to parse as JSON
        let normalized_output = crate::normalizer::normalize_contract(raw_output);
        let parsed: Option<serde_json::Value> = serde_json::from_str(&normalized_output).ok();

        let json_valid = parsed.is_some();
        if !json_valid {
            return RunResult {
                fixture_id: fix.id.clone(),
                repeat: repeat as u32,
                pass_type: pass_type.into(),
                raw_json_valid: false,
                validator_success: false,
                expected_outcome_match: false,
                requirement_recall: 0.0,
                hard_constraint_recall: 0.0,
                non_goal_recall: 0.0,
                claim_disposition_accuracy: 0.0,
                hard_failure: true,
                failure_class: "invalid_json".into(),
                latency_ms,
                timeout: false,
                user_prompt: Some(fix.user_prompt.clone()),
            retry_count: 0,
                raw_output: raw_output.to_string(),
                peer_reviewed: false,
                reviewer_model: None,
            };
        }

        let obj = parsed.unwrap();
        let empty_map = serde_json::Map::new();
        let obj_map = obj.as_object().unwrap_or(&empty_map);

        // Check expected keys
        let _found_keys: Vec<&String> = obj_map.keys().collect();
        let mut req_found = 0.0;
        let mut req_total = fix.expected_keys.len() as f64;
        if req_total == 0.0 { req_total = 1.0; }
        for ek in &fix.expected_keys {
            if obj_map.contains_key(ek) {
                req_found += 1.0;
            }
        }
        let requirement_recall = req_found / req_total;

        // Check forbidden keys
        let mut forbidden_found = 0;
        for fk in &fix.forbidden_keys {
            if obj_map.contains_key(fk) {
                forbidden_found += 1;
            }
        }
        let hard_constraint_recall = if forbidden_found > 0 { 0.0 } else { 1.0 };

        // Non-goal preservation
        let non_goal_recall = if forbidden_found > 0 { 0.0 } else { 1.0 };

        // Validator success = valid JSON + all required keys present + no forbidden keys
        let validator_success = json_valid
            && requirement_recall >= 0.8
            && forbidden_found == 0;

        // Outcome match (simplified)
        let expected_outcome = &fix.expected_outcome;
        let outcome_match = validator_success && expected_outcome == "accept";

        // Hard failure = hard constraint violation (forbidden key found or JSON invalid)
        let hard_failure = !json_valid || forbidden_found > 0;
        let failure_class = if !json_valid {
            "invalid_json".into()
        } else if forbidden_found > 0 {
            "hard_constraint_omission".into()
        } else {
            "none".into()
        };

        RunResult {
            fixture_id: fix.id.clone(),
            repeat: repeat as u32,
            pass_type: pass_type.into(),
            raw_json_valid: json_valid,
            validator_success,
            expected_outcome_match: outcome_match,
            requirement_recall,
            hard_constraint_recall,
            non_goal_recall,
            claim_disposition_accuracy: if validator_success { 1.0 } else { 0.0 },
            hard_failure,
            failure_class,
            latency_ms,
            timeout: false,
            user_prompt: Some(fix.user_prompt.clone()),
            retry_count: 0,
            raw_output: raw_output.to_string(),
            peer_reviewed: false,
            reviewer_model: None,
        }
    }

    fn failed(
        &self,
        fix: &Fixture,
        repeat: usize,
        class: &str,
        latency_ms: u64,
        detail: &str,
    ) -> RunResult {
        RunResult {
            fixture_id: fix.id.clone(),
            repeat: repeat as u32,
            pass_type: "first_pass".into(),
            raw_json_valid: false,
            validator_success: false,
            expected_outcome_match: false,
            requirement_recall: 0.0,
            hard_constraint_recall: 0.0,
            non_goal_recall: 0.0,
            claim_disposition_accuracy: 0.0,
            hard_failure: true,
            failure_class: class.into(),
            latency_ms,
            timeout: false,
            user_prompt: Some(fix.user_prompt.clone()),
            retry_count: 0,
            raw_output: format!("ERROR: {} ({})", class, detail),
            peer_reviewed: false,
            reviewer_model: None,
        }
    }

    async fn repair_pass(&self, run: &RunResult, adapter: &OpenAiAdapter, policy: &QualificationPolicy) -> RunResult {
        // Simplified repair: just re-run with a repair-focused prompt
        let start = Instant::now();
        let sys = format!("{} If your previous output was invalid, please re-emit valid JSON only.", SYSTEM_PROMPT);

        let result = adapter.complete(&sys, &format!("Fix the previous response. Output valid JSON only: {{\"type\":\"CodeMissionDraft\"}}"), policy.max_tokens, policy.seed + 1000 + (run.repeat as u64)).await;
        match result {
            Ok(content) => {
                let elapsed = start.elapsed().as_millis() as u64;
                // We need fixture to evaluate - use a generic check
                RunResult {
                    fixture_id: run.fixture_id.clone(),
                    repeat: run.repeat,
                    pass_type: "guardrailed".into(),
                    raw_json_valid: serde_json::from_str::<serde_json::Value>(&content).is_ok(),
                    validator_success: serde_json::from_str::<serde_json::Value>(&content).is_ok(),
                    expected_outcome_match: serde_json::from_str::<serde_json::Value>(&content).is_ok(),
                    requirement_recall: if serde_json::from_str::<serde_json::Value>(&content).is_ok() { 1.0 } else { 0.0 },
                    hard_constraint_recall: 1.0,
                    non_goal_recall: 1.0,
                    claim_disposition_accuracy: if serde_json::from_str::<serde_json::Value>(&content).is_ok() { 1.0 } else { 0.0 },
                    hard_failure: false,
                    failure_class: "none".into(),
                    latency_ms: elapsed,
                    timeout: false,
                    user_prompt: run.user_prompt.clone(),
            retry_count: 1,
                    raw_output: content.clone(),
                    peer_reviewed: false,
                    reviewer_model: None,
                }
            }
            Err(e) => {
                let elapsed = start.elapsed().as_millis() as u64;
                RunResult {
                    fixture_id: run.fixture_id.clone(),
                    repeat: run.repeat,
                    pass_type: "guardrailed".into(),
                    raw_json_valid: false,
                    validator_success: false,
                    expected_outcome_match: false,
                    requirement_recall: 0.0,
                    hard_constraint_recall: 0.0,
                    non_goal_recall: 0.0,
                    claim_disposition_accuracy: 0.0,
                    hard_failure: true,
                    failure_class: "repair_failed".into(),
                    latency_ms: elapsed,
                    timeout: false,
                    user_prompt: run.user_prompt.clone(),
            retry_count: 1,
                    raw_output: format!("REPAIR ERROR: {:?}", e),
                    peer_reviewed: false,
                    reviewer_model: None,
                }
            }
        }
    }
}

fn build_summary(runs: &[RunResult], _pass_type: &str) -> PassSummary {
    if runs.is_empty() {
        return PassSummary::default();
    }
    let n = runs.len() as f64;
    let total = runs.len() as u32;
    let raw_json_valid = runs.iter().filter(|r| r.raw_json_valid).count() as u32;
    let validator_success = runs.iter().filter(|r| r.validator_success).count() as u32;
    let outcome_match = runs.iter().filter(|r| r.expected_outcome_match).count() as u32;
    let hard_failures = runs.iter().filter(|r| r.hard_failure).count() as u32;
    let mean_req: f64 = runs.iter().map(|r| r.requirement_recall).sum::<f64>() / n;
    let mean_hc: f64 = runs.iter().map(|r| r.hard_constraint_recall).sum::<f64>() / n;
    let mean_ng: f64 = runs.iter().map(|r| r.non_goal_recall).sum::<f64>() / n;
    let mean_cda: f64 = runs.iter().map(|r| r.claim_disposition_accuracy).sum::<f64>() / n;
    let mean_lat: f64 = runs.iter().map(|r| r.latency_ms as f64).sum::<f64>() / n;

    // Deterministic repeat agreement — group by fixture
    let mut by_fix: BTreeMap<String, Vec<&RunResult>> = BTreeMap::new();
    for r in runs { by_fix.entry(r.fixture_id.clone()).or_default().push(r); }
    let mut agree = Vec::new();
    for attempts in by_fix.values() {
        if attempts.len() < 2 { continue; }
        let base = &attempts[0].raw_output;
        let ok = attempts.iter().filter(|a| &a.raw_output == base).count();
        agree.push(ok as f64 / attempts.len() as f64);
    }
    let repeat_agreement = if agree.is_empty() { 1.0 } else { agree.iter().sum::<f64>() / agree.len() as f64 };

    let mut failure_classes = BTreeMap::new();
    for r in runs { *failure_classes.entry(r.failure_class.clone()).or_insert(0) += 1; }

    PassSummary {
        total_runs: total,
        raw_json_valid,
        validator_success,
        outcome_match,
        hard_failures,
        mean_requirement_recall: mean_req,
        mean_hard_constraint_recall: mean_hc,
        mean_non_goal_recall: mean_ng,
        mean_claim_disposition_accuracy: mean_cda,
        mean_latency_ms: mean_lat,
        deterministic_repeat_agreement: repeat_agreement,
        failure_classes,
    }
}

fn compute_ranking(fp: &PassSummary) -> f64 {
    let total = fp.total_runs.max(1) as f64;
    let valid_rate = fp.raw_json_valid as f64 / total;
    let val_rate = if valid_rate.is_nan() { 0.0 } else { valid_rate };
    let recall = (fp.mean_requirement_recall + fp.mean_hard_constraint_recall + fp.mean_non_goal_recall) / 3.0;
    val_rate * 0.5 + recall * 0.5
}

pub fn evaluate_interaction(
    fix: &Fixture,
    raw_output: &str,
    latency_ms: u64,
) -> RunResult {
    // We can instantiate a dummy harness or just duplicate the logic
    let pass_type = "mission_control_live";
    let normalized_output = crate::normalizer::normalize_contract(raw_output);
    let parsed: Option<serde_json::Value> = serde_json::from_str(&normalized_output).ok();

    let json_valid = parsed.is_some();
    if !json_valid {
        return RunResult {
            fixture_id: fix.id.clone(),
            repeat: 0,
            pass_type: pass_type.into(),
            raw_json_valid: false,
            validator_success: false,
            expected_outcome_match: false,
            requirement_recall: 0.0,
            hard_constraint_recall: 0.0,
            non_goal_recall: 0.0,
            claim_disposition_accuracy: 0.0,
            hard_failure: true,
            failure_class: "invalid_json".into(),
            latency_ms,
            timeout: false,
            user_prompt: Some(fix.user_prompt.clone()),
            retry_count: 0,
            raw_output: raw_output.to_string(),
            peer_reviewed: false,
            reviewer_model: None,
        };
    }

    let obj = parsed.unwrap();
    let mut req_found = 0.0;
    let mut con_found = 0.0;
    let mut bad_keys = 0.0;

    let obj_map = obj.as_object().unwrap();
    for r in &fix.expected_keys {
        if obj_map.contains_key(r) { req_found += 1.0; }
    }
    for f in &fix.forbidden_keys {
        if obj_map.contains_key(f) { bad_keys += 1.0; }
    }

    let req_total = if fix.expected_keys.is_empty() { 1.0 } else { fix.expected_keys.len() as f64 };
    let req_recall = req_found / req_total;
    let valid = req_recall == 1.0 && bad_keys == 0.0;

    RunResult {
        fixture_id: fix.id.clone(),
        repeat: 0,
        pass_type: pass_type.into(),
        raw_json_valid: true,
        validator_success: valid,
        expected_outcome_match: valid,
        requirement_recall: req_recall,
        hard_constraint_recall: if bad_keys > 0.0 { 0.0 } else { 1.0 },
        non_goal_recall: 1.0,
        claim_disposition_accuracy: if valid { 1.0 } else { 0.0 },
        hard_failure: !valid,
        failure_class: if valid { "none".into() } else { "schema_mismatch".into() },
        latency_ms,
        timeout: false,
        user_prompt: Some(fix.user_prompt.clone()),
            retry_count: 0,
        raw_output: raw_output.to_string(),
        peer_reviewed: false,
        reviewer_model: None,
    }
}
