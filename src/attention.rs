// src/attention.rs
// NOTE: Requires wgpu crate in Cargo.toml to compile.
// TODO: Fix bytemuck casts and buffer creation once wgpu is added.

use std::sync::Arc;
use crate::arena::InferenceArena;

#[derive(Debug)]
pub enum AttentionError {
    WgpuDeviceMiss,
    PipelineCreationFailure,
    BufferLimitExceeded,
}

pub struct AttentionConfig {
    pub num_heads: usize,
    pub num_kv_heads: usize,
    pub head_dim: usize,
    pub max_seq_len: usize,
    pub rope_theta: f32,
}

/// Appends high-precision Rotary Position Embeddings (RoPE) into vector arrays.
/// This is the CPU-side RoPE that runs on the Xeons (f64 precision).
pub fn apply_rope_inplace(
    q_slice: &mut [f64],
    k_slice: &mut [f64],
    seq_idx: usize,
    head_dim: usize,
    rope_theta: f32,
) {
    for i in (0..head_dim).step_by(2) {
        let theta_base = 1.0 / (rope_theta.powf((i as f32) / (head_dim as f32)));
        let m_theta = (seq_idx as f64) * (theta_base as f64);
        let cos_val = m_theta.cos();
        let sin_val = m_theta.sin();

        // Interleaved coordinate vector rotations
        let q0 = q_slice[i];
        let q1 = q_slice[i + 1];
        q_slice[i] = (q0 * cos_val) - (q1 * sin_val);
        q_slice[i + 1] = (q0 * sin_val) + (q1 * cos_val);

        let k0 = k_slice[i];
        let k1 = k_slice[i + 1];
        k_slice[i] = (k0 * cos_val) - (k1 * sin_val);
        k_slice[i + 1] = (k0 * sin_val) + (k1 * cos_val);
    }
}

/// HIGH-PRECISION ROOT MEAN SQUARE NORMALIZATION (RMSNorm)
/// Runs at f64 to isolate small parameter pulls out of noise boundaries.
pub fn rmsnorm_inplace(x: &mut [f64], weight: &[f64], epsilon: f64) {
    let hidden_dim = x.len();

    let mut sum_squares: f64 = 0.0;
    for i in 0..hidden_dim {
        sum_squares += x[i] * x[i];
    }

    let mean = sum_squares / (hidden_dim as f64);
    let variance_inv = 1.0 / (mean + epsilon).sqrt();

    for i in 0..hidden_dim {
        x[i] = x[i] * variance_inv * weight[i];
    }
}

/// SwiGLU GATING ACTIVATION
/// Maps high-frequency activation thresholds without generating memory drops.
pub fn swiglu_block(output: &mut [f64], gate: &[f64], up: &[f64]) {
    for i in 0..output.len() {
        // Silu: x * sigmoid(x)
        let gate_val = gate[i];
        let sigmoid_val = 1.0 / (1.0 + (-gate_val).exp());
        let silu_activation = gate_val * sigmoid_val;

        // SwiGLU fusion
        output[i] = silu_activation * up[i];
    }
}
