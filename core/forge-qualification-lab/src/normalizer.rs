use regex::Regex;

pub fn normalize_contract(raw_output: &str) -> String {
    let mut s = raw_output.trim().to_string();

    // Strip out <think> and <reasoning> blocks completely
    if let Ok(think_re) = Regex::new(r"(?s)<think>.*?</think>") {
        s = think_re.replace_all(&s, "").to_string();
    }
    if let Ok(reason_re) = Regex::new(r"(?s)<reasoning>.*?</reasoning>") {
        s = reason_re.replace_all(&s, "").to_string();
    }
    
    // Strip out Markdown code blocks
    if let Ok(code_re) = Regex::new(r"(?s)```(?:json)?\s*(\{.*?\})\s*```") {
        if let Some(cap) = code_re.captures(&s) {
            return cap[1].trim().to_string();
        }
    }

    // Try finding the first JSON object if there is text before/after
    if let Ok(brace_re) = Regex::new(r"(?s)^.*?(\{.*\}).*$") {
        if let Some(cap) = brace_re.captures(&s) {
            if serde_json::from_str::<serde_json::Value>(&cap[1]).is_ok() {
                return cap[1].trim().to_string();
            }
        }
    }

    s
}
