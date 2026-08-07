//! Transformer forward pass — the complete layer execution loop.
//!
//! Sequences all GPU shader dispatches for one transformer layer:
//!   RMSNorm → QKV Projection → RoPE → Attention → Residual Add →
//!   RMSNorm → Gate/Up Projection → SwiGLU → Down Projection → Residual Add
//!
//! Supports both single-buffer and chunked weight tensors transparently.
//! Designed for autoregressive decode (one token at a time against KV cache).

use bytemuck::{Pod, Zeroable};
use crate::shader_ops::{DequantPipeline, RmsNormPipeline, RmsNormParams};
use crate::tensor_chunker::ChunkedMatmulPipeline;
use crate::tensor_loader_safe::TensorRegistry;

/// All pipelines needed for one transformer layer.
pub struct LayerPipelines {
    pub rmsnorm: RmsNormPipeline,
    pub chunked_matmul: ChunkedMatmulPipeline,
    pub rope: wgpu::ComputePipeline,
    pub rope_bgl: wgpu::BindGroupLayout,
    pub attention: wgpu::ComputePipeline,
    pub attention_bgl: wgpu::BindGroupLayout,
    pub softmax: wgpu::ComputePipeline,
    pub softmax_bgl: wgpu::BindGroupLayout,
    pub swiglu: wgpu::ComputePipeline,
    pub swiglu_bgl: wgpu::BindGroupLayout,
    pub add: wgpu::ComputePipeline,
    pub add_bgl: wgpu::BindGroupLayout,
    pub av: wgpu::ComputePipeline,
    pub av_bgl: wgpu::BindGroupLayout,
    pub dequant_q6k: crate::shader_ops::DequantQ6KPipeline,
    pub transpose: wgpu::ComputePipeline,
    pub transpose_bgl: wgpu::BindGroupLayout,
    pub matvec: wgpu::ComputePipeline,
    pub matvec_bgl: wgpu::BindGroupLayout,
    pub matvec_bias: wgpu::ComputePipeline,
    pub matvec_bias_bgl: wgpu::BindGroupLayout,
}

/// Uniform params for RoPE dispatch.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct RoPEParams {
    pub head_dim: u32,
    pub pos: u32,
    pub n_heads: u32,
    pub _pad: u32,
}

/// Uniform params for attention score computation.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct AttentionParams {
    pub kv_len: u32,
    pub head_dim: u32,
    pub cur_pos: u32,
    pub scale: f32,
}

/// Uniform params for softmax.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct SoftmaxParams {
    pub seq_len: u32,
    pub _pad0: u32,
    pub _pad1: u32,
    pub _pad2: u32,
}

/// Uniform params for SwiGLU.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct SwiGLUParams {
    pub n_elements_vec4: u32,
    pub _pad0: u32,
    pub _pad1: u32,
    pub _pad2: u32,
}

/// Uniform params for elementwise add.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct AddParams {
    pub n_elements: u32,
    pub _pad0: u32,
    pub _pad1: u32,
    pub _pad2: u32,
}

/// Per-layer weight buffer references.
pub struct LayerWeights {
    pub attn_norm: wgpu::Buffer,    // RMSNorm weight [hidden_dim]
    pub ffn_norm: wgpu::Buffer,     // RMSNorm weight [hidden_dim]
    pub q_proj: wgpu::Buffer,       // [hidden_dim × hidden_dim]
    pub k_proj: wgpu::Buffer,       // [hidden_dim × kv_dim]
    pub v_proj: wgpu::Buffer,       // [hidden_dim × kv_dim]
    pub o_proj: wgpu::Buffer,       // [hidden_dim × hidden_dim]
    pub gate_proj: wgpu::Buffer,    // [intermediate × hidden_dim]
    pub up_proj: wgpu::Buffer,      // [intermediate × hidden_dim]
    pub down_proj: wgpu::Buffer,    // [hidden_dim × intermediate]
    // Qwen-specific biases (optional — None if model doesn't have them)
    pub q_bias: Option<wgpu::Buffer>,   // [hidden_dim]
    pub k_bias: Option<wgpu::Buffer>,   // [kv_dim]
    pub v_bias: Option<wgpu::Buffer>,   // [kv_dim]
}

/// KV cache for one layer (ring buffer on GPU).
pub struct KVCache {
    pub key_cache: wgpu::Buffer,    // [max_seq × n_kv_heads × head_dim]
    pub value_cache: wgpu::Buffer,  // [max_seq × n_kv_heads × head_dim]
    pub current_len: u32,
    pub max_seq: u32,
}

/// Model configuration.
#[derive(Debug, Clone)]
pub struct ModelConfig {
    pub hidden_dim: u32,
    pub intermediate_dim: u32,
    pub n_heads: u32,
    pub n_kv_heads: u32,
    pub head_dim: u32,
    pub n_layers: u32,
    pub vocab_size: u32,
    pub max_seq_len: u32,
    pub rms_norm_eps: f32,
}

/// Execute one transformer layer (autoregressive decode, single token).
///
/// Optimized submit pattern for P100 Vulkan: 6 submits per layer instead of 15-20.
///
/// P100 Vulkan requires a submit boundary whenever op B reads a buffer written by op A.
/// Ops that write to DIFFERENT buffers from the same source can be batched safely.
///
/// Submit groups:
///   S1: attn_rmsnorm → normed
///   S2: Q_proj + K_proj + V_proj (all read normed, write different bufs)
///   S3: Q_bias + K_bias + V_bias + RoPE_Q + RoPE_K + KV_cache_write
///       (biases read/write same buf but different from each other; RoPE reads post-bias)
///       NOTE: biases are in-place so need their own submit after projections.
///       Actual: S3a=biases, S3b=RoPE+KV_write
///   S4: attention (reads q/k/v, writes attn_out) — handled by attention_dispatch
///   S5: O_proj + attn_residual (O reads attn_out→attn_proj; residual reads both)
///       NOTE: residual reads attn_proj which O writes → need boundary.
///       Actual: S5a=O_proj, S5b=attn_residual
///   S6: ffn_rmsnorm → ffn_normed
///   S7: gate_proj + up_proj (both read ffn_normed, write different bufs)
///   S8: swiglu + down_proj + ffn_residual
///       NOTE: swiglu reads gate/up → down reads swiglu output → need boundaries.
///       Actual: S8a=swiglu, S8b=down_proj, S8c=ffn_residual (caller submits)
///
/// Total: ~8 submits vs 15-20 before. ~2x speedup on submit overhead alone.
pub fn execute_layer(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    config: &ModelConfig,
    weights: &LayerWeights,
    kv_cache: &mut KVCache,
    hidden_state: &wgpu::Buffer,
    pos: u32,
) {
    let hidden_bytes       = (config.hidden_dim * 4) as u64;
    let kv_dim_bytes       = (config.n_kv_heads * config.head_dim * 4) as u64;
    let intermediate_bytes = (config.intermediate_dim * 4) as u64;

    // Pre-allocate all temp buffers up front (will be replaced by ScratchBuffers later)
    let normed        = create_temp_buffer(device, "normed",     hidden_bytes);
    let q_buf         = create_temp_buffer(device, "q",          hidden_bytes);
    let k_buf         = create_temp_buffer(device, "k",          kv_dim_bytes);
    let v_buf         = create_temp_buffer(device, "v",          kv_dim_bytes);
    let attn_output   = create_temp_buffer(device, "attn_out",   hidden_bytes);
    let attn_proj     = create_temp_buffer(device, "attn_proj",  hidden_bytes);
    let residual_tmp  = create_temp_buffer(device, "res_tmp",    hidden_bytes);
    let ffn_normed    = create_temp_buffer(device, "ffn_normed", hidden_bytes);
    let gate_out      = create_temp_buffer(device, "gate",       intermediate_bytes);
    let up_out        = create_temp_buffer(device, "up",         intermediate_bytes);
    let ffn_activated = create_temp_buffer(device, "ffn_act",    intermediate_bytes);
    let ffn_out       = create_temp_buffer(device, "ffn_out",    hidden_bytes);

    // Flush caller's pending work
    queue.submit(std::iter::once(
        std::mem::replace(encoder, device.create_command_encoder(
            &wgpu::CommandEncoderDescriptor { label: Some("layer") }
        )).finish()
    ));

    // ── S1: Attn RMSNorm ────────────────────────────────────────────────────
    // hidden_state → normed  (boundary: normed now ready)
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s1_norm") });
        pipelines.rmsnorm.dispatch(device, queue, &mut enc,
            hidden_state, &weights.attn_norm, &normed,
            config.hidden_dim, 1, config.rms_norm_eps);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S2: Q + K + V projections ───────────────────────────────────────────
    // All read normed, write to different output buffers — safe to batch.
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s2_qkv") });
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &normed, &weights.q_proj, &q_buf,
            1, config.hidden_dim, config.hidden_dim);
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &normed, &weights.k_proj, &k_buf,
            1, config.hidden_dim, config.n_kv_heads * config.head_dim);
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &normed, &weights.v_proj, &v_buf,
            1, config.hidden_dim, config.n_kv_heads * config.head_dim);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S3: Biases (in-place add via residual_tmp) ──────────────────────────
    // Each bias reads/writes its own buffer. They're independent of each other
    // but each is a RAW on its own buffer, so batch all three in one encoder:
    // q_buf → residual_tmp → q_buf  (copy back in same encoder is safe on P100
    // because copy_buffer_to_buffer is ordered after the compute pass that wrote
    // residual_tmp within the same encoder submission).
    let has_bias = weights.q_bias.is_some() || weights.k_bias.is_some() || weights.v_bias.is_some();
    if has_bias {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s3_bias") });
        if let Some(ref qb) = weights.q_bias {
            dispatch_add(device, queue, &mut enc, pipelines, &q_buf, qb, &residual_tmp, config.hidden_dim);
            enc.copy_buffer_to_buffer(&residual_tmp, 0, &q_buf, 0, hidden_bytes);
        }
        if let Some(ref kb) = weights.k_bias {
            dispatch_add(device, queue, &mut enc, pipelines, &k_buf, kb, &residual_tmp, config.n_kv_heads * config.head_dim);
            enc.copy_buffer_to_buffer(&residual_tmp, 0, &k_buf, 0, kv_dim_bytes);
        }
        if let Some(ref vb) = weights.v_bias {
            dispatch_add(device, queue, &mut enc, pipelines, &v_buf, vb, &residual_tmp, config.n_kv_heads * config.head_dim);
            enc.copy_buffer_to_buffer(&residual_tmp, 0, &v_buf, 0, kv_dim_bytes);
        }
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S4: RoPE + KV cache write ────────────────────────────────────────────
    // RoPE reads q_buf/k_buf (post-bias), writes in-place via residual_tmp.
    // KV cache write copies k_buf/v_buf to cache. All independent outputs.
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s4_rope_kv") });
        dispatch_rope(device, queue, &mut enc, pipelines, &q_buf, config.head_dim, pos, config.n_heads);
        dispatch_rope(device, queue, &mut enc, pipelines, &k_buf, config.head_dim, pos, config.n_kv_heads);
        let k_offset = (pos as u64) * (config.n_kv_heads as u64) * (config.head_dim as u64) * 4;
        enc.copy_buffer_to_buffer(&k_buf, 0, &kv_cache.key_cache,   k_offset, kv_dim_bytes);
        enc.copy_buffer_to_buffer(&v_buf, 0, &kv_cache.value_cache, k_offset, kv_dim_bytes);
        queue.submit(std::iter::once(enc.finish()));
    }
    kv_cache.current_len = pos + 1;

    // ── S5: Multi-head attention ─────────────────────────────────────────────
    // Reads q_buf + KV cache, writes attn_output.
    // attention_dispatch handles its own submits internally.
    crate::attention_dispatch::dispatch_multihead_attention_split(
        device, queue,
        &pipelines.attention, &pipelines.attention_bgl,
        &pipelines.softmax,   &pipelines.softmax_bgl,
        &pipelines.av,        &pipelines.av_bgl,
        &q_buf, &kv_cache.key_cache, &kv_cache.value_cache, &attn_output,
        config.n_heads, config.n_kv_heads, config.head_dim, pos,
    );

    // ── S6: O projection ────────────────────────────────────────────────────
    // attn_output → attn_proj
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s6_oproj") });
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &attn_output, &weights.o_proj, &attn_proj,
            1, config.hidden_dim, config.hidden_dim);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S7: Attention residual ───────────────────────────────────────────────
    // hidden_state + attn_proj → residual_tmp → hidden_state
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s7_attn_res") });
        dispatch_add(device, queue, &mut enc, pipelines,
            hidden_state, &attn_proj, &residual_tmp, config.hidden_dim);
        enc.copy_buffer_to_buffer(&residual_tmp, 0, hidden_state, 0, hidden_bytes);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S8: FFN RMSNorm ──────────────────────────────────────────────────────
    // hidden_state → ffn_normed
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s8_ffn_norm") });
        pipelines.rmsnorm.dispatch(device, queue, &mut enc,
            hidden_state, &weights.ffn_norm, &ffn_normed,
            config.hidden_dim, 1, config.rms_norm_eps);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S9: Gate + Up projections ────────────────────────────────────────────
    // Both read ffn_normed, write to different buffers — safe to batch.
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s9_gate_up") });
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &ffn_normed, &weights.gate_proj, &gate_out,
            1, config.hidden_dim, config.intermediate_dim);
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &ffn_normed, &weights.up_proj, &up_out,
            1, config.hidden_dim, config.intermediate_dim);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S10: SwiGLU ──────────────────────────────────────────────────────────
    // gate_out + up_out → ffn_activated
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s10_swiglu") });
        dispatch_swiglu(device, queue, &mut enc, pipelines,
            &gate_out, &up_out, &ffn_activated, config.intermediate_dim);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S11: Down projection ─────────────────────────────────────────────────
    // ffn_activated → ffn_out
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("s11_down") });
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &ffn_activated, &weights.down_proj, &ffn_out,
            1, config.intermediate_dim, config.hidden_dim);
        queue.submit(std::iter::once(enc.finish()));
    }

    // ── S12: FFN residual (caller submits) ───────────────────────────────────
    // hidden_state + ffn_out → residual_tmp → hidden_state
    dispatch_add(device, queue, encoder, pipelines,
        hidden_state, &ffn_out, &residual_tmp, config.hidden_dim);
    encoder.copy_buffer_to_buffer(&residual_tmp, 0, hidden_state, 0, hidden_bytes);
    // Caller submits encoder
}

pub fn execute_layer_diagnostic(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    pipelines: &LayerPipelines,
    config: &ModelConfig,
    weights: &LayerWeights,
    hidden_state: &wgpu::Buffer,
) {
    let h = config.hidden_dim;
    let i = config.intermediate_dim;
    let eps = config.rms_norm_eps;
    let hidden_bytes = (h * 4) as u64;
    let intermediate_bytes = (i * 4) as u64;

    tracing::info!("═══ FFN DIAGNOSTIC: Step-by-step with readback ═══");
    tracing::info!("  hidden_dim={}, intermediate_dim={}, eps={}", h, i, eps);

    // Python reference values for token 9707 through layer 0 FFN:
    let ref_normed = [-0.03002f32, 0.18692, 0.48619, -1.04201];
    let ref_gate = [-0.15846f32, 0.49651, -0.12629, 0.01424];
    let ref_up = [0.18722f32, -1.51797, 0.37551, -0.11288];
    let ref_swiglu = [-0.01366f32, -0.46852, -0.02222, -0.00081];
    let ref_down = [-0.15616f32, -0.06285, -0.41493, 0.24988];
    let ref_residual = [-0.15722f32, -0.05969, -0.40335, 0.23199];

    // Step 0: Read input hidden state
    let input_vals = readback_f32(device, queue, hidden_state, 8);
    tracing::info!("  INPUT hidden_state[0:8]: {:?}", input_vals);

    // Step 1: RMSNorm with ffn_norm weight
    let ffn_normed = create_temp_buffer(device, "diag_ffn_normed", hidden_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        pipelines.rmsnorm.dispatch(
            device, queue, &mut enc,
            hidden_state, &weights.ffn_norm, &ffn_normed,
            h, 1, eps,
        );
        queue.submit(std::iter::once(enc.finish()));
    }
    let normed_vals = readback_f32(device, queue, &ffn_normed, 4);
    let normed_ok = normed_vals.iter().zip(ref_normed.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] FFN RMSNorm  | Got: {:?} | Ref: {:?}",
        if normed_ok { "PASS" } else { "FAIL" }, normed_vals, ref_normed);

    // Step 2: Gate projection
    let gate_out = create_temp_buffer(device, "diag_gate", intermediate_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &ffn_normed, &weights.gate_proj, &gate_out,
            1, h, i);
        queue.submit(std::iter::once(enc.finish()));
    }
    let gate_vals = readback_f32(device, queue, &gate_out, 4);
    let gate_ok = gate_vals.iter().zip(ref_gate.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] Gate proj    | Got: {:?} | Ref: {:?}",
        if gate_ok { "PASS" } else { "FAIL" }, gate_vals, ref_gate);

    // Step 3: Up projection
    let up_out = create_temp_buffer(device, "diag_up", intermediate_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &ffn_normed, &weights.up_proj, &up_out,
            1, h, i);
        queue.submit(std::iter::once(enc.finish()));
    }
    let up_vals = readback_f32(device, queue, &up_out, 4);
    let up_ok = up_vals.iter().zip(ref_up.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] Up proj      | Got: {:?} | Ref: {:?}",
        if up_ok { "PASS" } else { "FAIL" }, up_vals, ref_up);

    // Step 4: SwiGLU
    let activated = create_temp_buffer(device, "diag_swiglu", intermediate_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        dispatch_swiglu(device, queue, &mut enc, pipelines,
            &gate_out, &up_out, &activated, i);
        queue.submit(std::iter::once(enc.finish()));
    }
    let swiglu_vals = readback_f32(device, queue, &activated, 4);
    let swiglu_ok = swiglu_vals.iter().zip(ref_swiglu.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] SwiGLU       | Got: {:?} | Ref: {:?}",
        if swiglu_ok { "PASS" } else { "FAIL" }, swiglu_vals, ref_swiglu);

    // Step 5: Down projection
    let ffn_out = create_temp_buffer(device, "diag_down", hidden_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        dispatch_tiled_matmul(device, queue, &mut enc, pipelines,
            &activated, &weights.down_proj, &ffn_out,
            1, i, h);
        queue.submit(std::iter::once(enc.finish()));
    }
    let down_vals = readback_f32(device, queue, &ffn_out, 4);
    let down_ok = down_vals.iter().zip(ref_down.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] Down proj    | Got: {:?} | Ref: {:?}",
        if down_ok { "PASS" } else { "FAIL" }, down_vals, ref_down);

    // Step 6: Residual add (hidden_state + ffn_out -> hidden_state)
    let residual_out = create_temp_buffer(device, "diag_residual", hidden_bytes);
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        dispatch_add(device, queue, &mut enc, pipelines,
            hidden_state, &ffn_out, &residual_out, h);
        queue.submit(std::iter::once(enc.finish()));
    }
    let res_vals = readback_f32(device, queue, &residual_out, 4);
    let res_ok = res_vals.iter().zip(ref_residual.iter())
        .all(|(a, e)| (a - e).abs() < 0.02);
    tracing::info!("  [{}] Residual add | Got: {:?} | Ref: {:?}",
        if res_ok { "PASS" } else { "FAIL" }, res_vals, ref_residual);

    // Copy result back to hidden_state for downstream use
    {
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        enc.copy_buffer_to_buffer(&residual_out, 0, hidden_state, 0, hidden_bytes);
        queue.submit(std::iter::once(enc.finish()));
    }

    tracing::info!("═══ FFN DIAGNOSTIC COMPLETE ═══");
}

// ── Dispatch helpers ────────────────────────────────────────────────────────

fn create_temp_buffer(device: &wgpu::Device, label: &str, size: u64) -> wgpu::Buffer {
    device.create_buffer(&wgpu::BufferDescriptor {
        label: Some(label),
        size,
        usage: wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC
            | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    })
}

fn dispatch_tiled_matmul(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    input: &wgpu::Buffer,
    weights: &wgpu::Buffer,
    output: &wgpu::Buffer,
    m: u32, k: u32, n: u32,
) {
    // For single-token decode (m=1), use the matvec shader which reads
    // weights in GGUF native [N × K] row-major layout directly.
    // output[n] = sum_k(W[n * K + k] * input[k])

    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    struct MatvecParams { n_out: u32, k_in: u32, _pad0: u32, _pad1: u32 }

    let params = MatvecParams { n_out: n, k_in: k, _pad0: 0, _pad1: 0 };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("matvec_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("matvec_bg"),
        layout: &pipelines.matvec_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: input.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: weights.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: output.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.matvec);
    pass.set_bind_group(0, Some(&bg), &[]);
    pass.dispatch_workgroups((n + 255) / 256, 1, 1);
}

/// Fused matvec + bias: output[n] = sum_k(W[n*K+k] * input[k]) + bias[n]
/// Eliminates staging buffer + copy hazard on P100 Vulkan.
fn dispatch_matvec_bias(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    input: &wgpu::Buffer,
    weights: &wgpu::Buffer,
    bias: &wgpu::Buffer,
    output: &wgpu::Buffer,
    k: u32, n: u32,
) {
    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    struct MatvecParams { n_out: u32, k_in: u32, _pad0: u32, _pad1: u32 }

    let params = MatvecParams { n_out: n, k_in: k, _pad0: 0, _pad1: 0 };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("matvec_bias_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("matvec_bias_bg"),
        layout: &pipelines.matvec_bias_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: input.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: weights.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: output.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 4, resource: bias.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.matvec_bias);
    pass.set_bind_group(0, Some(&bg), &[]);
    pass.dispatch_workgroups((n + 255) / 256, 1, 1);
}

fn dispatch_tiled_matmul_raw(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    input: &wgpu::Buffer,
    weights: &wgpu::Buffer,
    output: &wgpu::Buffer,
    m: u32, k: u32, n: u32,
) {
    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    struct TiledParams { m: u32, k: u32, n: u32, _pad: u32 }

    let params = TiledParams { m, k, n, _pad: 0 };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("tiled_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("tiled_bg"),
        layout: &pipelines.chunked_matmul.tiled_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: input.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: weights.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: output.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.chunked_matmul.tiled_pipeline);
    pass.set_bind_group(0, Some(&bg), &[]);
    pass.dispatch_workgroups((n + 15) / 16, (m + 15) / 16, 1);
}

fn dispatch_rope(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    qk_buf: &wgpu::Buffer,
    head_dim: u32,
    pos: u32,
    n_heads: u32,
) {
    let params = RoPEParams { head_dim, pos, n_heads, _pad: 0 };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("rope_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("rope_bg"),
        layout: &pipelines.rope_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: qk_buf.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.rope);
    pass.set_bind_group(0, Some(&bg), &[]);
    // One workgroup per head, 64 threads per workgroup (handles head_dim/2 pairs)
    pass.dispatch_workgroups(n_heads, 1, 1);
}

fn dispatch_swiglu(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    gate: &wgpu::Buffer,
    up: &wgpu::Buffer,
    output: &wgpu::Buffer,
    n_elements: u32,
) {
    let params = SwiGLUParams {
        n_elements_vec4: (n_elements + 3) / 4,
        _pad0: 0, _pad1: 0, _pad2: 0,
    };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("swiglu_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("swiglu_bg"),
        layout: &pipelines.swiglu_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: gate.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: up.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: output.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.swiglu);
    pass.set_bind_group(0, Some(&bg), &[]);
    pass.dispatch_workgroups((params.n_elements_vec4 + 255) / 256, 1, 1);
}

fn dispatch_add(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &LayerPipelines,
    a: &wgpu::Buffer,
    b: &wgpu::Buffer,
    output: &wgpu::Buffer,
    n_elements: u32,
) {
    let params = AddParams { n_elements, _pad0: 0, _pad1: 0, _pad2: 0 };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("add_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("add_bg"),
        layout: &pipelines.add_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: a.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: b.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: output.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
    pass.set_pipeline(&pipelines.add);
    pass.set_bind_group(0, Some(&bg), &[]);
    pass.dispatch_workgroups((n_elements + 255) / 256, 1, 1);
}

/// Read back f32 values from a GPU buffer.
pub fn readback_f32(device: &wgpu::Device, queue: &wgpu::Queue, buf: &wgpu::Buffer, n: usize) -> Vec<f32> {
    let size = (n * 4) as u64;
    let staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("diag_staging"), size,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
    enc.copy_buffer_to_buffer(buf, 0, &staging, 0, size);
    queue.submit(std::iter::once(enc.finish()));
    let slice = staging.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
    loop {
        device.poll(wgpu::Maintain::Poll);
        if rx.try_recv().is_ok() { break; }
        std::thread::sleep(std::time::Duration::from_micros(10));
    }
    let data = slice.get_mapped_range();
    let vals: Vec<f32> = bytemuck::cast_slice(&data)[..n].to_vec();
    drop(data);
    staging.unmap();
    vals
}
