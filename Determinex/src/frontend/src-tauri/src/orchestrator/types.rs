/// orchestrator/types.rs — Domain types for the MoA pipeline.
use serde::{Deserialize, Serialize};

/// Raw context from the user or a previous stage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Context {
    pub user_prompt: String,
    pub thread_id: String,
    #[serde(default)]
    pub retry_count: u32,
    /// Frontend route-picker id (lib/aiRouting.ts's AI_ROUTE_OPTIONS), e.g. "auto",
    /// "local/fast", "determinex/planner", "free/qwen3-coder", "cloud/claude-best".
    /// "auto" or omitted means: use whatever Settings > Hive Roles has configured,
    /// unchanged. See PipelineModels::with_override.
    #[serde(default)]
    pub model_override: Option<String>,
}

/// Structured plan emitted by the Sentinel.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SentinelPlan {
    pub title: String,
    #[serde(deserialize_with = "deserialize_steps_flexible")]
    pub steps: Vec<String>,
    #[serde(default, deserialize_with = "deserialize_steps_flexible")]
    pub audit_targets: Vec<String>,
}

/// Custom deserializer for `steps` / `audit_targets`.
/// Accepts both `["a","b"]` (expected) and `[1,2,3]` (model variance).
pub fn deserialize_steps_flexible<'de, D>(de: D) -> Result<Vec<String>, D::Error>
where
    D: serde::Deserializer<'de>,
{
    use serde::de::{SeqAccess, Visitor};
    use std::fmt;

    struct FlexSeq;

    impl<'de> Visitor<'de> for FlexSeq {
        type Value = Vec<String>;

        fn expecting(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
            write!(f, "an array of strings or numbers")
        }

        fn visit_seq<A: SeqAccess<'de>>(self, mut seq: A) -> Result<Vec<String>, A::Error> {
            let mut out = Vec::new();
            while let Some(val) = seq.next_element::<serde_json::Value>()? {
                let s = match &val {
                    serde_json::Value::String(s) => s.clone(),
                    other => other.to_string(),
                };
                out.push(s);
            }
            Ok(out)
        }
    }

    de.deserialize_seq(FlexSeq)
}

pub fn default_edit_type() -> String {
    "full".to_string()
}

/// Raw code output from the Engineer stage.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EngineerCode {
    pub language: String,
    pub code: String,
    pub files_affected: Vec<String>,
    #[serde(default = "default_edit_type")]
    pub edit_type: String,
    #[serde(default)]
    pub target: String,
}

/// Structured audit verdict from the Observer.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ObserverVerdict {
    pub verdict: String,
    pub issues: Vec<String>,
    pub confidence: f32,
    pub review_notes: Option<String>,
}

/// Final packaged result of a complete MoA pipeline run.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MoAResult {
    pub thread_id: String,
    pub plan: SentinelPlan,
    pub code: EngineerCode,
    pub audit: ObserverVerdict,
    pub accepted: bool,
}

/// Error type for the orchestrator pipeline.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrchestratorError {
    pub stage: String,
    pub message: String,
    pub retryable: bool,
}

impl std::fmt::Display for OrchestratorError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(
            f,
            "[{}] {} (retryable={})",
            self.stage, self.message, self.retryable
        )
    }
}

impl OrchestratorError {
    pub fn transport(msg: String) -> Self {
        Self {
            stage: "Transport".to_string(),
            message: msg,
            retryable: true,
        }
    }
    pub fn sentinel(msg: String) -> Self {
        Self {
            stage: "Sentinel".to_string(),
            message: msg,
            retryable: false,
        }
    }
    pub fn engineer(msg: String) -> Self {
        Self {
            stage: "Engineer".to_string(),
            message: msg,
            retryable: false,
        }
    }
    pub fn observer(msg: String) -> Self {
        Self {
            stage: "Observer".to_string(),
            message: msg,
            retryable: false,
        }
    }
    pub fn system(msg: String) -> Self {
        Self {
            stage: "System".to_string(),
            message: msg,
            retryable: false,
        }
    }
    pub fn max_retries_exceeded(msg: String) -> Self {
        Self {
            stage: "System".to_string(),
            message: msg,
            retryable: false,
        }
    }
    pub fn security_panic(msg: &str) -> Self {
        Self {
            stage: "Security".to_string(),
            message: msg.to_string(),
            retryable: false,
        }
    }
}

/// Data captured from a failed pipeline attempt, held until a success triggers DPO logging.
pub struct PendingTrainingPair {
    pub system_prompt: String,
    pub failed_code: String,
    pub compiler_error: String,
}
