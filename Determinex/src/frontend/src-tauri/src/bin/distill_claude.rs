use reqwest::{header, Client};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};

#[derive(Serialize, Deserialize, Clone)]
struct TelemetryEvent {
    timestamp: String,
    language: String,
    task_id: String,
    original_broken_code: String,
    raw_compiler_panic: String,
    observer_review_notes: String,
    final_status: String,
}

#[derive(Serialize)]
struct DistilledEvent {
    original: TelemetryEvent,
    claude_expert_analysis: String,
}

#[derive(Deserialize)]
struct AnthropicResponseContent {
    text: String,
}

#[derive(Deserialize)]
struct AnthropicResponse {
    content: Vec<AnthropicResponseContent>,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    dotenvy::dotenv().ok();
    let anthropic_key =
        env::var("ANTHROPIC_API_KEY").expect("CRITICAL: ANTHROPIC_API_KEY missing in .env");

    let mut headers = header::HeaderMap::new();
    headers.insert("x-api-key", header::HeaderValue::from_str(&anthropic_key)?);
    headers.insert(
        "anthropic-version",
        header::HeaderValue::from_static("2023-06-01"),
    );
    headers.insert(
        header::CONTENT_TYPE,
        header::HeaderValue::from_static("application/json"),
    );

    let client = Client::builder().default_headers(headers).build()?;

    let in_file = match File::open("determinex_v1_failures.jsonl") {
        Ok(f) => f,
        Err(_) => {
            println!("No determinex_v1_failures.jsonl found. Exiting distillation.");
            return Ok(());
        }
    };

    let mut out_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open("determinex_v1_distilled_claude.jsonl")?;

    let reader = BufReader::new(in_file);

    // Pre-count total entries for numbered output
    let total_entries = fs::read_to_string("determinex_v1_failures.jsonl")
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .count();

    println!(
        "[DISTIL] Vault loaded — {} entries queued for distillation.",
        total_entries
    );
    println!("═══════════════════════════════════════════════════════════════");

    let mut idx = 0usize;
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        idx += 1;

        let event: TelemetryEvent = serde_json::from_str(&line)?;

        println!(
            "[DISTIL] [{}/{}] Processing → {}",
            idx, total_entries, event.task_id
        );

        let system_prompt = "You are a Senior Principal Engineer. Analyze the failure and provide the correct architectural fix.";
        let user_content = format!(
            "Language: {}\nFailed Code:\n{}\n\nCompiler Panic/Output:\n{}\n\nPrevious Observer Notes:\n{}",
            event.language, event.original_broken_code, event.raw_compiler_panic, event.observer_review_notes
        );

        let payload = json!({
            "model": "claude-opus-4-6",
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [
                {
                    "role": "user",
                    "content": user_content
                }
            ]
        });

        let res_obj = client
            .post("https://api.anthropic.com/v1/messages")
            .json(&payload)
            .send()
            .await?;

        if !res_obj.status().is_success() {
            eprintln!("[ERROR] Claude API Failed: {}", res_obj.text().await?);
            continue;
        }

        let anthropic_res: AnthropicResponse = res_obj.json().await?;
        let analysis_text = anthropic_res
            .content
            .into_iter()
            .next()
            .map(|c| c.text)
            .unwrap_or_default();

        let distilled = DistilledEvent {
            original: event,
            claude_expert_analysis: analysis_text,
        };

        writeln!(out_file, "{}", serde_json::to_string(&distilled)?)?;
        println!(
            "[DISTIL] [{}/{}] ✅ Committed — {}",
            idx, total_entries, distilled.original.task_id
        );
    }

    Ok(())
}
