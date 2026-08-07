use crate::adapter::{AdapterError, OpenAiAdapter};
use serde::{Deserialize, Serialize};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::time::Instant;

#[derive(Debug, Serialize, Deserialize)]
pub struct FailureLog {
    pub fixture_id: String,
    pub model: String,
    pub system_prompt: String,
    pub user_prompt: String,
    pub expected_keys: Vec<String>,
    pub forbidden_keys: Vec<String>,
    pub raw_output: String,
    pub failure_class: String,
}

#[derive(Debug, Serialize)]
pub struct RepairScorecard {
    pub reviewer_model_name: String,
    pub total_failures_processed: usize,
    pub successful_repairs: usize,
    pub failed_repairs: usize,
    pub repair_accuracy: f64,
}

pub struct RepairHarness {
    pub reviewer_model_name: String,
}

impl RepairHarness {
    pub fn new(reviewer_model_name: impl Into<String>) -> Self {
        Self {
            reviewer_model_name: reviewer_model_name.into(),
        }
    }

    pub async fn run_repair_suite(&self, failure_log_path: &str, adapter: &OpenAiAdapter) -> RepairScorecard {
        let mut total_processed = 0;
        let mut successful = 0;
        let mut failed = 0;

        let file = match File::open(failure_log_path) {
            Ok(f) => f,
            Err(_) => {
                // If no failures logged, return an empty scorecard
                return RepairScorecard {
                    reviewer_model_name: self.reviewer_model_name.clone(),
                    total_failures_processed: 0,
                    successful_repairs: 0,
                    failed_repairs: 0,
                    repair_accuracy: 0.0,
                };
            }
        };

        let reader = BufReader::new(file);

        let review_system_prompt = r#"You are the CESARops Qualification Review Guard.
Your job is to review a candidate model's JSON output for constraint omissions.
You will receive the original fixture (System and User prompts) and the Candidate Output.

HARD CONSTRAINTS:
1. The JSON MUST contain all Expected Keys.
2. The JSON MUST NOT contain any Forbidden Keys.

Return ONLY a JSON object with this exact schema:
{
  "accept": boolean,
  "omissions": ["list", "of", "missing or forbidden keys found"],
  "minimal_patch": "string containing the full, valid, patched JSON object"
}
"#;

        for line in reader.lines().flatten() {
            if let Ok(log) = serde_json::from_str::<FailureLog>(&line) {
                total_processed += 1;
                
                let expected_keys_str = log.expected_keys.join(", ");
                let forbidden_keys_str = log.forbidden_keys.join(", ");

                let user_msg = format!(
                    "ORIGINAL SYSTEM PROMPT:\n{}\n\nORIGINAL USER PROMPT:\n{}\n\nEXPECTED KEYS: [{}]\nFORBIDDEN KEYS: [{}]\n\nCANDIDATE OUTPUT:\n{}",
                    log.system_prompt,
                    log.user_prompt,
                    expected_keys_str,
                    forbidden_keys_str,
                    log.raw_output
                );

                if let Ok(response) = adapter.complete(review_system_prompt, &user_msg, 1024, 42).await {
                    let normalized_response = crate::normalizer::normalize_contract(&response);
                    let parsed: Result<serde_json::Value, _> = serde_json::from_str(&normalized_response);
                    if let Ok(val) = parsed {
                        let accept = val.get("accept").and_then(|v| v.as_bool()).unwrap_or(false);
                        if accept {
                            // If they accept it erroneously when we know it's a failure
                            failed += 1;
                            continue;
                        }

                        if let Some(patch_val) = val.get("minimal_patch") {
                            let patch_str = if patch_val.is_object() {
                                serde_json::to_string(patch_val).unwrap_or_default()
                            } else if patch_val.is_string() {
                                patch_val.as_str().unwrap_or_default().to_string()
                            } else {
                                String::new()
                            };

                            // Validate the patch
                            let mut valid = true;
                            let normalized_patch = crate::normalizer::normalize_contract(&patch_str);
                            if let Ok(patched_json) = serde_json::from_str::<serde_json::Value>(&normalized_patch) {
                                // Check expected keys
                                for key in &log.expected_keys {
                                    if patched_json.get(key).is_none() {
                                        valid = false;
                                        break;
                                    }
                                }
                                // Check forbidden keys
                                if valid {
                                    for key in &log.forbidden_keys {
                                        if patched_json.get(key).is_some() {
                                            valid = false;
                                            break;
                                        }
                                    }
                                }
                            } else {
                                valid = false;
                            }

                            if valid {
                                successful += 1;
                            } else {
                                failed += 1;
                            }
                        } else {
                            failed += 1;
                        }
                    } else {
                        failed += 1;
                    }
                } else {
                    failed += 1;
                }
            }
        }

        let accuracy = if total_processed > 0 {
            (successful as f64) / (total_processed as f64)
        } else {
            0.0
        };

        RepairScorecard {
            reviewer_model_name: self.reviewer_model_name.clone(),
            total_failures_processed: total_processed,
            successful_repairs: successful,
            failed_repairs: failed,
            repair_accuracy: accuracy,
        }
    }
}
