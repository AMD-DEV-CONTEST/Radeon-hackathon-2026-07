use crate::diagnostics;
use crate::memory;
use crate::prompts;
use crate::tools;
use crate::translator::{self, FailureType, Message};
use crate::{AppState, SendResponse};
use tracing::{info, warn};

const MAX_TOOL_ROUNDS: u32 = u32::MAX;

// ── Corrector endpoint cascade ───────────────────────────────────────────────
// Try each in order until one responds. This lets the P1000 TinyLlama act as
// a fallback corrector when Marvin (14B on 1070) is offline.
const CORRECTOR_CASCADE: &[(&str, &str)] = &[
    ("marvin-14b",   "http://100.102.158.111:5555"),  // 14B on GTX 1070 — primary
    ("picasso-tiny", "http://100.102.158.111:5571"),  // TinyLlama on P1000 — fallback
    ("laptop-tiny",  "http://100.110.214.86:5571"),   // M2200 on ThinkPad — tertiary
];

// ── "Close enough" thresholds ────────────────────────────────────────────────
// If a code block is this close to compilable, finish it ourselves.
const CLOSE_ENOUGH_MISSING_BRACES: i32 = 3;   // ≤3 unmatched braces
const CLOSE_ENOUGH_MISSING_LINES: usize = 15; // ≤15 lines of obvious boilerplate missing

/// Result of the corrector's repetition justification check.
struct RepetitionJudgment {
    allowed: bool,
    reason: String,
}

/// Read tuning params from cluster_config.toml
fn read_tuning() -> (u32, u64, u64, u32, f32, bool) {
    let config_path = "/codebase/repos/wreckhunter2000-1/cesarops-forge-v2/cluster_config.toml";
    let content = std::fs::read_to_string(config_path).unwrap_or_default();
    let table: toml::Table = content.parse().unwrap_or_default();
    
    let tuning = table.get("tuning");
    let max_think = tuning.and_then(|t| t.get("max_think_rounds")).and_then(|v| v.as_integer()).unwrap_or(20) as u32;
    let gen_timeout = tuning.and_then(|t| t.get("generation_timeout_secs")).and_then(|v| v.as_integer()).unwrap_or(600) as u64;
    let thinker_timeout = tuning.and_then(|t| t.get("thinker_timeout_secs")).and_then(|v| v.as_integer()).unwrap_or(60) as u64;
    let max_tokens = tuning.and_then(|t| t.get("max_generation_tokens")).and_then(|v| v.as_integer()).unwrap_or(12288) as u32;
    let temperature = tuning.and_then(|t| t.get("temperature")).and_then(|v| v.as_float()).unwrap_or(0.4) as f32;
    let skip_corrector = tuning.and_then(|t| t.get("skip_corrector")).and_then(|v| v.as_bool()).unwrap_or(false);
    
    (max_think, gen_timeout, thinker_timeout, max_tokens, temperature, skip_corrector)
}

/// Main orchestration loop: Strategy → Execution → Verification.
pub async fn run(state: &AppState, user_message: &str) -> SendResponse {
    let fast_mode = user_message.starts_with("/fast");
    let message = if fast_mode {
        user_message.trim_start_matches("/fast").trim()
    } else {
        user_message
    };

    // --- Layer 1: Thinker pre-flight (skip with /fast) ---
    let thinker_context = if !fast_mode {
        get_thinker_preflight(message, state).await
    } else {
        String::new()
    };

    // Add user message to conversation
    {
        let mut conv = state.conversation.lock().await;
        conv.push(Message {
            role: "user".to_string(),
            content: message.to_string(),
        });
    }

    // --- Layer 3: Execute generation loop ---
    let mut tool_actions: Vec<String> = Vec::new();
    let mut output_history: Vec<String> = Vec::new();
    let mut failure_count: u32 = 0;
    let mut diagnosis_info: Option<String> = None;
    let (max_diagnosis, _gen_timeout, _thinker_timeout, _max_tokens, start_temp, skip_corrector) = read_tuning();
    let mut temperature = start_temp;

    for round in 1..=MAX_TOOL_ROUNDS {
        // Check interrupt flag
        if state.interrupt.load(std::sync::atomic::Ordering::Relaxed) {
            info!("INTERRUPTED at round {}", round);
            state.interrupt.store(false, std::sync::atomic::Ordering::Relaxed);
            return SendResponse {
                response: "[INTERRUPTED by user]".to_string(),
                tool_actions,
                diagnosis: diagnosis_info,
            };
        }

        // Check for steering messages injected between rounds
        {
            let mut steering = state.steering.lock().await;
            if !steering.is_empty() {
                let mut conv = state.conversation.lock().await;
                for msg in steering.drain(..) {
                    info!("Injecting steering: {}", &msg[..msg.len().min(60)]);
                    conv.push(Message {
                        role: "user".to_string(),
                        content: format!("[STEERING FROM OPERATOR]: {}", msg),
                    });
                }
            }
        }

        // Build prompt from conversation state
        let prompt = build_prompt(state, &thinker_context, failure_count).await;

        // Generate from 35B
        let raw_output = generate_35b(&prompt, temperature, state).await;

        // --- Layer 2: Translator normalizes output ---
        let normalized = translator::normalize(&raw_output);

        // Loop detection
        if translator::detect_output_loop(&output_history, &raw_output) {
            warn!("Loop detected at round {}", round);
            // Hard reset recent history
            hard_reset(state).await;
            failure_count += 1;
            temperature = (temperature + 0.15).min(1.0);
            continue;
        }
        output_history.push(raw_output.clone());

        // Handle failure states
        if let Some(ref failure_type) = normalized.failure {
            warn!("Failure detected: {:?} at round {}", failure_type, round);

            // --- MalformedToolCall: Route to corrector cascade ---
            if matches!(failure_type, FailureType::MalformedToolCall) {
                if skip_corrector {
                    info!("Corrector disabled (skip_corrector=true). Treating as parse failure.");
                    failure_count += 1;
                    temperature = (temperature + 0.1).min(1.0);
                    continue;
                }
                info!("Routing malformed tool call to corrector cascade");
                let corrected = correct_and_execute_cascade(&raw_output, &normalized.content, state).await;
                
                if let Some((tool_name, result, correction_note, corrector_id)) = corrected {
                    tool_actions.push(format!("{}(corrected-by:{})", tool_name, corrector_id));
                    
                    let feedback = format!(
                        "{}\n\n[CORRECTION by {}]: {}\nPattern: {{\"name\": \"TOOL_NAME\", \"arguments\": {{\"key\": \"value\"}}}}",
                        result, corrector_id, correction_note
                    );
                    let formatted = translator::format_tool_result_for_qwen(&feedback, round, MAX_TOOL_ROUNDS);
                    
                    let mut conv = state.conversation.lock().await;
                    conv.push(Message { role: "assistant".to_string(), content: normalized.content.clone() });
                    conv.push(Message { role: "user".to_string(), content: formatted });
                    
                    let remember_args = serde_json::json!({
                        "content": format!("Correct tool call format: {{\"name\": \"{}\", \"arguments\": {{...}}}}. Fixed by {}.", tool_name, corrector_id),
                        "tags": "tool_call,format_fix,corrector"
                    });
                    let _ = tools::execute("remember", &remember_args, state).await;
                    continue;
                }
                // Corrector cascade exhausted — fall through to diagnostics
            }

            if failure_count >= max_diagnosis {
                // Give up — return whatever we have
                let response = if normalized.content.is_empty() {
                    format!("[Model stuck after {} attempts. Last failure: {:?}]", failure_count, failure_type)
                } else {
                    normalized.content
                };

                return SendResponse {
                    response,
                    tool_actions,
                    diagnosis: diagnosis_info,
                };
            }

            // --- Layer 4: Diagnostic ---
            let prompt_tail = get_prompt_tail(state).await;
            let diag = diagnostics::diagnose(
                &prompt_tail,
                &raw_output,
                failure_type,
                state,
            )
            .await;

            if let Some(ref diagnosis) = diag {
                diagnosis_info = Some(diagnosis.explanation.clone());
                info!("Diagnosis: {} (confidence: {:.2})", diagnosis.explanation, diagnosis.confidence);

                // Apply prompt override if provided
                if let Some(ref override_text) = diagnosis.prompt_override {
                    let mut conv = state.conversation.lock().await;
                    conv.push(Message {
                        role: "user".to_string(),
                        content: format!("[System correction]: {}", override_text),
                    });
                }

                // Temperature spike on failure
                temperature = (temperature + 0.15).min(0.9);
            }

            failure_count += 1;
            continue;
        }

        // --- Tool call handling ---
        if let Some(ref tool_call) = normalized.tool_call {
            info!("Tool call round {}: {}", round, tool_call.name);
            tool_actions.push(tool_call.name.clone());

            // Check for repeated tool calls — ask corrector cascade to judge
            if tool_actions.len() >= 3 {
                let last_three = &tool_actions[tool_actions.len() - 3..];
                if last_three.iter().all(|a| a.trim_end_matches(|c: char| !c.is_alphabetic()) == tool_call.name.as_str()
                    || a == &tool_call.name) {
                    let repeat_count = tool_actions.iter().rev()
                        .take_while(|a| a.starts_with(&tool_call.name))
                        .count();

                    if repeat_count >= 3 {
                        // Ask corrector cascade whether this repetition is justified
                        let judgment = check_repetition_justification_cascade(
                            &tool_call.name, &tool_actions, &output_history, state
                        ).await;

                        if !judgment.allowed {
                            warn!("Corrector BLOCKED repeated '{}': {}", tool_call.name, judgment.reason);
                            let mut conv = state.conversation.lock().await;
                            conv.push(Message {
                                role: "user".to_string(),
                                content: format!(
                                    "[LOOP BLOCKED by corrector]: '{}' called {} times. Reason: {}. \
                                     You MUST either use a DIFFERENT tool or provide your FINAL ANSWER now. \
                                     No more '{}' calls.",
                                    tool_call.name, repeat_count, judgment.reason, tool_call.name
                                ),
                            });
                            failure_count += 1;
                            continue;
                        } else if repeat_count >= 5 {
                            // Hard cap regardless of corrector judgment
                            warn!("Hard cap: '{}' called {} times, terminating loop", tool_call.name, repeat_count);
                            let mut conv = state.conversation.lock().await;
                            conv.push(Message {
                                role: "user".to_string(),
                                content: format!(
                                    "[TERMINATED]: '{}' repeated {} times. Provide your answer in plain text NOW.",
                                    tool_call.name, repeat_count
                                ),
                            });
                            continue;
                        } else {
                            info!("Corrector ALLOWED repeated '{}' ({}x): {}", tool_call.name, repeat_count, judgment.reason);
                        }
                    }
                }
            }

            // Execute the tool
            let result = tools::execute(&tool_call.name, &tool_call.arguments, state).await;

            // ── "Close enough" detection ─────────────────────────────────────
            // If the model just wrote a code file that's nearly complete (compile
            // errors are minor / missing closing braces), finish it ourselves and
            // queue a WIP commit rather than burning another full round.
            if tool_call.name == "write_file" {
                if let Some(content) = tool_call.arguments.get("content").and_then(|v| v.as_str()) {
                    if let Some(path) = tool_call.arguments.get("path").and_then(|v| v.as_str()) {
                        if path.ends_with(".rs") || path.ends_with(".wgsl") || path.ends_with(".toml") {
                            if let Some(fix) = assess_close_enough(content, path) {
                                info!("Close-enough detected for '{}': {}", path, fix.description);
                                // Apply the fix ourselves
                                if let Some(fixed_content) = &fix.fixed_content {
                                    let write_args = serde_json::json!({
                                        "path": path,
                                        "content": fixed_content
                                    });
                                    let _ = tools::execute("write_file", &write_args, state).await;
                                    tool_actions.push(format!("write_file(close-enough-fix:{})", path));
                                    info!("Applied close-enough fix to '{}': {}", path, fix.description);
                                }
                                // Queue next round with targeted context
                                let next_round_msg = format!(
                                    "[CLOSE-ENOUGH AUTO-FIX]: '{}' was nearly complete. Applied fix: {}. \
                                     Next step: run cargo_check on the project to verify it compiles, \
                                     then commit with a WIP message. If cargo_check passes, \
                                     call run_command with: git add {} && git commit -m 'WIP: {}'",
                                    path, fix.description, path,
                                    path.split('/').last().unwrap_or(path)
                                );
                                let mut conv = state.conversation.lock().await;
                                conv.push(Message { role: "assistant".to_string(), content: normalized.content.clone() });
                                conv.push(Message { role: "user".to_string(), content: next_round_msg });
                                continue;
                            }
                        }
                    }
                }
            }

            // --- Context Window Management ---
            // If the result is large, compress it for conversation and store full in nautivecs
            let (conv_result, stored_full) = compress_tool_result(&tool_call.name, &tool_call.arguments, &result, state).await;

            // Format result as user message (QwenChatML format)
            let formatted = translator::format_tool_result_for_qwen(&conv_result, round, MAX_TOOL_ROUNDS);

            // Trim old conversation to keep context lean (keep system + last 6 exchanges)
            let mut conv = state.conversation.lock().await;
            trim_conversation(&mut conv, 12); // keep last 12 messages (6 exchanges)

            conv.push(Message {
                role: "assistant".to_string(),
                content: normalized.content.clone(),
            });
            conv.push(Message {
                role: "user".to_string(),
                content: formatted,
            });

            // If diagnosis was used and this succeeded, auto-remember
            if failure_count > 0 {
                if let Some(ref diag) = diagnosis_info {
                    let diag_result = diagnostics::DiagnosisResult {
                        explanation: diag.clone(),
                        prompt_override: None,
                        confidence: 0.8,
                    };
                    let ft = FailureType::ThinkOnly; // approximate
                    memory::auto_remember_success(&diag_result, &ft, "qwen3.6-35b", state).await;
                }
                failure_count = 0; // Reset on success
            }

            continue;
        }

        // --- Plain text response (no tool call, no failure) ---
        // Add to conversation and return
        {
            let mut conv = state.conversation.lock().await;
            conv.push(Message {
                role: "assistant".to_string(),
                content: normalized.content.clone(),
            });
        }

        // Auto-remember success after diagnosis recovery
        if failure_count > 0 {
            if let Some(ref diag) = diagnosis_info {
                let diag_result = diagnostics::DiagnosisResult {
                    explanation: diag.clone(),
                    prompt_override: None,
                    confidence: 0.8,
                };
                let ft = FailureType::ThinkOnly;
                memory::auto_remember_success(&diag_result, &ft, "qwen3.6-35b", state).await;
            }
        }

        return SendResponse {
            response: normalized.content,
            tool_actions,
            diagnosis: diagnosis_info,
        };
    }

    // Exhausted all rounds
    SendResponse {
        response: format!("[Exhausted {} tool rounds. Last actions: {:?}]", MAX_TOOL_ROUNDS, tool_actions),
        tool_actions,
        diagnosis: diagnosis_info,
    }
}

/// Call the 8B thinker for pre-flight reasoning.
async fn get_thinker_preflight(message: &str, state: &AppState) -> String {
    let prompt = prompts::thinker_prompt(message);
    let client = reqwest::Client::new();

    let payload = serde_json::json!({
        "prompt": prompt,
        "max_length": 900,
        "temperature": 0.5,
        "top_p": 0.9,
        "stop_sequence": ["<|im_end|>"],
    });

    let resp = client
        .post(format!("{}/api/v1/generate", state.config.thinker_url))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(90))
        .send()
        .await;

    match resp {
        Ok(r) => {
            if let Ok(body) = r.json::<serde_json::Value>().await {
                body.get("results")
                    .and_then(|r| r.as_array())
                    .and_then(|a| a.first())
                    .and_then(|r| r.get("text"))
                    .and_then(|t| t.as_str())
                    .unwrap_or("")
                    .to_string()
            } else {
                String::new()
            }
        }
        Err(e) => {
            warn!("Thinker preflight failed: {}", e);
            String::new()
        }
    }
}

/// Build the full prompt from conversation state.
async fn build_prompt(state: &AppState, thinker_context: &str, failure_count: u32) -> String {
    let conv = state.conversation.lock().await;

    let system = format!(
        "{}{}{}",
        prompts::system_prompt(),
        if !thinker_context.is_empty() {
            prompts::format_thinker_context(thinker_context)
        } else {
            String::new()
        },
        prompts::snark_nudge(failure_count),
    );

    let messages: Vec<(String, String)> = conv
        .iter()
        .map(|m| (m.role.clone(), m.content.clone()))
        .collect();

    prompts::format_chatml(&system, &messages, true)
}

/// Generate from the 35B via KoboldCPP.
async fn generate_35b(prompt: &str, temperature: f32, state: &AppState) -> String {
    let client = reqwest::Client::new();

    // Fresh token budget every call — context is trimmed between rounds
    // so we always have room for a full generation
    let payload = serde_json::json!({
        "prompt": prompt,
        "max_length": 16384,
        "temperature": temperature,
        "top_p": 0.95,
        "rep_pen": 1.1,
        "stop_sequence": ["</tool_call>", "<|endoftext|>"],
    });

    let resp = client
        .post(format!("{}/api/v1/generate", state.config.coder_url))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(600))
        .send()
        .await;

    match resp {
        Ok(r) => {
            if let Ok(body) = r.json::<serde_json::Value>().await {
                let text = body
                    .get("results")
                    .and_then(|r| r.as_array())
                    .and_then(|a| a.first())
                    .and_then(|r| r.get("text"))
                    .and_then(|t| t.as_str())
                    .unwrap_or("");

                // If stopped at </tool_call>, re-append it so the parser can find it
                if !text.contains("</tool_call>") && text.contains("<tool_call>") {
                    format!("{}</tool_call>", text)
                } else {
                    text.to_string()
                }
            } else {
                String::new()
            }
        }
        Err(e) => {
            warn!("35B generation failed: {}", e);
            String::new()
        }
    }
}

/// Get the tail of the prompt for diagnostic context.
async fn get_prompt_tail(state: &AppState) -> String {
    let conv = state.conversation.lock().await;
    let tail: Vec<String> = conv
        .iter()
        .rev()
        .take(3)
        .map(|m| format!("[{}]: {}", m.role, &m.content[..m.content.len().min(200)]))
        .collect();
    tail.join("\n")
}

/// Hard reset: clear recent conversation history (keep system + first user message).
async fn hard_reset(state: &AppState) {
    let mut conv = state.conversation.lock().await;
    if conv.len() > 2 {
        // Keep only the last user message
        let last_user = conv
            .iter()
            .rev()
            .find(|m| m.role == "user")
            .cloned();
        conv.clear();
        if let Some(msg) = last_user {
            conv.push(msg);
        }
    }
    info!("Hard reset: conversation cleared to last user message");
}

/// Route a malformed tool call through the corrector cascade.
/// Tries each corrector in order until one fixes it.
/// Returns (tool_name, result, correction_note, corrector_id) or None.
async fn correct_and_execute_cascade(
    raw_output: &str,
    stripped_content: &str,
    state: &AppState,
) -> Option<(String, String, String, String)> {
    // Build the corrector URL list: config corrector first, then cascade fallbacks
    let mut endpoints: Vec<(String, String)> = Vec::new();

    // Primary from config (may be disabled/empty)
    let primary = &state.config.corrector_url;
    if !primary.is_empty() && !primary.contains("0.0.0.0") {
        endpoints.push(("config-corrector".to_string(), primary.clone()));
    }

    // Cascade fallbacks
    for (id, url) in CORRECTOR_CASCADE {
        if !endpoints.iter().any(|(_, u)| u == url) {
            endpoints.push((id.to_string(), url.to_string()));
        }
    }

    for (corrector_id, corrector_url) in &endpoints {
        info!("Trying corrector '{}' at {}", corrector_id, corrector_url);
        if let Some(result) = try_corrector(raw_output, stripped_content, corrector_url, corrector_id, state).await {
            return Some(result);
        }
        warn!("Corrector '{}' failed or unreachable, trying next", corrector_id);
    }

    warn!("All correctors exhausted — cannot fix malformed tool call");
    None
}

/// Try a single corrector endpoint. Returns None if unreachable or can't fix.
async fn try_corrector(
    raw_output: &str,
    stripped_content: &str,
    corrector_url: &str,
    corrector_id: &str,
    state: &AppState,
) -> Option<(String, String, String, String)> {
    let client = reqwest::Client::new();

    // Smaller models need a simpler, more direct prompt
    let is_tiny = corrector_id.contains("tiny") || corrector_id.contains("picasso") || corrector_id.contains("laptop");
    let max_length = if is_tiny { 200 } else { 600 };

    let fix_prompt = if is_tiny {
        // TinyLlama / small model — ultra-minimal prompt
        format!(
            "Fix this JSON tool call. Output ONLY valid JSON, nothing else.\n\
             Format: {{\"name\": \"tool_name\", \"arguments\": {{\"key\": \"value\"}}}}\n\
             Tools: write_file, read_file, cargo_check, think_harder, remember, run_command\n\
             Input: {}\nFixed JSON:",
            &stripped_content[..stripped_content.len().min(300)]
        )
    } else {
        // Full corrector prompt for 14B+
        format!(
            r#"<|im_start|>system
You are a tool-call JSON fixer. Output ONLY the corrected JSON. Nothing else.
Format: {{"name": "tool_name", "arguments": {{"key": "value"}}}}
Tools: write_file, read_file, cargo_check, think_harder, remember, run_command, speed_check
<|im_end|>
<|im_start|>user
Fix: {}
<|im_end|>
<|im_start|>assistant
"#,
            stripped_content
        )
    };

    let payload = serde_json::json!({
        "prompt": fix_prompt,
        "max_length": max_length,
        "temperature": 0.05,
        "top_p": 0.9,
        "stop_sequence": if is_tiny { vec!["\n\n", "```"] } else { vec!["<|im_end|>", "\n\n"] },
    });

    let resp = client
        .post(format!("{}/api/v1/generate", corrector_url))
        .json(&payload)
        .timeout(std::time::Duration::from_secs(if is_tiny { 20 } else { 60 }))
        .send()
        .await
        .ok()?;

    let body: serde_json::Value = resp.json().await.ok()?;
    let fixed_text = body
        .get("results")
        .and_then(|r| r.as_array())
        .and_then(|a| a.first())
        .and_then(|r| r.get("text"))
        .and_then(|t| t.as_str())
        .unwrap_or("");

    // Extract JSON from the response (may have surrounding text for small models)
    let json_text = extract_json_from_text(fixed_text);

    let normalized = translator::normalize(&json_text);
    if let Some(ref tool_call) = normalized.tool_call {
        info!("Corrector '{}' fixed tool call: {}", corrector_id, tool_call.name);
        let result = tools::execute(&tool_call.name, &tool_call.arguments, state).await;
        let correction_note = format!(
            "Your tool call JSON was malformed. Fixed by {}. \
             Correct format: {{\"name\": \"{}\", \"arguments\": {{...}}}}",
            corrector_id, tool_call.name
        );
        Some((tool_call.name.clone(), result, correction_note, corrector_id.to_string()))
    } else {
        None
    }
}

/// Extract the first JSON object from a string (handles small models that add surrounding text).
fn extract_json_from_text(text: &str) -> String {
    // Try to find { ... } pattern
    if let Some(start) = text.find('{') {
        let substr = &text[start..];
        let mut depth = 0i32;
        let mut end = 0;
        for (i, c) in substr.char_indices() {
            match c {
                '{' => depth += 1,
                '}' => {
                    depth -= 1;
                    if depth == 0 {
                        end = i + 1;
                        break;
                    }
                }
                _ => {}
            }
        }
        if end > 0 {
            return substr[..end].to_string();
        }
    }
    text.to_string()
}

/// Ask the corrector cascade whether a repeated tool call is justified.
async fn check_repetition_justification_cascade(
    tool_name: &str,
    tool_history: &[String],
    output_history: &[String],
    state: &AppState,
) -> RepetitionJudgment {
    let recent_outputs = output_history.iter().rev().take(2)
        .map(|s| s.chars().take(150).collect::<String>())
        .collect::<Vec<_>>()
        .join("\n---\n");
    let recent_tools = tool_history.iter().rev().take(5).cloned().collect::<Vec<_>>().join(", ");

    // Build endpoint list
    let mut endpoints: Vec<(String, String)> = Vec::new();
    let primary = &state.config.corrector_url;
    if !primary.is_empty() && !primary.contains("0.0.0.0") {
        endpoints.push(("config-corrector".to_string(), primary.clone()));
    }
    for (id, url) in CORRECTOR_CASCADE {
        if !endpoints.iter().any(|(_, u)| u == url) {
            endpoints.push((id.to_string(), url.to_string()));
        }
    }

    for (corrector_id, corrector_url) in &endpoints {
        let is_tiny = corrector_id.contains("tiny") || corrector_id.contains("picasso") || corrector_id.contains("laptop");

        let prompt = if is_tiny {
            format!(
                "Is calling '{}' again justified? Recent calls: [{}]. Recent output: {}...\n\
                 Answer ALLOW or BLOCK with one reason.",
                tool_name, recent_tools, &recent_outputs[..recent_outputs.len().min(100)]
            )
        } else {
            format!(
                r#"<|im_start|>system
Loop detection judge. Respond ONLY: ALLOW: <reason> or BLOCK: <reason>
<|im_end|>
<|im_start|>user
Tool repeated: "{}" | Recent: [{}]
Output: {}
Justified?<|im_end|>
<|im_start|>assistant
"#,
                tool_name, recent_tools, &recent_outputs[..recent_outputs.len().min(150)]
            )
        };

        let client = reqwest::Client::new();
        let payload = serde_json::json!({
            "prompt": prompt,
            "max_length": 60,
            "temperature": 0.1,
            "stop_sequence": ["\n\n", "<|im_end|>"],
        });

        let resp = client
            .post(format!("{}/api/v1/generate", corrector_url))
            .json(&payload)
            .timeout(std::time::Duration::from_secs(10))
            .send()
            .await;

        if let Ok(r) = resp {
            if let Ok(body) = r.json::<serde_json::Value>().await {
                let text = body.get("results")
                    .and_then(|r| r.as_array())
                    .and_then(|a| a.first())
                    .and_then(|r| r.get("text"))
                    .and_then(|t| t.as_str())
                    .unwrap_or("ALLOW: unavailable")
                    .trim()
                    .to_string();

                info!("Repetition judgment from '{}': {}", corrector_id, &text[..text.len().min(80)]);

                if text.to_uppercase().starts_with("BLOCK") {
                    let reason = text.splitn(2, ':').nth(1).unwrap_or(&text).trim().to_string();
                    return RepetitionJudgment { allowed: false, reason };
                } else {
                    let reason = text.splitn(2, ':').nth(1).unwrap_or(&text).trim().to_string();
                    return RepetitionJudgment { allowed: true, reason };
                }
            }
        }
        // This corrector failed, try next
    }

    // All correctors unreachable — allow by default
    RepetitionJudgment { allowed: true, reason: "all correctors unreachable".to_string() }
}

/// Assessment of whether a code file is "close enough" to complete.
struct CloseEnoughFix {
    description: String,
    fixed_content: Option<String>,
}

/// Check if a code file is close enough to complete that we should fix it ourselves.
/// Returns Some(fix) if we can patch it, None if it needs a full round.
fn assess_close_enough(content: &str, path: &str) -> Option<CloseEnoughFix> {
    if path.ends_with(".rs") {
        return assess_rust_close_enough(content);
    }
    if path.ends_with(".wgsl") {
        return assess_wgsl_close_enough(content);
    }
    None
}

fn assess_rust_close_enough(content: &str) -> Option<CloseEnoughFix> {
    // Count unmatched braces
    let open = content.chars().filter(|&c| c == '{').count() as i32;
    let close = content.chars().filter(|&c| c == '}').count() as i32;
    let brace_diff = open - close;

    // Check for truncated function (ends mid-function without closing)
    let ends_cleanly = content.trim_end().ends_with('}')
        || content.trim_end().ends_with("};")
        || content.trim_end().ends_with(")\n}");

    if brace_diff > 0 && brace_diff <= CLOSE_ENOUGH_MISSING_BRACES && !ends_cleanly {
        // Missing closing braces — append them
        let mut fixed = content.to_string();
        // Add a newline if needed
        if !fixed.ends_with('\n') { fixed.push('\n'); }
        for _ in 0..brace_diff {
            fixed.push_str("}\n");
        }
        return Some(CloseEnoughFix {
            description: format!("appended {} missing closing braces", brace_diff),
            fixed_content: Some(fixed),
        });
    }

    // Check for file that ends with a comment or doc string (truncated mid-write)
    let trimmed = content.trim_end();
    if trimmed.ends_with("//") || trimmed.ends_with("///") || trimmed.ends_with("/*") {
        // Truncated comment — remove it and close
        let without_comment = trimmed.trim_end_matches('/').trim_end_matches('*').trim_end();
        let mut fixed = without_comment.to_string();
        if !fixed.ends_with('\n') { fixed.push('\n'); }
        // Close any open braces
        let open2 = fixed.chars().filter(|&c| c == '{').count() as i32;
        let close2 = fixed.chars().filter(|&c| c == '}').count() as i32;
        for _ in 0..(open2 - close2).max(0) {
            fixed.push_str("}\n");
        }
        return Some(CloseEnoughFix {
            description: "removed truncated comment and closed open braces".to_string(),
            fixed_content: Some(fixed),
        });
    }

    None
}

fn assess_wgsl_close_enough(content: &str) -> Option<CloseEnoughFix> {
    let open = content.chars().filter(|&c| c == '{').count() as i32;
    let close = content.chars().filter(|&c| c == '}').count() as i32;
    let diff = open - close;

    if diff > 0 && diff <= CLOSE_ENOUGH_MISSING_BRACES {
        let mut fixed = content.to_string();
        if !fixed.ends_with('\n') { fixed.push('\n'); }
        for _ in 0..diff {
            fixed.push_str("}\n");
        }
        return Some(CloseEnoughFix {
            description: format!("appended {} missing WGSL closing braces", diff),
            fixed_content: Some(fixed),
        });
    }
    None
}

/// Keep the old single-corrector function for backward compat (now delegates to cascade).
async fn correct_and_execute(
    raw_output: &str,
    stripped_content: &str,
    state: &AppState,
) -> Option<(String, String, String)> {
    correct_and_execute_cascade(raw_output, stripped_content, state)
        .await
        .map(|(name, result, note, _id)| (name, result, note))
}

/// Compress a tool result for conversation context.
/// If the result is large (>800 chars), store the full version in nautivecs
/// and return a compressed summary for the conversation.
/// This keeps the context window lean across many tool rounds.
async fn compress_tool_result(
    tool_name: &str,
    args: &serde_json::Value,
    full_result: &str,
    state: &AppState,
) -> (String, bool) {
    const COMPRESS_THRESHOLD: usize = 800;

    if full_result.len() <= COMPRESS_THRESHOLD {
        return (full_result.to_string(), false);
    }

    // Build a compressed summary: first 400 chars + last 200 chars + metadata
    let first = &full_result[..400.min(full_result.len())];
    let last_start = full_result.len().saturating_sub(200);
    let last = &full_result[last_start..];
    let lines = full_result.lines().count();

    let summary = format!(
        "[COMPRESSED — full result stored in memory, use think_harder to recall]\n\
         Tool: {}({})\n\
         Size: {} chars, {} lines\n\
         Preview: {}...\n\
         ...tail: {}",
        tool_name,
        args.get("path").or(args.get("query")).or(args.get("cmd"))
            .and_then(|v| v.as_str()).unwrap_or(""),
        full_result.len(),
        lines,
        first.trim(),
        last.trim(),
    );

    // Store full result in nautivecs for later retrieval via think_harder
    let remember_content = format!(
        "Tool result from {}({}): {}", 
        tool_name,
        args.get("path").or(args.get("query")).or(args.get("cmd"))
            .and_then(|v| v.as_str()).unwrap_or(""),
        &full_result[..full_result.len().min(3000)]
    );
    let remember_args = serde_json::json!({
        "content": remember_content,
        "tags": format!("tool_result,{},context_overflow", tool_name)
    });
    let _ = tools::execute("remember", &remember_args, state).await;

    (summary, true)
}

/// Trim conversation to keep only the first message (system/task) and the last N messages.
/// This prevents unbounded context growth across many tool rounds.
fn trim_conversation(conv: &mut Vec<Message>, keep_last: usize) {
    if conv.len() <= keep_last + 1 {
        return; // Nothing to trim
    }

    // Keep first message (the original user task) + last N messages
    let first = conv[0].clone();
    let tail: Vec<Message> = conv.iter().rev().take(keep_last).cloned().collect::<Vec<_>>().into_iter().rev().collect();

    conv.clear();
    conv.push(first);

    // Add a context note so the model knows history was trimmed
    conv.push(Message {
        role: "user".to_string(),
        content: format!(
            "[CONTEXT NOTE: {} earlier messages were compressed and stored in memory. \
             Use think_harder to recall previous tool results if needed. \
             Continue working on the original task.]",
            tail.len()
        ),
    });

    conv.extend(tail);
}
