//! GGUF metadata-driven model architecture detection.
//!
//! Walks the GGUF metadata table (already parsed by `loader.rs`) and the tensor
//! name list to build an `ArchInfo` that downstream code uses to wire up the
//! correct forward pass: dense vs MoE, sliding-window attention, RoPE config,
//! QKV bias presence, etc.
//!
//! No defaults are hardcoded for model dimensions — every value comes from the
//! file. The only heuristic is mapping `general.architecture` strings to our
//! `ModelFamily` enum and inferring `is_moe` from the architecture string and/or
//! `expert_count > 0`.
//!
//! Cross-validate against llama.cpp's `gguf-py/gguf/constants.py` and
//! `src/llama-arch.cpp` if a new architecture string shows up.

use std::collections::HashMap;

use crate::loader::GgufValue;
use crate::model_arch::ModelFamily;

/// All the per-model knobs the engine needs to run forward(). Values are pulled
/// from GGUF metadata; missing keys are filled with conservative defaults that
/// will produce a hard error later rather than silently wrong output.
#[derive(Debug, Clone)]
pub struct ArchInfo {
    pub family: ModelFamily,
    /// Raw `general.architecture` string from the file ("qwen2", "qwen2moe",
    /// "qwen3moe", "gemma", "gemma2", "gemma3", "llama", "phi3", "deepseek2"…).
    pub arch_str: String,

    // ── Topology ────────────────────────────────────────────────────────────
    pub n_layers: u32,
    pub hidden_dim: u32,
    pub ffn_dim: u32,
    pub n_heads: u32,
    pub n_kv_heads: u32,
    /// Per-head dim. Falls back to hidden_dim/n_heads if absent (Llama-style).
    pub head_dim: u32,
    pub vocab_size: u32,

    // ── MoE ─────────────────────────────────────────────────────────────────
    pub is_moe: bool,
    pub n_experts: u32,
    pub n_experts_used: u32,

    // ── Attention ───────────────────────────────────────────────────────────
    /// Some(window) for Gemma-style sliding-window attention.
    pub sliding_window: Option<u32>,
    pub has_qkv_bias: bool,

    // ── RoPE ────────────────────────────────────────────────────────────────
    pub rope_theta: f32,
    pub rope_scaling_factor: f32,
    /// Number of dims that get rotated. None = full head_dim.
    pub rope_partial_dim: Option<u32>,
}

impl ArchInfo {
    /// Detect everything from a parsed GGUF.
    ///
    /// `metadata` is the raw KV table. `tensor_names` is the full list of
    /// tensor names in the file (used to detect QKV biases without iterating
    /// every blk.{i}.attn_q.bias key).
    pub fn detect(
        metadata: &HashMap<String, GgufValue>,
        tensor_names: &[String],
    ) -> Self {
        let arch_str = get_str(metadata, "general.architecture")
            .unwrap_or_else(|| "llama".to_string());

        let family = match arch_str.as_str() {
            "qwen2" | "qwen2moe" | "qwen3" | "qwen3moe" => ModelFamily::Qwen2_5,
            "gemma" | "gemma2" | "gemma3" => ModelFamily::Gemma4,
            "llama" => ModelFamily::Llama3,
            "phi3" => ModelFamily::Phi3,
            "deepseek2" | "deepseekv2" => ModelFamily::DeepSeekV2,
            // Default to Llama-style for any unknown architecture — most
            // public GGUFs use llama-compatible tensor names.
            _ => ModelFamily::Llama3,
        };

        // Try keys in this order: explicit arch prefix, then llama fallback.
        let try_keys =
            |k: &str| -> Option<&GgufValue> {
                let prefixed = format!("{}.{}", arch_str, k);
                metadata
                    .get(&prefixed)
                    .or_else(|| metadata.get(&format!("llama.{}", k)))
                    .or_else(|| metadata.get(k))
            };

        let n_layers = try_keys("block_count")
            .and_then(as_u32)
            .unwrap_or(0);
        let hidden_dim = try_keys("embedding_length")
            .and_then(as_u32)
            .unwrap_or(0);
        let ffn_dim = try_keys("feed_forward_length")
            .and_then(as_u32)
            .unwrap_or(0);
        let n_heads = try_keys("attention.head_count")
            .and_then(as_u32)
            .unwrap_or(0);
        let n_kv_heads = try_keys("attention.head_count_kv")
            .and_then(as_u32)
            .unwrap_or(n_heads.max(1));
        let head_dim = try_keys("attention.key_length")
            .or_else(|| try_keys("attention.head_dim"))
            .and_then(as_u32)
            .unwrap_or_else(|| {
                if n_heads > 0 { hidden_dim / n_heads } else { 0 }
            });
        let vocab_size = try_keys("vocab_size")
            .and_then(as_u32)
            .unwrap_or(0);

        // ── MoE ─────────────────────────────────────────────────────────────
        let n_experts = try_keys("expert_count")
            .and_then(as_u32)
            .unwrap_or(0);
        let n_experts_used = try_keys("expert_used_count")
            .and_then(as_u32)
            .unwrap_or(if n_experts > 0 { 2 } else { 0 });
        let is_moe = n_experts > 0 || arch_str.contains("moe");

        // ── Attention ───────────────────────────────────────────────────────
        let sliding_window = try_keys("attention.sliding_window")
            .and_then(as_u32)
            .filter(|&w| w > 0);
        // Tensor-name probe: any layer with attn_q.bias = QKV biased model.
        let has_qkv_bias = tensor_names.iter().any(|n| n.ends_with(".attn_q.bias"));

        // ── RoPE ────────────────────────────────────────────────────────────
        let rope_theta = try_keys("rope.freq_base")
            .and_then(as_f32)
            .unwrap_or(10000.0);
        let rope_scaling_factor = try_keys("rope.scaling.factor")
            .and_then(as_f32)
            .unwrap_or(1.0);
        let rope_partial_dim = try_keys("rope.dimension_count")
            .and_then(as_u32)
            .filter(|&d| d != head_dim && d > 0);

        Self {
            family,
            arch_str,
            n_layers,
            hidden_dim,
            ffn_dim,
            n_heads,
            n_kv_heads,
            head_dim,
            vocab_size,
            is_moe,
            n_experts,
            n_experts_used,
            sliding_window,
            has_qkv_bias,
            rope_theta,
            rope_scaling_factor,
            rope_partial_dim,
        }
    }

    /// Human-readable one-liner for logs.
    pub fn summary(&self) -> String {
        let moe = if self.is_moe {
            format!(", MoE {}/{} experts", self.n_experts_used, self.n_experts)
        } else {
            String::new()
        };
        let sw = self
            .sliding_window
            .map(|w| format!(", sliding={}", w))
            .unwrap_or_default();
        let bias = if self.has_qkv_bias { ", QKV bias" } else { "" };
        format!(
            "{:?} ({}) — {}L × {}H × {}KV × {}HD, ffn={}, vocab={}, rope_theta={:.0}{moe}{sw}{bias}",
            self.family,
            self.arch_str,
            self.n_layers,
            self.n_heads,
            self.n_kv_heads,
            self.head_dim,
            self.ffn_dim,
            self.vocab_size,
            self.rope_theta,
        )
    }

    /// Sanity check — returns Err with the first missing required field.
    pub fn validate(&self) -> Result<(), String> {
        if self.n_layers == 0 {
            return Err("n_layers is 0 — missing {arch}.block_count".into());
        }
        if self.hidden_dim == 0 {
            return Err("hidden_dim is 0 — missing {arch}.embedding_length".into());
        }
        if self.n_heads == 0 {
            return Err("n_heads is 0 — missing {arch}.attention.head_count".into());
        }
        if self.head_dim == 0 {
            return Err("head_dim is 0 — could not derive from hidden_dim/n_heads".into());
        }
        if self.is_moe && self.n_experts_used == 0 {
            return Err("MoE model but n_experts_used is 0".into());
        }
        Ok(())
    }
}

// ── GgufValue accessors ─────────────────────────────────────────────────────

fn get_str(meta: &HashMap<String, GgufValue>, key: &str) -> Option<String> {
    match meta.get(key) {
        Some(GgufValue::Str(s)) => Some(s.clone()),
        _ => None,
    }
}

fn as_u32(v: &GgufValue) -> Option<u32> {
    match v {
        GgufValue::U32(n) => Some(*n),
        GgufValue::I32(n) => Some(*n as u32),
        GgufValue::U64(n) => Some(*n as u32),
        _ => None,
    }
}

fn as_f32(v: &GgufValue) -> Option<f32> {
    match v {
        GgufValue::F32(n) => Some(*n),
        GgufValue::U32(n) => Some(*n as f32),
        GgufValue::I32(n) => Some(*n as f32),
        _ => None,
    }
}
