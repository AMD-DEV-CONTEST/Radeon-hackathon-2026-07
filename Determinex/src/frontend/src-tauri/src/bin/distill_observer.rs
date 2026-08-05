use reqwest::{header, Client};
use serde::{Deserialize, Serialize};
use serde_json::json;
use std::env;
use std::fs::{self, File, OpenOptions};
use std::io::{BufRead, BufReader, Write};

#[derive(Serialize, Deserialize, Clone)]
struct ObserverMistakeEvent {
    timestamp: String,
    language: String,
    task_id: String,
    passing_code: String,
    compiler_test_output: String,
    wrong_observer_verdict: String,
    wrong_observer_confidence: f32,
    wrong_observer_notes: Option<String>,
}

#[derive(Serialize)]
struct DistilledObserverEvent {
    original: ObserverMistakeEvent,
    claude_correct_verdict_reasoning: String,
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

    let in_file = match File::open("determinex_v1_observer_mistakes.jsonl") {
        Ok(f) => f,
        Err(_) => {
            println!(
                "[DISTIL-OBS] No determinex_v1_observer_mistakes.jsonl found. Nothing to distill."
            );
            return Ok(());
        }
    };

    let mut out_file = OpenOptions::new()
        .create(true)
        .append(true)
        .open("determinex_v1_distilled_observer.jsonl")?;

    let reader = BufReader::new(in_file);

    let total_entries = fs::read_to_string("determinex_v1_observer_mistakes.jsonl")
        .unwrap_or_default()
        .lines()
        .filter(|l| !l.trim().is_empty())
        .count();

    println!(
        "[DISTIL-OBS] Observer mistake vault loaded — {} entries queued.",
        total_entries
    );
    println!("===============================================================");

    let mut idx = 0usize;
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }
        idx += 1;

        let event: ObserverMistakeEvent = serde_json::from_str(&line)?;
        println!(
            "[DISTIL-OBS] [{}/{}] Processing -> {}",
            idx, total_entries, event.task_id
        );

        let system_prompt = "You are a Senior Code Review Instructor training an AI code reviewer. \
            Your job is to correct a faulty verdict and explain, in detail, why the code is CORRECT and CLEAN. \
            The AI reviewer incorrectly flagged working code as HALLUCINATION. \
            Provide a thorough explanation of why the code is CLEAN so the AI learns to recognize valid code patterns.";

        let user_content = format!(
            "Language: {}\n\
            Task ID: {}\n\n\
            Code that was written (compiled and passed ALL tests):\n{}\n\n\
            Compiler & Test Output (PASSING):\n{}\n\n\
            The Observer AI gave this WRONG verdict: {} (confidence: {:.0}%)\n\
            Observer notes: {}\n\n\
            Explain in detail why this verdict is WRONG and what the CORRECT verdict (CLEAN) should be, \
            and what patterns the reviewer should look for to correctly identify working code in the future.",
            event.language,
            event.task_id,
            event.passing_code,
            event.compiler_test_output,
            event.wrong_observer_verdict,
            event.wrong_observer_confidence * 100.0,
            event.wrong_observer_notes.as_deref().unwrap_or("none"),
        );

        let payload = json!({
            "model": "claude-opus-4-6",
            "max_tokens": 2048,
            "system": system_prompt,
            "messages": [{ "role": "user", "content": user_content }]
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
        let reasoning = anthropic_res
            .content
            .into_iter()
            .next()
            .map(|c| c.text)
            .unwrap_or_default();

        let distilled = DistilledObserverEvent {
            original: event,
            claude_correct_verdict_reasoning: reasoning,
        };

        writeln!(out_file, "{}", serde_json::to_string(&distilled)?)?;
        println!(
            "[DISTIL-OBS] [{}/{}] Committed -> {}",
            idx, total_entries, distilled.original.task_id
        );
    }

    println!("===============================================================");
    println!("[DISTIL-OBS] Complete. determinex_v1_distilled_observer.jsonl ready for Unsloth.");
    Ok(())
}
