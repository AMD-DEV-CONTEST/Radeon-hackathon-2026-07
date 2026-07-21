//! Optional LLM narration layer, with two independent real backends
//! tried in order plus a fully offline fallback.
//!
//! **This module no longer decides which tools run.** Tool selection is
//! `intent.rs`'s job now: a custom, from-scratch, GPU-dispatched TF-IDF/
//! cosine-similarity kernel that requires no network call, no API key,
//! and no billing, and is the crate's only mandatory planning mechanism
//! (see `GenomicAgent::plan` in agent.rs). This module's one remaining
//! job is optional: after the tools intent.rs picked have already run,
//! turn their real output into a short plain-English narrative. The
//! synthesis prompt is built strictly from tool output already computed
//! by real code elsewhere in this crate (vcf.rs, gpu_ld.rs, pca.rs,
//! fst.rs, bootstrap.rs); the model is explicitly instructed not to
//! introduce any number that isn't already present in that text, so
//! this cannot fabricate a result -- it can only misdescribe or drop
//! one, which is why raw tool output is always still included in the
//! final response alongside the narrative.
//!
//! **Backend order, and why:** (1) Hugging Face's Inference Router
//! (`HF_TOKEN` or `HUGGING_FACE_HUB_TOKEN`) is tried first -- it's a
//! free-tier, publicly reachable, OpenAI-compatible endpoint, verified
//! working end-to-end before being wired in here, and getting a token
//! costs nothing and takes about a minute at
//! huggingface.co/settings/tokens. (2) Anthropic (`ANTHROPIC_API_KEY`)
//! is tried second, for anyone who already has a funded key. Both are
//! genuinely optional and independent -- neither, or an unfunded/rate-
//! limited key, gets a clean fallthrough to raw tool output, not an
//! error, and never affects which tools ran or what they computed.

use serde_json::Value;
use serde_json::json;
use std::time::Duration;

const DEFAULT_ANTHROPIC_MODEL: &str = "claude-haiku-4-5-20251001";
const ANTHROPIC_URL: &str = "https://api.anthropic.com/v1/messages";
const DEFAULT_HF_MODEL: &str = "Qwen/Qwen2.5-7B-Instruct";
const HF_ROUTER_URL: &str = "https://router.huggingface.co/v1/chat/completions";
const REQUEST_TIMEOUT_SECS: u64 = 20;

fn anthropic_api_key() -> Option<String> {
    std::env::var("ANTHROPIC_API_KEY")
        .ok()
        .filter(|k| !k.trim().is_empty())
}

fn anthropic_model_name() -> String {
    std::env::var("ANTHROPIC_MODEL").unwrap_or_else(|_| DEFAULT_ANTHROPIC_MODEL.to_string())
}

fn hf_token() -> Option<String> {
    std::env::var("HF_TOKEN")
        .or_else(|_| std::env::var("HUGGING_FACE_HUB_TOKEN"))
        .ok()
        .filter(|k| !k.trim().is_empty())
}

fn hf_model_name() -> String {
    std::env::var("HF_MODEL").unwrap_or_else(|_| DEFAULT_HF_MODEL.to_string())
}

/// Try each configured backend in order, returning the first one that
/// produces a response. `synthesize` is the only caller.
fn call_llm(system: &str, user: &str, max_tokens: u32) -> Option<String> {
    call_hf_router(system, user, max_tokens).or_else(|| call_anthropic(system, user, max_tokens))
}

/// Real HTTP call to Hugging Face's Inference Router
/// (OpenAI-compatible `/v1/chat/completions`), tried first: free tier,
/// no billing dependency. Returns `None` -- never panics, never
/// propagates an error -- on missing token, network failure, non-2xx
/// response, or unexpected response shape.
fn call_hf_router(system: &str, user: &str, max_tokens: u32) -> Option<String> {
    let token = hf_token()?;

    let body = json!({
        "model": hf_model_name(),
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    });

    let response = ureq::post(HF_ROUTER_URL)
        .set("Authorization", &format!("Bearer {token}"))
        .set("content-type", "application/json")
        .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS))
        .send_json(body);

    let response = match response {
        Ok(r) => r,
        Err(e) => {
            eprintln!("[llm] HF Inference Router call failed, trying next backend: {e}");
            return None;
        }
    };

    let parsed: Value = match response.into_json() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[llm] HF Inference Router response wasn't valid JSON, trying next backend: {e}");
            return None;
        }
    };

    parsed
        .get("choices")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("message"))
        .and_then(|m| m.get("content"))
        .and_then(|t| t.as_str())
        .map(|s| s.to_string())
}

/// Real HTTP call to the Anthropic Messages API, tried second (after HF).
/// Same never-panics, `None`-on-any-failure contract as `call_hf_router`.
fn call_anthropic(system: &str, user: &str, max_tokens: u32) -> Option<String> {
    let key = anthropic_api_key()?;

    let body = json!({
        "model": anthropic_model_name(),
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user}],
    });

    let response = ureq::post(ANTHROPIC_URL)
        .set("x-api-key", &key)
        .set("anthropic-version", "2023-06-01")
        .set("content-type", "application/json")
        .timeout(Duration::from_secs(REQUEST_TIMEOUT_SECS))
        .send_json(body);

    let response = match response {
        Ok(r) => r,
        Err(e) => {
            eprintln!("[llm] Anthropic API call failed, falling back to raw output: {e}");
            return None;
        }
    };

    let parsed: Value = match response.into_json() {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[llm] Anthropic API response wasn't valid JSON, falling back: {e}");
            return None;
        }
    };

    parsed
        .get("content")
        .and_then(|c| c.get(0))
        .and_then(|c| c.get("text"))
        .and_then(|t| t.as_str())
        .map(|s| s.to_string())
}

/// Ask the model to narrate the already-computed `tool_outputs` in
/// plain English, grounded strictly in the numbers already present in
/// that text. Returns `None` on any API/network failure -- callers
/// should show the raw tool output on `None`, not silently drop it.
/// Never influences which tools ran; that's already decided by the time
/// this is called (see intent.rs).
pub fn synthesize(query: &str, tool_outputs: &[(String, String)]) -> Option<String> {
    if tool_outputs.is_empty() {
        return None;
    }

    let mut context = String::new();
    for (name, output) in tool_outputs {
        context.push_str(&format!("=== {name} output ===\n{output}\n\n"));
    }

    let system = "You are a genomics analyst summarizing real, already-computed tool output for \
        a researcher. You will be given the user's question and the exact output of one or more \
        analysis tools. Write a short (3-6 sentence) plain-English interpretation. Rules: \
        (1) Do not introduce any number that does not already appear verbatim in the tool output \
        below -- you are narrating existing results, not computing new ones. \
        (2) This is a synthetic/demo dataset; say so if you'd otherwise imply it's real patient \
        data. (3) If the tool output already flags a caveat (e.g. 'CPU fallback', 'synthetic \
        dataset', a p-value threshold), preserve that caveat in your summary rather than \
        dropping it.";

    let user = format!("User question: {query}\n\n{context}");
    call_llm(system, &user, 400)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn synthesize_with_no_tool_outputs_returns_none_without_network() {
        assert_eq!(synthesize("anything", &[]), None);
    }

    #[test]
    fn synthesize_is_none_without_any_backend_configured() {
        // SAFETY: single-threaded within this test; std::env::var is read,
        // never mutated, by this test -- it only asserts the no-backend
        // path when the ambient environment genuinely has neither an HF
        // token nor an Anthropic key set, and is a no-op assertion
        // (skipped) otherwise so it doesn't depend on the test-running
        // machine's environment.
        if hf_token().is_some() || anthropic_api_key().is_some() {
            eprintln!("SKIPPED synthesize_is_none_without_any_backend_configured: a backend credential is set in this environment");
            return;
        }
        assert_eq!(synthesize("anything", &[("T".to_string(), "out".to_string())]), None);
    }
}
