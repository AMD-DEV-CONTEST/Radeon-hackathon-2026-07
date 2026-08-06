use anyhow::Result;
use serde::{Deserialize, Serialize};
use std::path::Path;

/// Model profile captures verified runtime characteristics.
/// Loaded from profiles/*.toml files.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelProfile {
    pub model: ModelConfig,
    pub context: ContextConfig,
    pub sampling: SamplingConfig,
    pub thinking: ThinkingConfig,
    pub concurrency: ConcurrencyConfig,
    pub timeouts: TimeoutConfig,
    pub run: RunConfig,
    pub prompt: PromptConfig,
    /// Optional in-process model simulator used when no model service exists.
    #[serde(default)]
    pub simulator: SimulatorConfig,
}

/// Profile-level switch for the persistent in-process model simulator.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct SimulatorConfig {
    /// Use the simulator instead of the configured HTTP endpoint.
    #[serde(default)]
    pub enabled: bool,
    /// Scripted scenario file. Relative paths are resolved from the current
    /// FlintCode workspace.
    pub scenario: Option<std::path::PathBuf>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ModelConfig {
    pub name: String,
    pub endpoint_env: String,
    pub default_endpoint: String,
    pub api_path: String,
    /// Optional environment variable containing the Bearer API key.
    #[serde(default)]
    pub api_key_env: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ContextConfig {
    pub model_context_tokens: u32,
    pub max_prompt_tokens: u32,
    pub max_completion_tokens: u32,
    pub safety_tokens: u32,
}

impl ContextConfig {
    /// Agent usable limit = max_prompt + max_completion + safety
    pub fn agent_limit(&self) -> u32 {
        self.max_prompt_tokens + self.max_completion_tokens + self.safety_tokens
    }

    /// Whether a given prompt size fits the budget
    pub fn admits(&self, estimated_prompt_tokens: u32) -> bool {
        estimated_prompt_tokens <= self.max_prompt_tokens
            && estimated_prompt_tokens + self.max_completion_tokens + self.safety_tokens
                <= self.model_context_tokens
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SamplingConfig {
    pub temperature: f32,
    pub top_p: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ThinkingConfig {
    pub enabled: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ConcurrencyConfig {
    pub max_in_flight: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct TimeoutConfig {
    pub health_secs: u64,
    pub model_secs: u64,
    pub domain_validation_secs: u64,
    pub build_secs: u64,
    pub test_secs: u64,
    pub cancel_grace_secs: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RunConfig {
    pub max_repairs: u8,
    pub retry_http_4xx: bool,
    pub retry_http_5xx_count: u8,
    pub diagnostic_character_limit: usize,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PromptConfig {
    pub max_system_prompt_tokens: u32,
}

impl ModelProfile {
    /// Load a profile from a TOML file
    pub fn load(path: &Path) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let profile: Self = toml::from_str(&content)?;
        Ok(profile)
    }

    /// Resolve the actual endpoint URL, checking env var first
    pub fn resolve_endpoint(&self) -> String {
        std::env::var(&self.model.endpoint_env)
            .unwrap_or_else(|_| self.model.default_endpoint.clone())
    }

    /// Full URL for chat completions
    pub fn chat_url(&self) -> String {
        let base = self.resolve_endpoint();
        let base = base.trim_end_matches('/');
        let mut path = self.model.api_path.trim_start_matches('/');
        if base.ends_with("/v1") {
            path = path.strip_prefix("v1/").unwrap_or(path);
        }
        format!("{base}/{path}")
    }

    /// Full URL for the OpenAI-compatible models endpoint.
    pub fn models_url(&self) -> String {
        let base = self.resolve_endpoint();
        let base = base.trim_end_matches('/');
        if base.ends_with("/v1") {
            format!("{base}/models")
        } else {
            format!("{base}/v1/models")
        }
    }

    /// Resolve an optional Bearer API key from the configured environment.
    pub fn resolve_api_key(&self) -> Option<String> {
        self.model
            .api_key_env
            .as_deref()
            .and_then(|name| std::env::var(name).ok())
            .filter(|key| !key.trim().is_empty())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn profile(endpoint: &str) -> ModelProfile {
        toml::from_str(&format!(
            r#"
[model]
name = "test"
endpoint_env = "FLINTCODE_TEST_UNUSED_ENDPOINT"
default_endpoint = "{endpoint}"
api_path = "/v1/chat/completions"

[context]
model_context_tokens = 65536
max_prompt_tokens = 48000
max_completion_tokens = 4096
safety_tokens = 8192

[sampling]
temperature = 0.0
top_p = 1.0

[thinking]
enabled = false

[concurrency]
max_in_flight = 1

[timeouts]
health_secs = 10
model_secs = 30
domain_validation_secs = 30
build_secs = 30
test_secs = 30
cancel_grace_secs = 2

[run]
max_repairs = 1
retry_http_4xx = false
retry_http_5xx_count = 1
diagnostic_character_limit = 12000

[prompt]
max_system_prompt_tokens = 2000
"#
        ))
        .expect("profile")
    }

    #[test]
    fn versioned_endpoint_is_not_duplicated() {
        let profile = profile("https://example.com/v1");
        assert_eq!(
            profile.chat_url(),
            "https://example.com/v1/chat/completions"
        );
        assert_eq!(profile.models_url(), "https://example.com/v1/models");
    }

    #[test]
    fn unversioned_endpoint_gets_the_openai_version_prefix() {
        let profile = profile("https://example.com");
        assert_eq!(
            profile.chat_url(),
            "https://example.com/v1/chat/completions"
        );
        assert_eq!(profile.models_url(), "https://example.com/v1/models");
    }
}
