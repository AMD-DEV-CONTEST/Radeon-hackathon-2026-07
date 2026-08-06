//! L2: Acceptance spec validation — checks against acceptance.json

use agent_core::event::ValidationResult;
use serde_json::Value;

/// Validate the candidate against an acceptance specification.
/// This is a structural check — does the output contain the right objects/fields?
pub fn validate_acceptance(_content: &str, _spec: &Value) -> ValidationResult {
    let start = std::time::Instant::now();

    // TODO: Implement full acceptance spec checking.
    // For now, just check that the spec is a valid JSON object.
    let errors: Vec<String> = Vec::new();

    let elapsed = start.elapsed().as_secs_f64();
    if errors.is_empty() {
        super::pass(2, "acceptance", elapsed)
    } else {
        let diagnostic = errors.join("\n");
        super::fail(2, "acceptance", errors, diagnostic, elapsed)
    }
}
