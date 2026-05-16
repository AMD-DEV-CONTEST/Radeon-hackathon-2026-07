//! Chat template registry for multi-model support.
//! Auto-detects from GGUF metadata or selects via CLI flag.
//! Tracks inference metrics per template tier for comparison.

use std::collections::HashMap;
use std::time::{Instant, Duration};
use serde::{Serialize, Deserialize};

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ChatTemplate {
    pub name: String,
    pub system_prefix: String,
    pub system_suffix: String,
    pub user_prefix: String,
    pub user_suffix: String,
    pub assistant_prefix: String,
    pub assistant_suffix: String,
    pub default_system: Option<String>,
    pub thinking_prefix: Option<String>,
    pub stop_token_ids: Vec<u32>,
}

impl ChatTemplate {
    /// Format a simple user prompt into the full chat template string.
    pub fn wrap_prompt(&self, user_prompt: &str) -> String {
        let mut out = String::new();

        // System message
        if let Some(ref sys) = self.default_system {
            out.push_str(&self.system_prefix);
            out.push_str(sys);
            out.push_str(&self.system_suffix);
        }

        // User message
        out.push_str(&self.user_prefix);
        out.push_str(user_prompt);
        out.push_str(&self.user_suffix);

        // Assistant prefix (generation starts here)
        out.push_str(&self.assistant_prefix);

        out
    }

    /// Check if a token ID is a stop token for this template.
    pub fn is_stop_token(&self, token_id: u32) -> bool {
        self.stop_token_ids.contains(&token_id)
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct InferenceMetrics {
    pub template_name: String,
    pub time_to_first_token_ms: u128,
    pub tokens_per_second: f32,
    pub total_tokens_generated: u32,
    pub final_logit_entropy: f32,
}

pub struct TemplateRegistry {
    pub templates: HashMap<String, ChatTemplate>,
    pub metrics_log: Vec<InferenceMetrics>,
}

impl TemplateRegistry {
    pub fn new() -> Self {
        let mut templates = HashMap::new();

        // --- Qwen 2.5 Instruct (verified working) ---
        templates.insert("qwen2.5".to_string(), ChatTemplate {
            name: "qwen2.5-instruct".to_string(),
            system_prefix: "<|im_start|>system\n".to_string(),
            system_suffix: "<|im_end|>\n".to_string(),
            user_prefix: "<|im_start|>user\n".to_string(),
            user_suffix: "<|im_end|>\n".to_string(),
            assistant_prefix: "<|im_start|>assistant\n".to_string(),
            assistant_suffix: "<|im_end|>".to_string(),
            default_system: Some("You are a helpful assistant.".to_string()),
            thinking_prefix: None,
            stop_token_ids: vec![151645, 151643], // <|im_end|>, <|endoftext|>
        });

        // --- Qwen 3 / 3.6 (ChatML + thinking toggle) ---
        templates.insert("qwen3".to_string(), ChatTemplate {
            name: "qwen3-reasoning".to_string(),
            system_prefix: "<|im_start|>system\n".to_string(),
            system_suffix: "<|im_end|>\n".to_string(),
            user_prefix: "<|im_start|>user\n".to_string(),
            user_suffix: "<|im_end|>\n".to_string(),
            assistant_prefix: "<|im_start|>assistant\n".to_string(),
            assistant_suffix: "<|im_end|>".to_string(),
            default_system: None, // Qwen3 doesn't need a default system prompt
            thinking_prefix: Some("<think>\n".to_string()),
            stop_token_ids: vec![151645, 151643],
        });

        // --- Qwen 3 with thinking disabled (fast mode) ---
        templates.insert("qwen3-nothink".to_string(), ChatTemplate {
            name: "qwen3-fast".to_string(),
            system_prefix: "<|im_start|>system\n".to_string(),
            system_suffix: "<|im_end|>\n".to_string(),
            user_prefix: "<|im_start|>user\n".to_string(),
            user_suffix: "<|im_end|>\n".to_string(),
            assistant_prefix: "<|im_start|>assistant\n<think>\n\n</think>\n\n".to_string(),
            assistant_suffix: "<|im_end|>".to_string(),
            default_system: None,
            thinking_prefix: None,
            stop_token_ids: vec![151645, 151643],
        });

        // --- Phi-3 Mini ---
        templates.insert("phi3".to_string(), ChatTemplate {
            name: "phi3-mini-instruct".to_string(),
            system_prefix: "<|system|>\n".to_string(),
            system_suffix: "<|end|>\n".to_string(),
            user_prefix: "<|user|>\n".to_string(),
            user_suffix: "<|end|>\n".to_string(),
            assistant_prefix: "<|assistant|>\n".to_string(),
            assistant_suffix: "<|end|>".to_string(),
            default_system: None,
            thinking_prefix: None,
            stop_token_ids: vec![32007], // <|end|>
        });

        // --- DeepSeek R1 (native format) ---
        templates.insert("deepseek-r1".to_string(), ChatTemplate {
            name: "deepseek-r1-reasoning".to_string(),
            system_prefix: "".to_string(),
            system_suffix: "".to_string(),
            user_prefix: "<|User|>".to_string(),
            user_suffix: "".to_string(),
            assistant_prefix: "<|Assistant|><think>\n".to_string(),
            assistant_suffix: "</think>".to_string(),
            default_system: None,
            thinking_prefix: Some("<think>\n".to_string()),
            stop_token_ids: vec![100001], // <|end▁of▁sentence|>
        });

        // --- DeepSeek R1 Distill (Qwen-based, uses ChatML) ---
        templates.insert("deepseek-r1-qwen".to_string(), ChatTemplate {
            name: "deepseek-r1-distill-qwen".to_string(),
            system_prefix: "<|im_start|>system\n".to_string(),
            system_suffix: "<|im_end|>\n".to_string(),
            user_prefix: "<|im_start|>user\n".to_string(),
            user_suffix: "<|im_end|>\n".to_string(),
            assistant_prefix: "<|im_start|>assistant\n<think>\n".to_string(),
            assistant_suffix: "</think>\n<|im_end|>".to_string(),
            default_system: None,
            thinking_prefix: Some("<think>\n".to_string()),
            stop_token_ids: vec![151645, 151643],
        });

        Self {
            templates,
            metrics_log: Vec::new(),
        }
    }

    /// Get a template by key. Falls back to qwen2.5 if not found.
    pub fn get(&self, key: &str) -> &ChatTemplate {
        self.templates.get(key)
            .unwrap_or_else(|| self.templates.get("qwen2.5").unwrap())
    }

    /// Auto-detect template from GGUF model filename or metadata.
    /// Heuristic: check for known substrings in the model name.
    pub fn detect_from_model_name(&self, model_name: &str) -> &ChatTemplate {
        let lower = model_name.to_lowercase();

        if lower.contains("deepseek") && lower.contains("r1") {
            if lower.contains("qwen") || lower.contains("distill") {
                return self.get("deepseek-r1-qwen");
            }
            return self.get("deepseek-r1");
        }

        if lower.contains("qwen3") || lower.contains("qwen-3") {
            return self.get("qwen3");
        }

        if lower.contains("phi-3") || lower.contains("phi3") {
            return self.get("phi3");
        }

        // Default: Qwen 2.5
        self.get("qwen2.5")
    }

    /// Log metrics from an inference pass for cross-model comparison.
    pub fn log_inference(
        &mut self,
        template_name: &str,
        start_time: Instant,
        first_token_time: Duration,
        token_count: u32,
        final_entropy: f32,
    ) {
        let total_duration = start_time.elapsed();
        let tps = if total_duration.as_secs_f32() > 0.0 {
            token_count as f32 / total_duration.as_secs_f32()
        } else {
            0.0
        };

        self.metrics_log.push(InferenceMetrics {
            template_name: template_name.to_string(),
            time_to_first_token_ms: first_token_time.as_millis(),
            tokens_per_second: tps,
            total_tokens_generated: token_count,
            final_logit_entropy: final_entropy,
        });
    }

    /// Get average tokens/sec for a given template (for comparison).
    pub fn avg_tps(&self, template_name: &str) -> f32 {
        let matching: Vec<f32> = self.metrics_log.iter()
            .filter(|m| m.template_name == template_name)
            .map(|m| m.tokens_per_second)
            .collect();
        if matching.is_empty() { return 0.0; }
        matching.iter().sum::<f32>() / matching.len() as f32
    }
}
