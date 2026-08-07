You are an expert in speculative decoding, LLM inference optimization, and Rust systems programming. I need a complete speculative decoding implementation for a Rust+wgpu inference engine.

## System context
- **Verifier**: Qwen2.5-Coder-1.5B Q6_K on Tesla P100 (T440, local). Currently 0.1 t/s (being fixed separately to ~2-5 t/s).
- **Draft model**: Will be a smaller model (TinyLlama-1.1B Q4_K_M or Qwen2.5-0.5B) on GTX 1070 (cesarops2, 100.102.158.111) or P106-100 (cesarops3, 100.105.77.74).
- **Communication**: HTTP/JSON between nodes over Tailscale (100Mbps effective, ~1ms RTT).
- **Goal**: 2-3x speedup via speculative decoding.

## How speculative decoding works (for context)
1. Draft model proposes N tokens (γ=4-8) autoregressively
2. Verifier runs ONE forward pass over all N+1 positions in parallel (batch prefill)
3. Compare draft tokens vs verifier's argmax at each position
4. Accept tokens up to first mismatch, reject rest
5. Always accept at least 1 token (the verifier's own prediction at the rejection point)
6. Expected speedup: γ × acceptance_rate / (1 + γ × overhead_ratio)

## Deliverable 1: src/speculative.rs — Core algorithm

```rust
pub struct SpecConfig {
    pub gamma: usize,           // draft tokens per step (4-8)
    pub draft_endpoint: String, // "http://100.102.158.111:5200/v1"
    pub temperature: f32,       // 0.0 = greedy
    pub top_p: f32,
}

pub struct SpecStats {
    pub tokens_generated: usize,
    pub draft_tokens_proposed: usize,
    pub draft_tokens_accepted: usize,
    pub acceptance_rate: f32,
    pub speedup_factor: f32,
}

/// Run speculative decoding loop.
/// draft_fn: calls draft model HTTP endpoint to get γ token proposals
/// verify_fn: runs verifier forward pass over [context + γ draft tokens]
pub async fn speculative_decode(
    config: &SpecConfig,
    initial_tokens: &[u32],
    max_new_tokens: usize,
    verify_fn: impl Fn(&[u32]) -> Vec<f32>,  // returns logits for last position
    verify_batch_fn: impl Fn(&[u32]) -> Vec<Vec<f32>>, // returns logits for ALL positions
) -> (Vec<u32>, SpecStats);
```

Key implementation details:
- Draft model is called via HTTP (koboldcpp OpenAI-compatible API)
- Verifier runs locally via our GPU forward pass
- The "batch verify" is the key: run the verifier once over [context + γ draft tokens] and get logits at all γ+1 positions
- Token acceptance: greedy (temperature=0) → accept if draft[i] == argmax(verifier_logits[i])
- Stochastic (temperature>0) → use the modified rejection sampling from the original speculative decoding paper

## Deliverable 2: Draft model HTTP client

```rust
pub struct DraftClient {
    endpoint: String,
    client: reqwest::Client,
}

impl DraftClient {
    /// Propose γ tokens given context. Returns token IDs.
    pub async fn propose(&self, context: &[u32], gamma: usize, temperature: f32) -> Result<Vec<u32>, reqwest::Error>;
    
    /// Check if draft endpoint is alive.
    pub async fn health_check(&self) -> bool;
}
```

Use koboldcpp's `/v1/completions` endpoint with `max_tokens=gamma`. The context needs to be decoded to text (or use token IDs directly if the API supports it — koboldcpp does via `token_ids` field).

## Deliverable 3: Batch verifier integration

The current verifier runs one token at a time. For speculative decoding we need to run it over a sequence of γ+1 tokens and get logits at each position.

Show how to modify `generate.rs::run_generate_mode` to support batch verification:
```rust
/// Run forward pass over tokens[0..n], return logits at each position.
/// This is the "prefill" mode — processes all tokens in one pass.
pub fn verify_batch(
    tokens: &[u32],
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    // ... existing params ...
) -> Vec<Vec<f32>>;  // [n_tokens][vocab_size]
```

The key change: instead of only keeping the last position's logits, keep ALL positions' logits. The KV cache naturally handles this since we're doing sequential prefill.

## Deliverable 4: CLI integration

Add `--speculative` flag to the generate command:
```
cesarops-inference generate \
  --model /codebase/models/qwen2.5-coder-1.5b-instruct-q6_k.gguf \
  --prompt "Hello" \
  --max-tokens 100 \
  --speculative \
  --draft-endpoint http://100.102.158.111:5200 \
  --gamma 5
```

## Deliverable 5: Expected performance analysis

Given:
- Verifier: 1.5B model, ~2-5 t/s after submit batching fix (single token)
- Draft: TinyLlama 1.1B Q4_K_M on 1070, ~8-15 t/s
- γ = 5 draft tokens
- Expected acceptance rate: ~70-80% for code completion tasks
- HTTP round-trip: ~5ms per draft call

Calculate:
- Tokens per second with speculative decoding
- Break-even acceptance rate (below which speculative is slower)
- Optimal γ for this hardware setup

## OUTPUT FORMAT
```rust
// === FILE: src/speculative.rs ===
// Full implementation

// === FILE: src/draft_client.rs ===
// HTTP client for draft model

// === DIFF: src/generate.rs ===
// verify_batch addition + CLI flag

// === PERFORMANCE ANALYSIS ===
// Math showing expected speedup

// === NOTES ===
// - Token ID vs text encoding for draft API
// - KV cache management during speculative steps (need to rollback on rejection)
// - Why batch verify is faster than γ sequential verifies
```

Complete working async Rust code. Use tokio and reqwest (already in Cargo.toml).
