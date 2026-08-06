/// Token estimation strategies.
/// Priority order per design doc:
/// 1. vLLM tokenizer endpoint (future)
/// 2. Local tokenizer matching the service (future)
/// 3. Conservative byte estimation with expanded safety margin

/// Conservative token estimate from text.
/// Uses ~3.5 bytes per token for English/code, ~2 bytes for CJK.
/// Intentionally over-estimates to be safe for admission control.
pub fn estimate_tokens(text: &str) -> u32 {
    let mut byte_weight: f64 = 0.0;
    for ch in text.chars() {
        if ch.is_ascii() {
            byte_weight += 1.0;
        } else {
            // CJK and other multibyte: roughly 2 tokens per char
            byte_weight += 2.5;
        }
    }
    // Conservative: ~3.5 chars per token for ASCII
    // Add 10% safety margin on top
    let raw = (byte_weight / 3.5).ceil() as u32;
    (raw as f64 * 1.1).ceil() as u32
}

/// Estimate tokens for a list of chat messages.
/// Accounts for message framing overhead (~4 tokens per message).
pub fn estimate_messages_tokens(messages: &[(String, String)]) -> u32 {
    let mut total: u32 = 0;
    for (role, content) in messages {
        total += estimate_tokens(role);
        total += estimate_tokens(content);
        total += 4; // message framing overhead
    }
    total += 2; // chat template overhead
    total
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_estimate_ascii() {
        let text = "Hello, this is a test of the token estimator.";
        let tokens = estimate_tokens(text);
        // ~46 chars / 3.5 ≈ 13.1 * 1.1 ≈ 15
        assert!(tokens > 10 && tokens < 25, "tokens = {tokens}");
    }

    #[test]
    fn test_estimate_cjk() {
        let text = "\u{8fd9}\u{662f}\u{4e00}\u{4e2a}\u{4e2d}\u{6587}\u{6d4b}\u{8bd5}";
        let tokens = estimate_tokens(text);
        // 8 CJK chars * 2.5 = 20 / 3.5 ≈ 5.7 * 1.1 ≈ 7
        assert!(tokens > 4 && tokens < 15, "tokens = {tokens}");
    }

    #[test]
    fn test_empty() {
        assert_eq!(estimate_tokens(""), 0);
    }
}
