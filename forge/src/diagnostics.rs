use crate::translator::FailureType;
use crate::AppState;
use serde::Serialize;
use tracing::{info, warn};

/// Result of the 8B diagnostic analysis.
#[derive(Debug, Clone, Serialize)]
pub struct DiagnosisResult {
    pub explanation: String,
    pub prompt_override: Option<String>,
    pub confidence: f32,
}

/// Send a failure to the 8B on cesarops2 for diagnosis.
/// Returns a diagnosis with explanation and optional prompt rewrite.
pub async fn diagnose(
    prompt_tail: &str,
    raw_output: &str,
    failure_type: &FailureType,
    state: &AppState,
) -> Option<DiagnosisResult> {
    info!("Diagnosing failure: {:?}", failure_type);

    // First, search nautivecs for prior fixes
    let prior_fix = search_prior_fix(failure_type, state).await;
    if let Some(fix) = prior_fix {
        info!("Found prior fix in nautivecs, skipping 8B diagnosis");
        return Some(DiagnosisResult {
            explanation: format!("Prior fix found: {}", &fix[..fix.len().min(100)]),
            prompt_override: Some(fix),
            confidence: 0.95,
        });
    }

    // Build diagnostic prompt for the 8B
    let diag_prompt = format!(
        r#"<|im_start|>system
You are a diagnostic assistant. A larger model (35B) has failed to produce useful output.
Analyze the failure and provide a corrected prompt approach.

Respond in this exact JSON format:
{{"explanation": "why it failed", "prompt_override": "rewritten instruction to fix it", "confidence": 0.0-1.0}}
<|im_end|>
<|im_start|>user
## Failure Type: {:?}

## Last prompt sent (tail):
{}

## Raw output received:
{}

## What went wrong and how should the prompt be rewritten?<|im_end|>
<|im_start|>assistant
"#,
        failure_type,
        truncate(prompt_tail, 500),
        truncate(raw_output, 500),
    );

    // Call 8B on cesarops2
    let client = reqwest::Client::new();
    let payload = serde_json::json!({
        "prompt": diag_prompt,
        "max_length": 1500,
        "temperature": 0.3,
        "top_p": 0.9,
        "stop_sequence": ["<|im_end|>", "\n\n\n"],
    });

    let resp = match client
        .post(format!("{}/api/v1/generate", state.config.thinker_url))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .await
    {
        Ok(r) => r,
        Err(e) => {
            warn!("8B diagnosis request failed: {}", e);
            return None;
        }
    };

    let body: serde_json::Value = match resp.json().await {
        Ok(b) => b,
        Err(e) => {
            warn!("8B diagnosis parse failed: {}", e);
            return None;
        }
    };

    let text = body
        .get("results")
        .and_then(|r| r.as_array())
        .and_then(|a| a.first())
        .and_then(|r| r.get("text"))
        .and_then(|t| t.as_str())
        .unwrap_or("");

    // Try to parse as JSON
    parse_diagnosis(text)
}

/// Search nautivecs for a prior fix matching this failure type.
async fn search_prior_fix(failure_type: &FailureType, state: &AppState) -> Option<String> {
    let query = format!("format_fix {:?}", failure_type);
    let client = reqwest::Client::new();

    let resp = client
        .post(&state.config.nautivecs_url)
        .json(&serde_json::json!({"query": query, "top_k": 1}))
        .timeout(std::time::Duration::from_secs(5))
        .send()
        .await
        .ok()?;

    let body: serde_json::Value = resp.json().await.ok()?;

    // Check if we got a relevant result with high similarity
    let results = body.get("results").and_then(|r| r.as_array())?;
    let first = results.first()?;
    let score = first.get("score").and_then(|s| s.as_f64()).unwrap_or(0.0);
    let content = first.get("content").and_then(|c| c.as_str())?;

    if score > 0.75 {
        // Extract the prompt_override from the stored fix
        if content.contains("Fix:") {
            let fix = content.split("Fix:").nth(1)?.trim().to_string();
            Some(fix)
        } else {
            Some(content.to_string())
        }
    } else {
        None
    }
}

/// Parse the 8B's JSON response into a DiagnosisResult.
fn parse_diagnosis(text: &str) -> Option<DiagnosisResult> {
    // Try direct JSON parse
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(text.trim()) {
        let explanation = v.get("explanation").and_then(|e| e.as_str()).unwrap_or("Unknown").to_string();
        let prompt_override = v.get("prompt_override").and_then(|p| p.as_str()).map(|s| s.to_string());
        let confidence = v.get("confidence").and_then(|c| c.as_f64()).unwrap_or(0.5) as f32;

        return Some(DiagnosisResult {
            explanation,
            prompt_override,
            confidence,
        });
    }

    // Fallback: try to find JSON in the text
    if let Some(start) = text.find('{') {
        if let Some(end) = text.rfind('}') {
            let json_slice = &text[start..=end];
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(json_slice) {
                let explanation = v.get("explanation").and_then(|e| e.as_str()).unwrap_or("Unknown").to_string();
                let prompt_override = v.get("prompt_override").and_then(|p| p.as_str()).map(|s| s.to_string());
                let confidence = v.get("confidence").and_then(|c| c.as_f64()).unwrap_or(0.5) as f32;

                return Some(DiagnosisResult {
                    explanation,
                    prompt_override,
                    confidence,
                });
            }
        }
    }

    // Last resort: treat the whole text as the explanation
    if !text.trim().is_empty() {
        Some(DiagnosisResult {
            explanation: text.trim().to_string(),
            prompt_override: None,
            confidence: 0.3,
        })
    } else {
        None
    }
}

fn truncate(s: &str, max: usize) -> &str {
    if s.len() > max {
        &s[..max]
    } else {
        s
    }
}
