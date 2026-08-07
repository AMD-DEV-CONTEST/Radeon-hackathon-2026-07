//! Thomas Translator qualification policy (v1)
//! Ported from wreckhunter2000-1/core/forge-contract-builder-qualify

use serde::{Deserialize, Serialize};

pub const POLICY_VERSION: &str = "thomas-translator.v1";
pub const FIXTURE_SUITE_ID: &str = "contract-builder-thomas-review.v1";

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct QualificationPolicy {
    pub policy_version: String,
    pub suite_id: String,
    pub temperature: f32,
    pub seed: u64,
    pub max_tokens: u32,
    pub repeats: u32,
    pub timeout_secs: u64,
    pub json_mode: bool,
    pub allow_repair: bool,
}

impl Default for QualificationPolicy {
    fn default() -> Self {
        Self {
            policy_version: POLICY_VERSION.into(),
            suite_id: FIXTURE_SUITE_ID.into(),
            temperature: 0.0,
            seed: 42,
            max_tokens: 4096,
            repeats: 3,
            timeout_secs: 300,
            json_mode: true,
            allow_repair: true,
        }
    }
}
