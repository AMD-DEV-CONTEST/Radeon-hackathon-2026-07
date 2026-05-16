use crate::AppState;
use crate::validator::{ValidatorConfig, run_validation, benchmark_tps, ping};
use serde_json::Value;
use std::path::PathBuf;
use std::sync::atomic::{AtomicU32, Ordering};
use tokio::process::Command;
use tracing::{info, warn};

/// Counter for think_harder calls per session. Resets on /clear.
static THINK_HARDER_COUNT: AtomicU32 = AtomicU32::new(0);
const THINK_HARDER_LIMIT: u32 = u32::MAX; // No limit — let it search as much as it needs

/// Reset the think_harder counter (called on /clear).
pub fn reset_think_counter() {
    THINK_HARDER_COUNT.store(0, Ordering::Relaxed);
}

/// Execute a tool by name with the given arguments. Returns the tool result as a string.
pub async fn execute(name: &str, arguments: &Value, state: &AppState) -> String {
    info!("Tool call: {} args={}", name, arguments);

    match name {
        "write_file" => { reset_think_counter(); write_file(arguments, state).await },
        "read_file" => { reset_think_counter(); read_file(arguments, state).await },
        "cargo_check" => { reset_think_counter(); cargo_check(arguments, state).await },
        "think_harder" => {
            let _count = THINK_HARDER_COUNT.fetch_add(1, Ordering::Relaxed) + 1;
            let result = think_harder(arguments, state).await;
            result
        },
        "remember" => { reset_think_counter(); remember(arguments, state).await },
        "run_command" => { reset_think_counter(); run_command(arguments, state).await },
        "speed_check" => { speed_check(arguments, state).await },
        _ => format!("Unknown tool: '{}'. Available: write_file, read_file, cargo_check, think_harder, remember, run_command, speed_check", name),
    }
}

/// Write content to a file under project_root.
async fn write_file(args: &Value, state: &AppState) -> String {
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) => p,
        None => return "Error: 'path' argument required".to_string(),
    };
    let content = match args.get("content").and_then(|v| v.as_str()) {
        Some(c) => c,
        None => return "Error: 'content' argument required".to_string(),
    };

    let full_path = resolve_path(path, state);

    // Create parent directories
    if let Some(parent) = full_path.parent() {
        if let Err(e) = tokio::fs::create_dir_all(parent).await {
            return format!("Error creating directories: {}", e);
        }
    }

    match tokio::fs::write(&full_path, content).await {
        Ok(_) => format!("Written {} bytes to {}", content.len(), path),
        Err(e) => format!("Error writing file: {}", e),
    }
}

/// Read a file, truncating at 3000 chars.
async fn read_file(args: &Value, state: &AppState) -> String {
    let path = match args.get("path").and_then(|v| v.as_str()) {
        Some(p) => p,
        None => return "Error: 'path' argument required".to_string(),
    };

    let full_path = resolve_path(path, state);

    match tokio::fs::read_to_string(&full_path).await {
        Ok(content) => {
            if content.len() > 3000 {
                format!("{}...\n[truncated at 3000 chars, total {} bytes]", &content[..3000], content.len())
            } else {
                content
            }
        }
        Err(e) => format!("Error reading file: {}", e),
    }
}

/// Run cargo check with --message-format=json, parse errors.
async fn cargo_check(args: &Value, state: &AppState) -> String {
    let dir = args
        .get("dir")
        .and_then(|v| v.as_str())
        .unwrap_or(".");

    let full_dir = resolve_path(dir, state);

    let output = match Command::new("cargo")
        .args(["check", "--message-format=json"])
        .current_dir(&full_dir)
        .output()
        .await
    {
        Ok(o) => o,
        Err(e) => return format!("Error running cargo check: {}", e),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    // Extract compiler errors from JSON lines
    let mut errors: Vec<String> = Vec::new();
    for line in stdout.lines() {
        if let Ok(msg) = serde_json::from_str::<Value>(line) {
            if msg.get("reason").and_then(|r| r.as_str()) == Some("compiler-message") {
                if let Some(message) = msg.get("message") {
                    let level = message.get("level").and_then(|l| l.as_str()).unwrap_or("");
                    let text = message.get("message").and_then(|m| m.as_str()).unwrap_or("");
                    if level == "error" {
                        errors.push(text.to_string());
                    }
                }
            }
        }
    }

    if errors.is_empty() && output.status.success() {
        "cargo check: OK (no errors)".to_string()
    } else if errors.is_empty() {
        // Fallback to stderr
        let truncated = truncate_output(&stderr, 2000);
        format!("cargo check FAILED:\n{}", truncated)
    } else {
        let error_list = errors.iter().take(10).cloned().collect::<Vec<_>>().join("\n- ");
        format!("cargo check: {} error(s):\n- {}", errors.len(), error_list)
    }
}

/// Search nautivecs + WSO for information.
async fn think_harder(args: &Value, state: &AppState) -> String {
    let query = match args.get("query").and_then(|v| v.as_str()) {
        Some(q) => q,
        None => return "Error: 'query' argument required".to_string(),
    };

    let client = reqwest::Client::new();
    let mut results = Vec::new();

    // Query nautivecs
    let nautivecs_result = client
        .post(&state.config.nautivecs_url)
        .json(&serde_json::json!({"query": query, "top_k": 3}))
        .send()
        .await;

    match nautivecs_result {
        Ok(resp) => {
            if let Ok(body) = resp.text().await {
                let truncated = truncate_output(&body, 1500);
                results.push(format!("[nautivecs]: {}", truncated));
            }
        }
        Err(e) => {
            warn!("nautivecs query failed: {}", e);
            results.push(format!("[nautivecs]: unavailable ({})", e));
        }
    }

    // Query WSO (web search)
    let wso_result = client
        .post(&state.config.wso_url)
        .json(&serde_json::json!({"query": query, "max_results": 3}))
        .send()
        .await;

    match wso_result {
        Ok(resp) => {
            if let Ok(body) = resp.text().await {
                let truncated = truncate_output(&body, 1500);
                results.push(format!("[web search]: {}", truncated));
            }
        }
        Err(e) => {
            warn!("WSO query failed: {}", e);
            results.push(format!("[web search]: unavailable ({})", e));
        }
    }

    if results.is_empty() {
        "No results from knowledge base or web search.".to_string()
    } else {
        results.join("\n\n")
    }
}

/// Append a lesson to research_log/lessons_learned.md AND push to nautivecs vector DB.
/// This makes the lesson retrievable via think_harder on future prompts.
async fn remember(args: &Value, state: &AppState) -> String {
    let content = match args.get("content").and_then(|v| v.as_str()) {
        Some(c) => c,
        None => return "Error: 'content' argument required".to_string(),
    };
    let tags = args
        .get("tags")
        .and_then(|v| v.as_str())
        .unwrap_or("general");

    let log_path = resolve_path("research_log/lessons_learned.md", state);

    // Ensure directory exists
    if let Some(parent) = log_path.parent() {
        let _ = tokio::fs::create_dir_all(parent).await;
    }

    let entry = format!("\n## [{}] {}\n{}\n", tags, chrono_now(), content);

    // Write to markdown log
    let log_result = {
        let existing = tokio::fs::read_to_string(&log_path).await.unwrap_or_default();
        let new_content = format!("{}{}", existing, entry);
        tokio::fs::write(&log_path, new_content).await
    };

    // Push to nautivecs so think_harder can retrieve it
    // nautivecs /add endpoint: POST { "text": "...", "tags": "...", "source": "..." }
    let nautivecs_base = state.config.nautivecs_url
        .trim_end_matches("/query")
        .trim_end_matches("/search");
    let add_url = format!("{}/add", nautivecs_base);

    let client = reqwest::Client::new();
    let nautivecs_result = client
        .post(&add_url)
        .json(&serde_json::json!({
            "text": format!("[{}] {}", tags, content),
            "tags": tags,
            "source": "lessons_learned",
            "file_path": "research_log/lessons_learned.md",
        }))
        .timeout(std::time::Duration::from_secs(10))
        .send()
        .await;

    let nautivecs_status = match nautivecs_result {
        Ok(r) if r.status().is_success() => " + indexed in nautivecs".to_string(),
        Ok(r) => format!(" (nautivecs returned {})", r.status()),
        Err(e) => format!(" (nautivecs unavailable: {})", e),
    };

    match log_result {
        Ok(_) => format!(
            "Remembered (tags: {}){}: {}...",
            tags, nautivecs_status, &content[..content.len().min(80)]
        ),
        Err(e) => format!("Error writing memory: {}", e),
    }
}

/// Run a shell command with K-line guards.
async fn run_command(args: &Value, state: &AppState) -> String {
    let cmd = match args.get("cmd").and_then(|v| v.as_str()) {
        Some(c) => c,
        None => return "Error: 'cmd' argument required".to_string(),
    };

    // K-line guard: block dangerous commands
    let blocked = ["rm -rf /", "rm -rf /*", "dd if=", "mkfs", "> /dev/sd", "chmod 777 /"];
    for pattern in &blocked {
        if cmd.contains(pattern) {
            warn!("K-LINED command blocked: {}", cmd);
            return format!("BLOCKED: Command '{}' is K-lined (dangerous operation)", cmd);
        }
    }

    let output = match Command::new("bash")
        .args(["-c", cmd])
        .current_dir(&state.config.project_root)
        .output()
        .await
    {
        Ok(o) => o,
        Err(e) => return format!("Error executing command: {}", e),
    };

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    let mut result = String::new();
    if !stdout.is_empty() {
        result.push_str(&truncate_output(&stdout, 2000));
    }
    if !stderr.is_empty() {
        if !result.is_empty() {
            result.push_str("\n[stderr]: ");
        }
        result.push_str(&truncate_output(&stderr, 500));
    }

    if result.is_empty() {
        format!("Command completed (exit code: {})", output.status.code().unwrap_or(-1))
    } else {
        result
    }
}

/// Ad-hoc speed + accuracy check using the P1000 TinyLlama reference.
///
/// Fires the same prompt at both the main engine and the P1000 in parallel,
/// compares token agreement, and reports t/s for both.
///
/// Usage: speed_check { "prompt": "optional — defaults to a fixed benchmark prompt" }
async fn speed_check(args: &Value, state: &AppState) -> String {
    let prompt = args
        .get("prompt")
        .and_then(|v| v.as_str())
        .unwrap_or("The quick brown fox jumps over the lazy dog. In Rust, a vector is");

    let validator_url = &state.config.validator_url;

    // First check if P1000 is up
    if !ping(validator_url).await {
        // P1000 offline — just benchmark the main engine
        info!("P1000 validator offline, benchmarking main engine only");
        let main_tps = benchmark_tps(&state.config.coder_url, 10).await;
        return match main_tps {
            Some(tps) => format!(
                "⚡ Speed check (P1000 offline — main engine only)\n\
                 Main engine: {:.1} t/s\n\
                 P1000 ({}): offline",
                tps, validator_url
            ),
            None => format!(
                "Speed check failed — main engine ({}) also unreachable",
                state.config.coder_url
            ),
        };
    }

    let config = ValidatorConfig {
        main_endpoint: state.config.coder_url.clone(),
        ref_endpoint: validator_url.clone(),
        n_tokens: 10,
        min_agreement: 0.4, // TinyLlama vs 35B will diverge — 40% is fine
    };

    let result = run_validation(&config, prompt).await;

    format!(
        "⚡ Speed + Accuracy Check\n\
         Prompt: \"{}\"\n\
         {}\n\
         Main tokens:  {}\n\
         P1000 tokens: {}\n\
         \n\
         Note: Token agreement between different model sizes is expected to be ~40-70%.\n\
         Low agreement (<30%) on simple prompts may indicate main engine issues.",
        &prompt[..prompt.len().min(60)],
        result.summary,
        result.main_tokens.join(" "),
        result.ref_tokens.join(" "),
    )
}

// --- Helpers ---

fn resolve_path(relative: &str, state: &AppState) -> PathBuf {
    let root = PathBuf::from(&state.config.project_root);
    root.join(relative)
}

fn truncate_output(s: &str, max: usize) -> String {
    if s.len() > max {
        format!("{}...[truncated, {} total bytes]", &s[..max], s.len())
    } else {
        s.to_string()
    }
}

/// Simple timestamp without pulling in chrono crate.
fn chrono_now() -> String {
    // Use system time as unix timestamp
    let duration = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default();
    format!("{}", duration.as_secs())
}
