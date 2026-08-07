//! Model architecture abstraction layer.
//!
//! Allows the engine to support multiple model families (Qwen2.5, Gemma4, Llama3, etc.)
//! by abstracting tensor naming, RoPE config, attention type, and MoE routing.

/// Supported model families.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ModelFamily {
    Qwen2_5,
    Gemma4,
    Llama3,
    Phi3,
    DeepSeekV2,
}

/// RoPE implementation variant.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RopeType {
    /// Standard RoPE with half-split pairs (d, d+half_dim)
    HalfSplit,
    /// Interleaved pairs (2d, 2d+1) — GPT-NeoX style
    Interleaved,
    /// Yarn scaling for extended context
    Yarn,
}

/// RoPE configuration for a model.
#[derive(Debug, Clone)]
pub struct RopeConfig {
    pub theta: f32,
    pub scaling_factor: f32,
    pub rope_type: RopeType,
    /// Partial RoPE: only rotate first `partial_dim` elements per head
    /// (None = rotate full head_dim)
    pub partial_dim: Option<u32>,
}

/// Attention type.
#[derive(Debug, Clone, Copy)]
pub enum AttentionType {
    Causal,
    SlidingWindow { window_size: u32 },
}

/// MoE (Mixture of Experts) configuration.
#[derive(Debug, Clone)]
pub struct MoEConfig {
    pub num_experts: u32,
    pub num_active_experts: u32,
    pub shared_experts: u32,
}

/// Full model architecture descriptor — built from GGUF metadata.
#[derive(Debug, Clone)]
pub struct ModelArch {
    pub family: ModelFamily,
    pub rope: RopeConfig,
    pub attention: AttentionType,
    pub moe: Option<MoEConfig>,
}

impl ModelArch {
    /// Detect model family from GGUF metadata keys.
    pub fn from_gguf_metadata(arch_name: &str, n_experts: usize, rope_theta: f32) -> Self {
        let family = match arch_name {
            s if s.contains("qwen2") => ModelFamily::Qwen2_5,
            s if s.contains("gemma") => ModelFamily::Gemma4,
            s if s.contains("llama") => ModelFamily::Llama3,
            s if s.contains("phi") => ModelFamily::Phi3,
            s if s.contains("deepseek") => ModelFamily::DeepSeekV2,
            _ => ModelFamily::Llama3, // Default to Llama-style
        };

        let rope = RopeConfig {
            theta: rope_theta,
            scaling_factor: 1.0,
            rope_type: match family {
                ModelFamily::Qwen2_5 => RopeType::HalfSplit,
                ModelFamily::Gemma4 => RopeType::HalfSplit,
                ModelFamily::Llama3 => RopeType::HalfSplit,
                ModelFamily::Phi3 => RopeType::HalfSplit,
                ModelFamily::DeepSeekV2 => RopeType::Yarn,
            },
            partial_dim: None,
        };

        let attention = match family {
            ModelFamily::Gemma4 => AttentionType::SlidingWindow { window_size: 4096 },
            _ => AttentionType::Causal,
        };

        let moe = if n_experts > 0 {
            Some(MoEConfig {
                num_experts: n_experts as u32,
                num_active_experts: match family {
                    ModelFamily::Gemma4 => 2,
                    ModelFamily::DeepSeekV2 => 6,
                    _ => 2,
                },
                shared_experts: 0,
            })
        } else {
            None
        };

        Self { family, rope, attention, moe }
    }

    /// Get GGUF tensor name for a given layer and component.
    pub fn tensor_name(&self, layer: usize, component: &str) -> String {
        match component {
            "embed" => "token_embd.weight".to_string(),
            "final_norm" => "output_norm.weight".to_string(),
            "lm_head" => "output.weight".to_string(),
            "attn_norm" => format!("blk.{}.attn_norm.weight", layer),
            "ffn_norm" => format!("blk.{}.ffn_norm.weight", layer),
            "q_proj" => format!("blk.{}.attn_q.weight", layer),
            "k_proj" => format!("blk.{}.attn_k.weight", layer),
            "v_proj" => format!("blk.{}.attn_v.weight", layer),
            "o_proj" => format!("blk.{}.attn_output.weight", layer),
            "gate_proj" => format!("blk.{}.ffn_gate.weight", layer),
            "up_proj" => format!("blk.{}.ffn_up.weight", layer),
            "down_proj" => format!("blk.{}.ffn_down.weight", layer),
            "q_bias" => format!("blk.{}.attn_q.bias", layer),
            "k_bias" => format!("blk.{}.attn_k.bias", layer),
            "v_bias" => format!("blk.{}.attn_v.bias", layer),
            // MoE-specific
            "moe_gate" => format!("blk.{}.ffn_gate_inp.weight", layer),
            "expert_gate" => format!("blk.{}.ffn_gate.{{}}.weight", layer), // needs expert idx
            "expert_up" => format!("blk.{}.ffn_up.{{}}.weight", layer),
            "expert_down" => format!("blk.{}.ffn_down.{{}}.weight", layer),
            _ => format!("blk.{}.{}", layer, component),
        }
    }

    /// Whether this model has QKV biases.
    pub fn has_qkv_bias(&self) -> bool {
        matches!(self.family, ModelFamily::Qwen2_5)
    }

    /// Whether this model is MoE.
    pub fn is_moe(&self) -> bool {
        self.moe.is_some()
    }
}
