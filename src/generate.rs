//! Token generation loop — the top-level entry point for inference.
//!
//! Orchestrates: embedding lookup → layer loop → final norm → lm_head → sampling
//! Handles KV cache updates and autoregressive decode.

use crate::forward_pass::{
    execute_layer, LayerPipelines, LayerWeights, KVCache, ModelConfig,
};
use crate::shader_ops::RmsNormPipeline;
use crate::tensor_chunker::ChunkedMatmulPipeline;
use bytemuck::{Pod, Zeroable};
use rand::Rng;
use std::sync::Arc;
use tracing::info;

/// All model weights loaded onto GPU, organized by layer.
pub struct ModelWeightsGpu {
    /// Token embedding table [vocab_size × hidden_dim] as f32
    pub token_embeddings: wgpu::Buffer,
    /// Per-layer weight sets
    pub layers: Vec<LayerWeights>,
    /// Final RMSNorm weight [hidden_dim]
    pub final_norm: wgpu::Buffer,
    /// Language model head [vocab_size × hidden_dim] — may be chunked
    pub lm_head: wgpu::Buffer,
}

/// Generation parameters.
#[derive(Debug, Clone)]
pub struct GenerationParams {
    pub temperature: f32,
    pub top_p: f32,
    pub max_tokens: usize,
    /// Stop token IDs (EOS, EOT, etc.)
    pub stop_tokens: Vec<u32>,
}

impl Default for GenerationParams {
    fn default() -> Self {
        Self {
            temperature: 0.7,
            top_p: 0.9,
            max_tokens: 512,
            stop_tokens: vec![151643, 151645], // Qwen EOS tokens
        }
    }
}

/// Errors during generation.
#[derive(Debug)]
pub enum GenerationError {
    GpuError(String),
    MaxTokensReached,
    EmptyPrompt,
}

impl std::fmt::Display for GenerationError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::GpuError(msg) => write!(f, "GPU error: {}", msg),
            Self::MaxTokensReached => write!(f, "Max tokens reached"),
            Self::EmptyPrompt => write!(f, "Empty prompt"),
        }
    }
}

/// Generate tokens autoregressively.
///
/// 1. Prefill: process all prompt tokens (building KV cache)
/// 2. Decode: generate one token at a time until stop condition
pub fn generate_tokens(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    config: &ModelConfig,
    pipelines: &LayerPipelines,
    weights: &ModelWeightsGpu,
    kv_caches: &mut Vec<KVCache>,
    prompt_tokens: &[u32],
    params: &GenerationParams,
) -> Result<Vec<u32>, GenerationError> {
    if prompt_tokens.is_empty() {
        return Err(GenerationError::EmptyPrompt);
    }

    let hidden_bytes = (config.hidden_dim * 4) as u64;
    let vocab_bytes = (config.vocab_size * 4) as u64;

    // Working buffer for hidden states (reused across all positions)
    let hidden_state = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("hidden_state"),
        size: hidden_bytes,
        usage: wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC
            | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });

    let mut output_tokens: Vec<u32> = Vec::with_capacity(params.max_tokens);

    // ── Prefill: process prompt tokens to build KV cache ────────────────────
    for (pos, &token_id) in prompt_tokens.iter().enumerate() {
        execute_single_token(
            device, queue, config, pipelines, weights, kv_caches,
            &hidden_state, token_id, pos as u32,
        );
    }

    // ── Decode: generate new tokens ─────────────────────────────────────────
    let mut pos = prompt_tokens.len() as u32;

    for _ in 0..params.max_tokens {
        // Get logits from the last forward pass
        let logits_buf = project_lm_head(
            device, queue, config, pipelines, weights, &hidden_state,
        );

        // Read logits back to CPU for sampling
        let logits = read_buffer_f32(device, queue, &logits_buf, config.vocab_size as usize);

        // Diagnostic: print top-5 logits for first generated token
        #[cfg(feature = "diagnostics")]
        if output_tokens.is_empty() {
            // Also check hidden state after final norm
            let hs_vals = crate::forward_pass::readback_f32(device, queue, &hidden_state, 4);
            tracing::info!("  Hidden state after final_norm[0:4]: {:?}", hs_vals);

            let mut indexed: Vec<(usize, f32)> = logits.iter().enumerate().map(|(i, &v)| (i, v)).collect();
            indexed.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));
            tracing::info!("═══ TOP-5 LOGITS (first generated token) ═══");
            for (idx, val) in indexed.iter().take(5) {
                tracing::info!("  token {} = {:.4}", idx, val);
            }
            tracing::info!("  logits[0..4] = {:?}", &logits[..4]);
            tracing::info!("  logits stats: min={:.4} max={:.4} mean={:.4}",
                logits.iter().cloned().fold(f32::INFINITY, f32::min),
                logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max),
                logits.iter().sum::<f32>() / logits.len() as f32);
        }

        // Sample next token
        let next_token = sample_next_token(&logits, params.temperature, params.top_p);

        // Check stop condition
        if params.stop_tokens.contains(&next_token) {
            break;
        }

        output_tokens.push(next_token);

        // Feed the new token back through the model
        execute_single_token(
            device, queue, config, pipelines, weights, kv_caches,
            &hidden_state, next_token, pos,
        );
        pos += 1;
    }

    info!("Generated {} tokens", output_tokens.len());
    Ok(output_tokens)
}

/// Process a single token through all layers (used for both prefill and decode).
fn execute_single_token(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    config: &ModelConfig,
    pipelines: &LayerPipelines,
    weights: &ModelWeightsGpu,
    kv_caches: &mut Vec<KVCache>,
    hidden_state: &wgpu::Buffer,
    token_id: u32,
    pos: u32,
) {
    let hidden_bytes = (config.hidden_dim * 4) as u64;
    // Embedding buffer is pre-dequanted to F32 at load time.
    // Each row = hidden_dim * 4 bytes (f32).
    let embed_offset = (token_id as u64) * hidden_bytes;

    // 1. Embedding lookup: copy token's F32 row to hidden_state
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("embed_encoder"),
    });
    encoder.copy_buffer_to_buffer(
        &weights.token_embeddings, embed_offset,
        hidden_state, 0,
        hidden_bytes,
    );
    queue.submit(std::iter::once(encoder.finish()));

    // Diagnostic: dump embedding vector before any layers process it
    #[cfg(feature = "diagnostics")]
    if pos == 0 {
        let diag_size = 64u64;
        let staging = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("embed_diag"),
            size: diag_size,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
        enc.copy_buffer_to_buffer(hidden_state, 0, &staging, 0, diag_size);
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
        let vals: &[f32] = bytemuck::cast_slice(&data);
        tracing::info!("═══ LAYER 0 INPUT (embedding[0..16]) ═══");
        tracing::info!("  {:?}", &vals[..16]);
        drop(data);
        staging.unmap();
    }

    // 2. Execute all transformer layers
    // Pre-allocate scratch buffers (reused across all layers for this token)
    let scratch = crate::scratch_buffers::ScratchBuffers::new(
        device, config.hidden_dim, config.intermediate_dim,
        config.n_kv_heads, config.head_dim, config.max_seq_len,
    );

    for (layer_idx, layer_weights) in weights.layers.iter().enumerate() {
        let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("layer_encoder"),
        });
        execute_layer(
            device, queue, &mut encoder, pipelines, config,
            layer_weights, &mut kv_caches[layer_idx],
            hidden_state, pos,
        );
        queue.submit(std::iter::once(encoder.finish()));

        // Dump hidden state magnitude after each layer for first token
        if pos == 0 && (layer_idx == 0 || layer_idx == 13 || layer_idx == 27) {
            let vals = crate::forward_pass::readback_f32(device, queue, hidden_state, 4);
            let all_vals = crate::forward_pass::readback_f32(device, queue, hidden_state, config.hidden_dim as usize);
            let rms: f32 = (all_vals.iter().map(|x| x*x).sum::<f32>() / all_vals.len() as f32).sqrt();
            tracing::info!("  [LAYER {}] hidden[0:4]={:?} rms={:.4}", layer_idx, vals, rms);
        }

        // Per-position per-layer diagnostics for prefill debugging
        if pos >= 2 && pos <= 6 && (layer_idx == 0 || layer_idx == 5 || layer_idx == 10 || layer_idx == 15 || layer_idx == 27) {
            let hs = crate::forward_pass::readback_f32(device, queue, hidden_state, 8);
            let all_vals = crate::forward_pass::readback_f32(device, queue, hidden_state, config.hidden_dim as usize);
            let rms: f32 = (all_vals.iter().map(|x| x*x).sum::<f32>() / all_vals.len() as f32).sqrt();
            tracing::info!("  POS={} LAYER={:2} hidden[0:8]={:?} RMS={:.4}", pos, layer_idx, hs, rms);
        }

        // Telemetry: after layer 0 on second token, dump KV cache values
        if layer_idx == 0 && pos == 1 {
            let dump_size = 16u64; // 4 f32 values
            let staging = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("kv_dump"), size: dump_size,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });

            // Read K cache position 0, head 0
            let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
            enc.copy_buffer_to_buffer(&kv_caches[0].key_cache, 0, &staging, 0, dump_size);
            queue.submit(std::iter::once(enc.finish()));
            let k0 = read_staging_f32(device, &staging, 4);
            tracing::info!("═══ ATTN TELEMETRY (Layer 0, pos=1) ═══");
            tracing::info!("  K cache[pos=0, head=0][0..4]: {:?}", k0);

            // Read K cache position 1, head 0
            let kv_stride_bytes = (config.n_kv_heads * config.head_dim * 4) as u64;
            let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
            enc.copy_buffer_to_buffer(&kv_caches[0].key_cache, kv_stride_bytes, &staging, 0, dump_size);
            queue.submit(std::iter::once(enc.finish()));
            let k1 = read_staging_f32(device, &staging, 4);
            tracing::info!("  K cache[pos=1, head=0][0..4]: {:?}", k1);

            // Read hidden state
            let mut enc = device.create_command_encoder(&wgpu::CommandEncoderDescriptor::default());
            enc.copy_buffer_to_buffer(hidden_state, 0, &staging, 0, dump_size);
            queue.submit(std::iter::once(enc.finish()));
            let hs = read_staging_f32(device, &staging, 4);
            tracing::info!("  Hidden state[0..4]: {:?}", hs);
            tracing::info!("  (K values should be non-zero if KV cache is being written)");
        }
    }

    // 3. Final RMSNorm (applied before lm_head projection)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("final_norm_encoder"),
    });
    // Norm in-place: hidden_state → hidden_state
    let norm_temp = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("final_norm_temp"),
        size: hidden_bytes,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });
    pipelines.rmsnorm.dispatch(
        device, queue, &mut encoder,
        hidden_state, &weights.final_norm, &norm_temp,
        config.hidden_dim, 1, config.rms_norm_eps,
    );
    encoder.copy_buffer_to_buffer(&norm_temp, 0, hidden_state, 0, hidden_bytes);
    queue.submit(std::iter::once(encoder.finish()));
}

/// Project hidden state through lm_head to get logits [vocab_size].
fn project_lm_head(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    config: &ModelConfig,
    pipelines: &LayerPipelines,
    weights: &ModelWeightsGpu,
    hidden_state: &wgpu::Buffer,
) -> wgpu::Buffer {
    let logits_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("logits"),
        size: (config.vocab_size * 4) as u64,
        usage: wgpu::BufferUsages::STORAGE
            | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });

    // lm_head: [vocab_size × hidden_dim] × hidden_state[hidden_dim] → logits[vocab_size]
    // Use matvec: output[n] = sum_k(W[n * K + k] * input[k])
    #[repr(C)]
    #[derive(Clone, Copy, Pod, Zeroable)]
    struct MatvecParams { n_out: u32, k_in: u32, _pad0: u32, _pad1: u32 }

    let params = MatvecParams {
        n_out: config.vocab_size,
        k_in: config.hidden_dim,
        _pad0: 0,
        _pad1: 0,
    };
    let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("lm_head_params"),
        size: 16,
        usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

    let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some("lm_head_bg"),
        layout: &pipelines.matvec_bgl,
        entries: &[
            wgpu::BindGroupEntry { binding: 0, resource: hidden_state.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 1, resource: weights.lm_head.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 2, resource: logits_buf.as_entire_binding() },
            wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
        ],
    });

    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("lm_head_encoder"),
    });
    {
        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&pipelines.matvec);
        pass.set_bind_group(0, Some(&bg), &[]);
        pass.dispatch_workgroups(
            (config.vocab_size + 255) / 256,
            1,
            1,
        );
    }
    queue.submit(std::iter::once(encoder.finish()));

    logits_buf
}

/// Read a small staging buffer back to CPU.
fn read_staging_f32(device: &wgpu::Device, staging: &wgpu::Buffer, n: usize) -> Vec<f32> {
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

/// Read a GPU buffer back to CPU as f32 vector.
fn read_buffer_f32(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    buffer: &wgpu::Buffer,
    n_elements: usize,
) -> Vec<f32> {
    let size = (n_elements * 4) as u64;
    let staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("readback_staging"),
        size,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });

    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("readback_encoder"),
    });
    encoder.copy_buffer_to_buffer(buffer, 0, &staging, 0, size);
    queue.submit(std::iter::once(encoder.finish()));

    let slice = staging.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |result| {
        let _ = tx.send(result);
    });

    loop {
        device.poll(wgpu::Maintain::Poll);
        if rx.try_recv().is_ok() {
            break;
        }
        std::thread::sleep(std::time::Duration::from_micros(10));
    }

    let data = slice.get_mapped_range();
    let result: Vec<f32> = bytemuck::cast_slice(&data).to_vec();
    drop(data);
    staging.unmap();
    result
}

/// Top-P + Temperature sampling on CPU.
pub fn sample_next_token(logits: &[f32], temperature: f32, top_p: f32) -> u32 {
    if temperature <= 0.0 || temperature < 0.01 {
        // Greedy: return argmax
        return logits.iter()
            .enumerate()
            .max_by(|(_, a), (_, b)| a.partial_cmp(b).unwrap_or(std::cmp::Ordering::Equal))
            .map(|(idx, _)| idx as u32)
            .unwrap_or(0);
    }

    // Apply temperature and stable softmax
    let max_logit = logits.iter().filter(|x| x.is_finite()).fold(f32::NEG_INFINITY, |a, &b| a.max(b));
    if !max_logit.is_finite() {
        // All logits are NaN/Inf — return token 0
        return 0;
    }
    let mut probs: Vec<(usize, f32)> = logits.iter()
        .enumerate()
        .map(|(idx, &l)| {
            if !l.is_finite() { return (idx, 0.0); }
            (idx, ((l - max_logit) / temperature).exp())
        })
        .collect();

    let sum: f32 = probs.iter().map(|(_, p)| p).sum();
    if sum <= 0.0 {
        return 0;
    }
    for entry in probs.iter_mut() {
        entry.1 /= sum;
    }

    // Sort descending by probability
    probs.sort_unstable_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Top-P truncation
    let mut cumulative = 0.0f32;
    let mut cutoff = probs.len();
    for (i, (_, p)) in probs.iter().enumerate() {
        cumulative += p;
        if cumulative >= top_p {
            cutoff = i + 1;
            break;
        }
    }
    probs.truncate(cutoff);

    // Re-normalize and sample
    let final_sum: f32 = probs.iter().map(|(_, p)| p).sum();
    let mut rng = rand::rng();
    let r_val: f32 = rand::random();
    let mut r: f32 = r_val * final_sum;

    for (token_id, p) in &probs {
        r -= p;
        if r <= 0.0 {
            return *token_id as u32;
        }
    }

    probs.last().map(|(id, _)| *id as u32).unwrap_or(0)
}

// ── GGUF Tensor Name Mapping ────────────────────────────────────────────────

/// Maps GGUF tensor names to our internal weight structure.
/// Qwen2.5 GGUF naming convention:
///
/// - `token_embd.weight` → token embeddings [vocab × hidden]
/// - `blk.{i}.attn_norm.weight` → attention RMSNorm
/// - `blk.{i}.ffn_norm.weight` → FFN RMSNorm
/// - `blk.{i}.attn_q.weight` → Q projection
/// - `blk.{i}.attn_k.weight` → K projection
/// - `blk.{i}.attn_v.weight` → V projection
/// - `blk.{i}.attn_output.weight` → O projection
/// - `blk.{i}.ffn_gate.weight` → Gate projection (SwiGLU)
/// - `blk.{i}.ffn_up.weight` → Up projection
/// - `blk.{i}.ffn_down.weight` → Down projection
/// - `output_norm.weight` → Final RMSNorm
/// - `output.weight` → LM head (may be tied to token_embd)
pub fn gguf_tensor_name(layer: usize, component: &str) -> String {
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
        _ => format!("blk.{}.{}", layer, component),
    }
}
