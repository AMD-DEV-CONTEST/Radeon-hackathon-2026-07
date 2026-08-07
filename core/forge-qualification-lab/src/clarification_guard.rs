use crate::adapter::{AdapterError, OpenAiAdapter};
use crate::fixtures::Fixture;

const REVIEW_SYSTEM_PROMPT: &str = r#"You are the CESARops Qualification Review Guard.
Your job is to blindly review a candidate model's JSON output for constraint omissions.
You will receive the original fixture (System and User prompts) and the Candidate Output.

HARD CONSTRAINTS FOR THIS FIXTURE:
1. The JSON MUST contain all Expected Keys.
2. The JSON MUST NOT contain any Forbidden Keys.

Analyze the Candidate Output. If it violates ANY hard constraint, reject it.
Return ONLY a JSON object with this exact schema:
{
  "accept": boolean,
  "omissions": ["list", "of", "missing or forbidden keys found"],
  "source_constraint": "string citing which rule failed",
  "minimal_patch": "string containing the full, valid, patched JSON object"
}
"#;

pub struct ClarificationGuard {
    reviewer_adapter: OpenAiAdapter,
    pub reviewer_model_id: String,
}

impl ClarificationGuard {
    pub fn new() -> Self {
        // We configure it to use NIM by default as per the user's setup, or we could make it configurable.
        let adapter = OpenAiAdapter::new(
            "https://integrate.api.nvidia.com",
            "nvidia/llama-3.3-nemotron-super-49b-v1"
        );
        Self {
            reviewer_adapter: adapter,
            reviewer_model_id: "nvidia/llama-3.3-nemotron-super-49b-v1".into(),
        }
    }

    pub async fn review_and_repair(
        &self,
        fixture: &Fixture,
        candidate_output: &str,
        seed: u64,
    ) -> Result<(bool, String), AdapterError> {
        let expected_keys_str = fixture.expected_keys.join(", ");
        let forbidden_keys_str = fixture.forbidden_keys.join(", ");

        let user_msg = format!(
            "ORIGINAL SYSTEM PROMPT:\n{}\n\nORIGINAL USER PROMPT:\n{}\n\nEXPECTED KEYS: [{}]\nFORBIDDEN KEYS: [{}]\n\nCANDIDATE OUTPUT:\n{}",
            fixture.system_prompt,
            fixture.user_prompt,
            expected_keys_str,
            forbidden_keys_str,
            candidate_output
        );

        let response = self.reviewer_adapter.complete(
            REVIEW_SYSTEM_PROMPT,
            &user_msg,
            1024,
            seed,
        ).await?;

        // Parse the reviewer's response
        let normalized_response = crate::normalizer::normalize_contract(&response);
        let parsed: Result<serde_json::Value, _> = serde_json::from_str(&normalized_response);
        if let Ok(val) = parsed {
            let accept = val.get("accept").and_then(|v| v.as_bool()).unwrap_or(false);
            
            // Check if minimal patch exists
            if let Some(patch_val) = val.get("minimal_patch") {
                let patch_str = if patch_val.is_object() {
                    serde_json::to_string(patch_val).unwrap_or_default()
                } else if patch_val.is_string() {
                    patch_val.as_str().unwrap_or_default().to_string()
                } else {
                    String::new()
                };

                let normalized_patch = crate::normalizer::normalize_contract(&patch_str);
                return Ok((accept, normalized_patch));
            }
        }
        
        Ok((false, String::new()))
    }
}
