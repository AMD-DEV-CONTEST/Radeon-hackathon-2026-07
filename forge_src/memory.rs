use crate::diagnostics::DiagnosisResult;
use crate::translator::FailureType;
use crate::AppState;
use tracing::info;

/// Auto-remember a successful diagnosis fix to nautivecs and local log.
/// Called when a diagnosis leads to a successful recovery.
pub async fn auto_remember_success(
    diagnosis: &DiagnosisResult,
    failure_type: &FailureType,
    model_name: &str,
    state: &AppState,
) {
    let content = format!(
        "Model '{}' failed with {:?}. Fix: {}. Confidence: {:.2}",
        model_name,
        failure_type,
        diagnosis.prompt_override.as_deref().unwrap_or(&diagnosis.explanation),
        diagnosis.confidence,
    );
    let tags = format!("{},format_fix,{:?}", model_name, failure_type);

    info!("Auto-remembering fix: {}", &content[..content.len().min(100)]);

    // Save to local log (fire and forget)
    let args = serde_json::json!({
        "content": content,
        "tags": tags,
    });
    let _ = crate::tools::execute("remember", &args, state).await;

    // Also push to nautivecs for semantic search (background, non-blocking)
    let nautivecs_url = state.config.nautivecs_url.clone();
    let content_clone = content.clone();
    let tags_clone = tags.clone();

    tokio::spawn(async move {
        let client = reqwest::Client::new();
        let _ = client
            .post(nautivecs_url.replace("/query", "/ingest"))
            .json(&serde_json::json!({
                "content": content_clone,
                "metadata": {"tags": tags_clone, "type": "auto_fix"},
            }))
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await;
    });
}

/// Search nautivecs for prior fixes matching a failure type.
/// Returns the fix content if found with high confidence.
pub async fn search_prior_fixes(failure_type: &FailureType, state: &AppState) -> Option<String> {
    let query = format!("format_fix {:?} recovery", failure_type);
    let client = reqwest::Client::new();

    let resp = client
        .post(&state.config.nautivecs_url)
        .json(&serde_json::json!({"query": query, "top_k": 3}))
        .timeout(std::time::Duration::from_secs(5))
        .send()
        .await
        .ok()?;

    let body: serde_json::Value = resp.json().await.ok()?;
    let results = body.get("results").and_then(|r| r.as_array())?;

    // Prioritize web-crawled fixes over hallucinated ones
    for result in results {
        let score = result.get("score").and_then(|s| s.as_f64()).unwrap_or(0.0);
        let content = result.get("content").and_then(|c| c.as_str()).unwrap_or("");
        let metadata = result.get("metadata");

        if score > 0.7 {
            // Check if this is a web-sourced fix (higher priority)
            let is_web = metadata
                .and_then(|m| m.get("source"))
                .and_then(|s| s.as_str())
                .map(|s| s == "web")
                .unwrap_or(false);

            if is_web || score > 0.85 {
                return Some(content.to_string());
            }
        }
    }

    None
}
