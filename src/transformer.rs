// src/transformer.rs
//! Transformer forward pass with KV cache for multi-token attention.
//!
//! CPU-only implementation. GPU dispatch via wgpu replaces the inner matmul
//! calls once coherent text is confirmed.

use std::sync::Arc;
use crate::arena::InferenceArena;
use crate::bridge;
use crate::gpu_context::GpuContext;
use crate::kv_cache::KvCache;
use crate::loader::ModelWeights;
use crate::matmul;
use crate::weight_cache::WeightCache;

pub struct TransformerConfig {
    pub vocab_size: usize,
    pub hidden_size: usize,
    pub intermediate_size: usize,
    pub num_layers: usize,
    pub num_heads: usize,
    pub num_kv_heads: usize,
    pub head_dim: usize,
    pub max_seq_len: usize,
    pub rope_theta: f32,
    pub rms_norm_eps: f64,
}

pub struct TransformerDecoder {
    pub config: TransformerConfig,
    pub arena: Arc<InferenceArena>,
    pub weight_cache: Option<Arc<WeightCache>>,
    pub gpu: Option<Arc<GpuContext>>,
}

impl TransformerDecoder {
    pub fn new(config: TransformerConfig, arena: Arc<InferenceArena>) -> Self {
        Self { config, arena, weight_cache: None, gpu: None }
    }

    pub fn with_weight_cache(mut self, cache: Arc<WeightCache>) -> Self {
        self.weight_cache = Some(cache);
        self
    }

    pub fn with_gpu(mut self, gpu: Arc<GpuContext>) -> Self {
        self.gpu = Some(gpu);
        self
    }

    /// Matmul dispatch — uses GPU if available, otherwise CPU
    fn do_matmul(&self, a: &[f32], b_t: &[f32], m: usize, k: usize, n: usize) -> Vec<f32> {
        if let Some(ref gpu) = self.gpu {
            gpu.matmul_gpu(a, b_t, m, k, n)
        } else {
            matmul::matmul_f32_transposed_b(a, b_t, m, k, n)
        }
    }

    /// Run a single-token forward pass with KV cache.
    /// The cache stores K/V from all previous positions so attention has full context.
    pub fn forward(
        &self,
        hidden_state: &mut [f32],
        position_idx: usize,
        weights: &ModelWeights,
        kv_cache: &mut KvCache,
    ) -> Vec<f32> {
        let h = self.config.hidden_size;
        let head_dim = self.config.head_dim;
        let n_heads = self.config.num_heads;
        let n_kv_heads = self.config.num_kv_heads;
        let inter = self.config.intermediate_size;
        let heads_per_kv = n_heads / n_kv_heads;

        let mut residual = vec![0.0f32; h];

        for layer_idx in 0..self.config.num_layers {
            residual.copy_from_slice(hidden_state);

            // --- Pre-attention RMSNorm ---
            let norm_name = format!("blk.{}.attn_norm.weight", layer_idx);
            let norm_w = self.load_tensor_f32(weights, &norm_name, h);
            rmsnorm_f32(hidden_state, &norm_w, self.config.rms_norm_eps as f32);

            // --- Q/K/V Projections ---
            let q_dim = n_heads * head_dim;
            let kv_dim = n_kv_heads * head_dim;

            // GGUF stores weights in column-major (transposed relative to row-major).
            // Shape [K, M] in GGUF = [in_dim, out_dim] column-major = B^T for matmul.
            // Use matmul_f32_transposed_b(input, weight, m=1, k=in_dim, n=out_dim)
            // which computes input[1,k] × weight^T → output[1,n]

            let q_name = format!("blk.{}.attn_q.weight", layer_idx);
            let q_weight = self.load_tensor_f32(weights, &q_name, q_dim * h);
            let mut q = self.do_matmul(hidden_state, &q_weight, 1, h, q_dim);

            let k_name = format!("blk.{}.attn_k.weight", layer_idx);
            let k_weight = self.load_tensor_f32(weights, &k_name, kv_dim * h);
            let mut k = self.do_matmul(hidden_state, &k_weight, 1, h, kv_dim);

            let v_name = format!("blk.{}.attn_v.weight", layer_idx);
            let v_weight = self.load_tensor_f32(weights, &v_name, kv_dim * h);
            let mut v = self.do_matmul(hidden_state, &v_weight, 1, h, kv_dim);

            // --- Apply Q/K/V Attention Biases (Qwen2.5 requires these) ---
            let q_bias_name = format!("blk.{}.attn_q.bias", layer_idx);
            let q_bias = self.load_tensor_f32(weights, &q_bias_name, q_dim);
            for i in 0..q_dim {
                q[i] += q_bias[i];
            }

            let k_bias_name = format!("blk.{}.attn_k.bias", layer_idx);
            let k_bias = self.load_tensor_f32(weights, &k_bias_name, kv_dim);
            for i in 0..kv_dim {
                k[i] += k_bias[i];
            }

            let v_bias_name = format!("blk.{}.attn_v.bias", layer_idx);
            let v_bias = self.load_tensor_f32(weights, &v_bias_name, kv_dim);
            for i in 0..kv_dim {
                v[i] += v_bias[i];
            }

            // --- Apply RoPE to Q and K ---
            let mut q_rope = q;
            let mut k_rope = k.clone();
            apply_rope_f32(&mut q_rope, n_heads, head_dim, position_idx, self.config.rope_theta);
            apply_rope_f32(&mut k_rope, n_kv_heads, head_dim, position_idx, self.config.rope_theta);

            // --- Store K/V in cache ---
            kv_cache.push(layer_idx, k_rope, v);

            // --- Multi-token attention with KV cache ---
            let cached_keys = kv_cache.get_keys(layer_idx);
            let cached_values = kv_cache.get_values(layer_idx);
            let seq_len = cached_keys.len(); // includes current token

            let mut attn_output = vec![0.0f32; q_dim];
            let scale = 1.0f32 / (head_dim as f32).sqrt();

            // GQA attention: each query head attends to its shared KV head
            for head in 0..n_heads {
                let kv_head = head / heads_per_kv;
                let q_offset = head * head_dim;

                // Compute attention scores against all cached K vectors
                let mut scores = Vec::with_capacity(seq_len);
                let mut max_score = f32::NEG_INFINITY;

                for pos in 0..seq_len {
                    let k_vec = &cached_keys[pos];
                    let k_offset = kv_head * head_dim;
                    let mut dot = 0.0f32;
                    for d in 0..head_dim {
                        dot += q_rope[q_offset + d] * k_vec[k_offset + d];
                    }
                    let score = dot * scale;
                    if score > max_score {
                        max_score = score;
                    }
                    scores.push(score);
                }

                // Softmax
                let mut sum_exp = 0.0f32;
                for s in scores.iter_mut() {
                    *s = (*s - max_score).exp();
                    sum_exp += *s;
                }

                // Weighted sum of V vectors
                let v_offset = kv_head * head_dim;
                for d in 0..head_dim {
                    let mut acc = 0.0f32;
                    for pos in 0..seq_len {
                        acc += scores[pos] * cached_values[pos][v_offset + d];
                    }
                    attn_output[q_offset + d] = acc / sum_exp;
                }
            }

            // --- O projection ---
            let o_name = format!("blk.{}.attn_output.weight", layer_idx);
            let o_weight = self.load_tensor_f32(weights, &o_name, h * q_dim);
            let o_out = self.do_matmul(&attn_output, &o_weight, 1, q_dim, h);

            // Add residual
            for i in 0..h {
                hidden_state[i] = residual[i] + o_out[i];
            }

            // Save residual for FFN
            residual.copy_from_slice(hidden_state);

            // --- Post-attention RMSNorm ---
            let post_norm_name = format!("blk.{}.ffn_norm.weight", layer_idx);
            let post_norm_w = self.load_tensor_f32(weights, &post_norm_name, h);
            rmsnorm_f32(hidden_state, &post_norm_w, self.config.rms_norm_eps as f32);

            // --- FFN (SwiGLU) ---
            let gate_name = format!("blk.{}.ffn_gate.weight", layer_idx);
            let up_name = format!("blk.{}.ffn_up.weight", layer_idx);
            let down_name = format!("blk.{}.ffn_down.weight", layer_idx);

            // Log FFN shapes on layer 0 to verify intermediate_size
            if layer_idx == 0 {
                if let Some(r) = weights.tensors.get(&gate_name) {
                    tracing::info!("Layer 0 FFN gate shape: {:?}", r.shape);
                }
                if let Some(r) = weights.tensors.get(&down_name) {
                    tracing::info!("Layer 0 FFN down shape: {:?}", r.shape);
                }
            }

            let gate_weight = self.load_tensor_f32(weights, &gate_name, inter * h);
            let gate = self.do_matmul(hidden_state, &gate_weight, 1, h, inter);

            let up_weight = self.load_tensor_f32(weights, &up_name, inter * h);
            let up = self.do_matmul(hidden_state, &up_weight, 1, h, inter);

            // SwiGLU: silu(gate) * up
            let mut ffn_hidden = vec![0.0f32; inter];
            for i in 0..inter {
                let g = gate[i];
                let silu = g * (1.0 / (1.0 + (-g).exp()));
                ffn_hidden[i] = silu * up[i];
            }

            let down_weight = self.load_tensor_f32(weights, &down_name, h * inter);
            let down_out = self.do_matmul(&ffn_hidden, &down_weight, 1, inter, h);

            // Add residual
            for i in 0..h {
                hidden_state[i] = residual[i] + down_out[i];
            }
        }

        // --- Final RMSNorm ---
        let final_norm = self.load_tensor_f32(weights, "output_norm.weight", h);
        rmsnorm_f32(hidden_state, &final_norm, self.config.rms_norm_eps as f32);

        // --- LM Head ---
        let lm_head = self.load_tensor_f32(weights, "output.weight", self.config.vocab_size * h);
        self.do_matmul(hidden_state, &lm_head, 1, h, self.config.vocab_size)
    }

    fn load_tensor_f32(&self, weights: &ModelWeights, name: &str, expected_elements: usize) -> Vec<f32> {
        // Fast path: use pre-dequantized weight cache if available
        if let Some(ref cache) = self.weight_cache {
            if let Some(data) = cache.get(name) {
                if data.len() >= expected_elements {
                    return data[..expected_elements].to_vec();
                } else {
                    let mut v = data.to_vec();
                    v.resize(expected_elements, 0.0);
                    return v;
                }
            }
        }

        // Slow path: dequantize from GGUF bytes (used when no cache)
        if let Some(bytes) = weights.tensor_bytes(name) {
            let region = weights.tensors.get(name).unwrap();
            let n_elements: usize = region.shape.iter().product();
            let mut data = bridge::dequantize_tensor(bytes, region.quant_type, n_elements);
            data.resize(expected_elements, 0.0);
            data
        } else {
            tracing::warn!("Tensor not found: {} — using zeros", name);
            vec![0.0f32; expected_elements]
        }
    }
}

fn rmsnorm_f32(x: &mut [f32], weight: &[f32], eps: f32) {
    let n = x.len();
    let mut sum_sq = 0.0f32;
    for i in 0..n {
        sum_sq += x[i] * x[i];
    }
    let rms = ((sum_sq / n as f32) + eps).sqrt();
    let inv_rms = 1.0 / rms;
    for i in 0..n {
        x[i] = x[i] * inv_rms * weight[i.min(weight.len() - 1)];
    }
}

fn apply_rope_f32(x: &mut [f32], n_heads: usize, head_dim: usize, pos: usize, theta: f32) {
    for head in 0..n_heads {
        let offset = head * head_dim;
        for i in (0..head_dim).step_by(2) {
            let freq = 1.0f32 / theta.powf(i as f32 / head_dim as f32);
            let angle = pos as f32 * freq;
            let cos_val = angle.cos();
            let sin_val = angle.sin();

            let x0 = x[offset + i];
            let x1 = x[offset + i + 1];
            x[offset + i] = x0 * cos_val - x1 * sin_val;
            x[offset + i + 1] = x0 * sin_val + x1 * cos_val;
        }
    }
}
