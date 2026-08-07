use regex::Regex;
use serde::{Deserialize, Serialize};

/// A normalized message in the conversation history.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Message {
    pub role: String,    // "system", "user", "assistant"
    pub content: String,
}

/// The result of normalizing raw model output.
#[derive(Debug)]
pub struct NormalizedMessage {
    pub content: String,
    pub tool_call: Option<ToolCall>,
    pub failure: Option<FailureType>,
}

/// A parsed tool call extracted from model output.
#[derive(Debug, Clone, Serialize)]
pub struct ToolCall {
    pub name: String,
    pub arguments: serde_json::Value,
}

/// Detected failure states in model output.
#[derive(Debug, Clone, Serialize)]
pub enum FailureType {
    ThinkOnly,
    EmptyResponse,
    RepeatedToolCall,
    MalformedToolCall,
    PromptLeak,
    LoopDetected,
}

/// Normalize raw model output: strip artifacts, extract tool calls, detect failures.
pub fn normalize(raw_output: &str) -> NormalizedMessage {
    let stripped = strip_artifacts(raw_output);

    // Check for empty after stripping
    if stripped.trim().is_empty() {
        // Was it think-only?
        if raw_output.contains("<think>") || raw_output.contains("<reasoning>") {
            let think_content = extract_think_content(raw_output);
            // For Qwen3.6: thinking IS working. Return the think content as valid output.
            // The loop engine will feed it back and let the model continue to a tool call.
            if think_content.len() > 30 {
                return NormalizedMessage {
                    content: think_content,
                    tool_call: None,
                    failure: None, // NOT a failure — model is reasoning
                };
            }
            return NormalizedMessage {
                content: think_content,
                tool_call: None,
                failure: Some(FailureType::ThinkOnly),
            };
        }
        return NormalizedMessage {
            content: String::new(),
            tool_call: None,
            failure: Some(FailureType::EmptyResponse),
        };
    }

    // Check for prompt leaks
    if has_prompt_leak(&stripped) {
        return NormalizedMessage {
            content: stripped.clone(),
            tool_call: None,
            failure: Some(FailureType::PromptLeak),
        };
    }

    // Try to extract a tool call
    match extract_tool_call(&stripped) {
        Some(Ok(tc)) => NormalizedMessage {
            content: stripped,
            tool_call: Some(tc),
            failure: None,
        },
        Some(Err(_)) => NormalizedMessage {
            content: stripped,
            tool_call: None,
            failure: Some(FailureType::MalformedToolCall),
        },
        None => NormalizedMessage {
            content: stripped,
            tool_call: None,
            failure: None,
        },
    }
}

/// Format a tool result as a QwenChatML user message for multi-turn tool use.
pub fn format_tool_result_for_qwen(result: &str, _round: u32, _max_rounds: u32) -> String {
    format!(
        "<|im_end|>\n<|im_start|>user\n[Tool Result]: {}\nNow continue. Either call another tool or provide your final answer.<|im_end|>\n<|im_start|>assistant\n",
        result
    )
}

/// N-gram loop detection: returns true if current output is 80%+ similar to recent outputs.
pub fn detect_output_loop(history: &[String], current: &str) -> bool {
    let current_lines: Vec<&str> = current.lines().collect();
    if current_lines.is_empty() {
        return false;
    }

    history.iter().rev().take(3).any(|prev| {
        let prev_lines: Vec<&str> = prev.lines().collect();
        if prev_lines.is_empty() {
            return false;
        }
        let matching = current_lines
            .iter()
            .filter(|line| prev_lines.contains(line))
            .count();
        let total = current_lines.len().max(prev_lines.len());
        (matching as f32 / total as f32) > 0.8
    })
}

// --- Internal helpers ---

fn strip_artifacts(raw: &str) -> String {
    let mut s = raw.to_string();

    // Remove <think>...</think> blocks
    let think_re = Regex::new(r"(?s)<think>.*?</think>").unwrap();
    s = think_re.replace_all(&s, "").to_string();

    // Remove <reasoning>...</reasoning> blocks
    let reason_re = Regex::new(r"(?s)<reasoning>.*?</reasoning>").unwrap();
    s = reason_re.replace_all(&s, "").to_string();

    // Remove prompt leak tokens
    s = s.replace("<|im_start|>", "");
    s = s.replace("<|im_end|>", "");
    s = s.replace("<|endoftext|>", "");

    s.trim().to_string()
}

fn extract_think_content(raw: &str) -> String {
    let re = Regex::new(r"(?s)<think>(.*?)</think>").unwrap();
    if let Some(cap) = re.captures(raw) {
        format!("[Model reasoning]: {}", cap[1].trim())
    } else {
        "[Model produced only thinking content]".to_string()
    }
}

fn has_prompt_leak(text: &str) -> bool {
    let leak_markers = [
        "<|im_start|>system",
        "You are a helpful",
        "<|im_start|>user",
        "### System:",
        "[INST]",
    ];
    leak_markers.iter().any(|m| text.contains(m))
}

fn extract_tool_call(text: &str) -> Option<Result<ToolCall, String>> {
    // Try <tool_call>JSON</tool_call> format (preferred)
    let re = Regex::new(r"(?s)<tool_call>\s*(.*?)\s*</tool_call>").unwrap();
    if let Some(cap) = re.captures(text) {
        let json_str = cap[1].trim();
        return Some(parse_tool_json(json_str));
    }

    // Try ```json ... ``` with "name" and "arguments" keys
    let code_re = Regex::new(r"(?s)```(?:json)?\s*(\{.*?\})\s*```").unwrap();
    if let Some(cap) = code_re.captures(text) {
        let json_str = cap[1].trim();
        if json_str.contains("\"name\"") && json_str.contains("\"arguments\"") {
            return Some(parse_tool_json(json_str));
        }
    }

    // FALLBACK: Try raw JSON object with "name" and "arguments" keys anywhere in text
    // This catches models that output {"name": "tool", "arguments": {...}} without tags
    if let Some(start) = text.find(r#"{"name""#) {
        // Find the matching closing brace
        let slice = &text[start..];
        if let Some(end) = find_matching_brace(slice) {
            let json_str = &slice[..=end];
            if json_str.contains("arguments") {
                return Some(parse_tool_json(json_str));
            }
        }
    }

    // FALLBACK 2: If the entire stripped text IS a JSON object with "name" key
    let trimmed = text.trim();
    if trimmed.starts_with('{') && trimmed.ends_with('}') && trimmed.contains(r#""name""#) {
        return Some(parse_tool_json(trimmed));
    }

    None
}

/// Find the index of the matching closing brace for a string starting with '{'.
fn find_matching_brace(s: &str) -> Option<usize> {
    let mut depth = 0;
    for (i, c) in s.chars().enumerate() {
        match c {
            '{' => depth += 1,
            '}' => {
                depth -= 1;
                if depth == 0 {
                    return Some(i);
                }
            }
            _ => {}
        }
    }
    None
}

fn parse_tool_json(json_str: &str) -> Result<ToolCall, String> {
    // First try: direct JSON parse
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(json_str) {
        let name = v
            .get("name")
            .and_then(|n| n.as_str())
            .ok_or_else(|| "Missing 'name' field".to_string())?
            .to_string();

        // Accept both "arguments" and "args" keys
        let arguments = v
            .get("arguments")
            .or_else(|| v.get("args"))
            .cloned()
            .unwrap_or(serde_json::Value::Object(serde_json::Map::new()));

        return Ok(ToolCall { name, arguments });
    }

    // Second try: fix Qwen's common malformation
    // Pattern: {"name": "tool_name", {"arguments": {...}}}
    // Fix: insert "arguments": before the nested object
    let fixed = fix_qwen_json(json_str);
    if let Ok(v) = serde_json::from_str::<serde_json::Value>(&fixed) {
        let name = v
            .get("name")
            .and_then(|n| n.as_str())
            .ok_or_else(|| "Missing 'name' field".to_string())?
            .to_string();

        let arguments = v
            .get("arguments")
            .cloned()
            .unwrap_or(serde_json::Value::Object(serde_json::Map::new()));

        return Ok(ToolCall { name, arguments });
    }

    // Third try: regex extraction of name and arguments block
    let name_re = Regex::new(r#""name"\s*:\s*"([^"]+)""#).unwrap();
    let args_re = Regex::new(r#"(?s)"arguments"\s*:\s*(\{.*\})"#).unwrap();

    if let Some(name_cap) = name_re.captures(json_str) {
        let name = name_cap[1].to_string();
        let arguments = if let Some(args_cap) = args_re.captures(json_str) {
            serde_json::from_str(&args_cap[1]).unwrap_or(serde_json::Value::Object(serde_json::Map::new()))
        } else {
            serde_json::Value::Object(serde_json::Map::new())
        };
        return Ok(ToolCall { name, arguments });
    }

    Err(format!("Cannot parse tool call JSON: {}", &json_str[..json_str.len().min(200)]))
}

/// Fix Qwen's common JSON malformation where it drops the "arguments" key.
/// Input:  {"name": "think_harder", {"arguments": {"query": "..."}}}
/// Output: {"name": "think_harder", "arguments": {"query": "..."}}
fn fix_qwen_json(json_str: &str) -> String {
    // Pattern: ", {" after a quoted value — insert "arguments":
    let re = Regex::new(r#"("name"\s*:\s*"[^"]+"\s*),\s*\{\s*"arguments""#).unwrap();
    let fixed = re.replace(json_str, r#"$1, "arguments""#).to_string();

    // Also handle: {"name": "x", {"key": "val"}} → {"name": "x", "arguments": {"key": "val"}}
    let re2 = Regex::new(r#"("name"\s*:\s*"[^"]+"\s*),\s*\{"#).unwrap();
    if fixed == json_str {
        // First fix didn't match, try wrapping the orphan object as arguments
        re2.replace(json_str, r#"$1, "arguments": {"#).to_string()
    } else {
        fixed
    }
}
