//! HTTP API Server — KoboldCPP-compatible drop-in replacement.
//!
//! Endpoints:
//!   POST /api/v1/generate — same JSON format as KoboldCPP
//!   GET  /api/v1/model    — model info
//!   GET  /health          — liveness check

use axum::{
    extract::State,
    response::Json,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tokio::sync::Mutex;
use tracing::info;

use crate::arena::InferenceArena;
use crate::bridge;
use crate::kv_cache::KvCache;
use crate::loader::ModelWeights;
use crate::sampling::{self, SamplingParams};
use crate::tokenizer::ZeroAllocBpeTokenizer;
use crate::transformer::{TransformerConfig, TransformerDecoder};
use crate::weight_cache::WeightCache;

/// Server state shared across handlers.
pub struct InferenceState {
    pub model_name: String,
    pub is_generating: bool,
    pub weights: Arc<ModelWeights>,
    pub decoder: Arc<TransformerDecoder>,
    pub tokenizer: Arc<ZeroAllocBpeTokenizer>,
}

/// KoboldCPP-compatible generate request.
#[derive(Debug, Deserialize)]
pub struct GenerateRequest {
    pub prompt: String,
    #[serde(default = "default_max_length")]
    pub max_length: u32,
    #[serde(default = "default_temperature")]
    pub temperature: f32,
    #[serde(default = "default_top_p")]
    pub top_p: f32,
    #[serde(default = "default_rep_pen")]
    pub rep_pen: f32,
    #[serde(default)]
    pub stop_sequence: Vec<String>,
    /// If true (default), wrap prompt in Qwen2.5 ChatML template.
    /// Set to false for raw completion mode.
    #[serde(default = "default_chat_template")]
    pub use_chat_template: bool,
}

fn default_chat_template() -> bool { true }

fn default_max_length() -> u32 { 512 }
fn default_temperature() -> f32 { 0.7 }
fn default_top_p() -> f32 { 0.9 }
fn default_rep_pen() -> f32 { 1.1 }

/// KoboldCPP-compatible generate response.
#[derive(Debug, Serialize)]
pub struct GenerateResponse {
    pub results: Vec<GenerateResult>,
}

#[derive(Debug, Serialize)]
pub struct GenerateResult {
    pub text: String,
}

/// Model info response.
#[derive(Debug, Serialize)]
pub struct ModelResponse {
    pub result: String,
}

/// Health check response.
#[derive(Debug, Serialize)]
pub struct HealthResponse {
    pub status: String,
    pub service: String,
    pub model: String,
}

async fn health(State(state): State<Arc<Mutex<InferenceState>>>) -> Json<HealthResponse> {
    let s = state.lock().await;
    Json(HealthResponse {
        status: "ok".to_string(),
        service: "cesarops-inference".to_string(),
        model: s.model_name.clone(),
    })
}

async fn model_info(State(state): State<Arc<Mutex<InferenceState>>>) -> Json<ModelResponse> {
    let s = state.lock().await;
    Json(ModelResponse {
        result: format!("cesarops-inference/{}", s.model_name),
    })
}

async fn generate(
    State(state): State<Arc<Mutex<InferenceState>>>,
    Json(req): Json<GenerateRequest>,
) -> Json<GenerateResponse> {
    info!("Generate: prompt_len={}, max_length={}, temp={}",
        req.prompt.len(), req.max_length, req.temperature);

    let mut s = state.lock().await;
    s.is_generating = true;

    let weights = Arc::clone(&s.weights);
    let decoder = Arc::clone(&s.decoder);
    let tokenizer = Arc::clone(&s.tokenizer);
    drop(s); // Release lock during inference

    let response_text = run_inference(
        &weights,
        &decoder,
        &tokenizer,
        &req.prompt,
        req.max_length,
        req.temperature,
        req.top_p,
        req.rep_pen,
        req.use_chat_template,
    );

    let mut s = state.lock().await;
    s.is_generating = false;

    Json(GenerateResponse {
        results: vec![GenerateResult { text: response_text }],
    })
}

/// Run the actual inference loop: embed → forward → sample → decode.
fn run_inference(
    weights: &ModelWeights,
    decoder: &TransformerDecoder,
    tokenizer: &ZeroAllocBpeTokenizer,
    prompt: &str,
    max_tokens: u32,
    temperature: f32,
    top_p: f32,
    rep_pen: f32,
    use_chat_template: bool,
) -> String {
    let h = decoder.config.hidden_size;
    let vocab_size = decoder.config.vocab_size;

    // --- Apply Qwen2.5 ChatML template if requested ---
    let effective_prompt = if use_chat_template {
        format!(
            "<|im_start|>system\nYou are a helpful assistant.<|im_end|>\n<|im_start|>user\n{}<|im_end|>\n<|im_start|>assistant\n",
            prompt
        )
    } else {
        prompt.to_string()
    };

    // --- Tokenize prompt ---
    let prompt_tokens = tokenizer.encode(&effective_prompt);
    info!("Prompt tokens: {} (real_bpe={}, chat_template={}), ids={:?}", prompt_tokens.len(), tokenizer.has_real_vocab, use_chat_template, &prompt_tokens[..prompt_tokens.len().min(20)]);

    // --- Get embedding weight ---
    let embed_name = find_embed_name(weights);
    let embed_data = if let Some(bytes) = weights.tensor_bytes(&embed_name) {
        let region = weights.tensors.get(&embed_name).unwrap();
        let n_elements: usize = region.shape.iter().product();
        bridge::dequantize_tensor(bytes, region.quant_type, n_elements)
    } else {
        info!("WARNING: No embedding tensor found, using random init");
        vec![0.01f32; vocab_size * h]
    };

    // --- Get initial hidden state from last prompt token ---
    let last_prompt_token = *prompt_tokens.last().unwrap_or(&0) as usize;
    let mut hidden_state = get_embedding(&embed_data, last_prompt_token, h, vocab_size);

    // --- Process prompt through KV cache (prefill) ---
    let mut kv_cache = KvCache::new(decoder.config.num_layers, 4096);

    // Process all prompt tokens through the transformer to build KV cache
    for (i, &token_id) in prompt_tokens.iter().enumerate() {
        let mut h_state = get_embedding(&embed_data, token_id as usize, h, vocab_size);
        let _logits = decoder.forward(&mut h_state, i, weights, &mut kv_cache);
        kv_cache.advance();
        // Keep the last hidden state for generation
        if i == prompt_tokens.len() - 1 {
            hidden_state = h_state;
        }
    }
    info!("Prefill complete: {} tokens cached", kv_cache.len());

    // --- Autoregressive generation loop ---
    let mut generated_tokens: Vec<u32> = Vec::new();

    let params = SamplingParams {
        temperature,
        top_p,
        rep_pen,
        rep_pen_range: 256,
        stop_sequences: Vec::new(),
        banned_tokens: std::collections::HashSet::new(),
    };

    for step in 0..max_tokens {
        let position = prompt_tokens.len() + step as usize;

        // Forward pass with KV cache
        let mut logits = decoder.forward(&mut hidden_state, position, weights, &mut kv_cache);
        kv_cache.advance();

        // Check for NaN in hidden state before logits
        let has_nan = hidden_state.iter().any(|x| x.is_nan() || x.is_infinite());
        if has_nan {
            info!("WARNING: hidden_state contains NaN/Inf after forward pass");
        }

        // Diagnostic: log logits range
        let logits_min = logits.iter().cloned().fold(f32::INFINITY, f32::min);
        let logits_max = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        let logits_mean = logits.iter().sum::<f32>() / logits.len() as f32;
        info!("Logits: min={:.4}, max={:.4}, mean={:.6}", logits_min, logits_max, logits_mean);

        // Sample next token
        let recent: Vec<u32> = prompt_tokens.iter()
            .chain(generated_tokens.iter())
            .rev()
            .take(params.rep_pen_range)
            .copied()
            .collect();
        let next_token = sampling::sample(&mut logits, &params, &recent);

        // Check for EOS (Qwen EOS = 151645)
        if next_token == 151645 || next_token == 151643 {
            info!("EOS at step {}", step);
            break;
        }

        generated_tokens.push(next_token);

        // Embed the new token for next iteration
        hidden_state = get_embedding(&embed_data, next_token as usize, h, vocab_size);

        // Log progress every token (for debugging)
        info!("Step {}: token_id={}", step, next_token);
    }

    // Decode all generated tokens at once
    let output = tokenizer.decode(&generated_tokens);
    info!("Generated {} tokens, decoded to {} chars", generated_tokens.len(), output.len());
    output
}

/// Look up a token's embedding vector from the embedding matrix.
/// GGUF column-major: shape [1536, 151936] means 1536 is contiguous (the stride).
/// Each token's embedding is a contiguous block of 1536 elements.
/// Token t's embedding = data[t * hidden_size .. (t+1) * hidden_size]
fn get_embedding(embed_data: &[f32], token_id: usize, hidden_size: usize, vocab_size: usize) -> Vec<f32> {
    let token_id = token_id.min(vocab_size - 1);
    let start = token_id * hidden_size;
    let end = start + hidden_size;
    if end <= embed_data.len() {
        embed_data[start..end].to_vec()
    } else {
        (0..hidden_size).map(|i| 0.001 * ((i % 7) as f32 - 3.0) / 3.0).collect()
    }
}

/// Find the embedding tensor name (different models use different names).
fn find_embed_name(weights: &ModelWeights) -> String {
    let candidates = [
        "token_embd.weight",
        "model.embed_tokens.weight",
        "transformer.wte.weight",
        "embeddings.word_embeddings.weight",
    ];
    for name in &candidates {
        if weights.tensors.contains_key(*name) {
            return name.to_string();
        }
    }
    // Return first candidate as default
    candidates[0].to_string()
}

/// Generate check endpoint (KoboldCPP compatibility).
async fn generate_check(State(_state): State<Arc<Mutex<InferenceState>>>) -> Json<GenerateResponse> {
    Json(GenerateResponse {
        results: vec![GenerateResult { text: String::new() }],
    })
}

/// Build and run the inference server.
pub async fn run_server(
    model_name: String,
    port: u16,
    weights: Arc<ModelWeights>,
    arena: Arc<InferenceArena>,
    tokenizer: Arc<ZeroAllocBpeTokenizer>,
    gpu_context: Option<Arc<crate::gpu_context::GpuContext>>,
) -> anyhow::Result<()> {
    // Derive intermediate_size from FFN gate tensor shape
    // GGUF shape for ffn_gate is [hidden_dim, intermediate_size] or [intermediate_size, hidden_dim]
    let intermediate_size = weights.tensors.get("blk.0.ffn_gate.weight")
        .map(|r| {
            // The dimension that ISN'T hidden_dim is the intermediate_size
            if r.shape.len() >= 2 {
                let dim0 = r.shape[0];
                let dim1 = r.shape[1];
                if dim0 == weights.hidden_dim { dim1 } else { dim0 }
            } else {
                weights.hidden_dim * 4
            }
        })
        .unwrap_or(weights.hidden_dim * 4);
    
    info!("Derived intermediate_size={} from FFN gate tensor", intermediate_size);

    let config = TransformerConfig {
        vocab_size: weights.vocab_size,
        hidden_size: weights.hidden_dim,
        intermediate_size,
        num_layers: weights.n_layers,
        num_heads: weights.n_heads,
        num_kv_heads: weights.n_kv_heads,
        head_dim: weights.hidden_dim / weights.n_heads,
        max_seq_len: 4096,
        rope_theta: 1000000.0,
        rms_norm_eps: 1e-6,
    };

    // Pre-dequantize all weights into a CPU cache (eliminates per-token dequant overhead)
    let weight_cache = Arc::new(WeightCache::from_model(&weights));

    let decoder = Arc::new(
        TransformerDecoder::new(config, arena).with_weight_cache(weight_cache)
    );

    // Attach GPU context if available
    let decoder = if let Some(gpu) = gpu_context {
        Arc::new(
            TransformerDecoder::new(
                TransformerConfig {
                    vocab_size: weights.vocab_size,
                    hidden_size: weights.hidden_dim,
                    intermediate_size,
                    num_layers: weights.n_layers,
                    num_heads: weights.n_heads,
                    num_kv_heads: weights.n_kv_heads,
                    head_dim: weights.hidden_dim / weights.n_heads,
                    max_seq_len: 4096,
                    rope_theta: 1000000.0,
                    rms_norm_eps: 1e-6,
                },
                decoder.arena.clone(),
            ).with_weight_cache(decoder.weight_cache.clone().unwrap())
             .with_gpu(gpu)
        )
    } else {
        decoder
    };

    let state = Arc::new(Mutex::new(InferenceState {
        model_name: model_name.clone(),
        is_generating: false,
        weights,
        decoder,
        tokenizer,
    }));

    let app = Router::new()
        .route("/health", get(health))
        .route("/api/v1/model", get(model_info))
        .route("/api/v1/generate", post(generate))
        .route("/api/extra/generate/check", get(generate_check))
        .with_state(state);

    let addr = format!("0.0.0.0:{}", port);
    info!("cesarops-inference server on {}", addr);
    info!("  POST /api/v1/generate  — KoboldCPP-compatible");
    info!("  GET  /api/v1/model     — model info");
    info!("  GET  /health           — liveness");
    info!("  Model: {}", model_name);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
