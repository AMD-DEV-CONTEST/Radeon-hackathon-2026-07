//! Token Sampling — Temperature, Top-p, Repetition Penalty, Logit Bias.
//!
//! CRITICAL: The logit bias sets <think> and </think> token IDs to -infinity.
//! The model physically cannot emit think tokens during the action phase.

use std::collections::HashSet;

/// Sampling parameters for token generation.
#[derive(Debug, Clone)]
pub struct SamplingParams {
    pub temperature: f32,
    pub top_p: f32,
    pub rep_pen: f32,
    pub rep_pen_range: usize,
    pub stop_sequences: Vec<Vec<u32>>,
    pub banned_tokens: HashSet<u32>,
}

impl Default for SamplingParams {
    fn default() -> Self {
        Self {
            temperature: 0.7,
            top_p: 0.9,
            rep_pen: 1.1,
            rep_pen_range: 256,
            stop_sequences: Vec::new(),
            banned_tokens: HashSet::new(),
        }
    }
}

/// Apply temperature scaling to logits.
pub fn apply_temperature(logits: &mut [f32], temperature: f32) {
    if temperature <= 0.0 || temperature == 1.0 {
        return;
    }
    let inv_temp = 1.0 / temperature;
    for logit in logits.iter_mut() {
        *logit *= inv_temp;
    }
}

/// Apply repetition penalty to logits based on recent token history.
pub fn apply_repetition_penalty(logits: &mut [f32], recent_tokens: &[u32], penalty: f32) {
    if penalty == 1.0 {
        return;
    }
    for &token_id in recent_tokens {
        let idx = token_id as usize;
        if idx < logits.len() {
            if logits[idx] > 0.0 {
                logits[idx] /= penalty;
            } else {
                logits[idx] *= penalty;
            }
        }
    }
}

/// Apply logit bias — set banned tokens to -infinity.
/// This is the "Think Killer" — <think> and </think> tokens get -inf.
pub fn apply_logit_bias(logits: &mut [f32], banned_tokens: &HashSet<u32>) {
    for &token_id in banned_tokens {
        let idx = token_id as usize;
        if idx < logits.len() {
            logits[idx] = f32::NEG_INFINITY;
        }
    }
}

/// Top-p (nucleus) sampling — keep tokens whose cumulative probability <= top_p.
/// Returns the sampled token ID.
pub fn sample_top_p(logits: &[f32], top_p: f32) -> u32 {
    // Softmax
    let max_logit = logits.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
    let exps: Vec<f32> = logits.iter().map(|&l| (l - max_logit).exp()).collect();
    let sum: f32 = exps.iter().sum();
    let probs: Vec<f32> = exps.iter().map(|&e| e / sum).collect();

    // Sort by probability (descending)
    let mut indexed: Vec<(usize, f32)> = probs.iter().enumerate().map(|(i, &p)| (i, p)).collect();
    indexed.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap_or(std::cmp::Ordering::Equal));

    // Accumulate until we exceed top_p
    let mut cumulative = 0.0f32;
    let mut candidates: Vec<(usize, f32)> = Vec::new();
    for (idx, prob) in &indexed {
        cumulative += prob;
        candidates.push((*idx, *prob));
        if cumulative >= top_p {
            break;
        }
    }

    // Sample from candidates
    if candidates.is_empty() {
        return indexed[0].0 as u32;
    }

    // Renormalize
    let total: f32 = candidates.iter().map(|(_, p)| p).sum();
    let mut rng_val = simple_random() * total;

    for (idx, prob) in &candidates {
        rng_val -= prob;
        if rng_val <= 0.0 {
            return *idx as u32;
        }
    }

    candidates.last().unwrap().0 as u32
}

/// Full sampling pipeline: temperature → rep_pen → logit_bias → top_p.
pub fn sample(
    logits: &mut Vec<f32>,
    params: &SamplingParams,
    recent_tokens: &[u32],
) -> u32 {
    // 1. Apply logit bias (kill think tokens)
    apply_logit_bias(logits, &params.banned_tokens);

    // 2. Apply repetition penalty
    apply_repetition_penalty(logits, recent_tokens, params.rep_pen);

    // 3. Apply temperature
    apply_temperature(logits, params.temperature);

    // 4. Sample with top-p
    sample_top_p(logits, params.top_p)
}

/// Check if a stop sequence has been generated.
pub fn check_stop_sequence(generated: &[u32], stop_sequences: &[Vec<u32>]) -> bool {
    for stop_seq in stop_sequences {
        if generated.len() >= stop_seq.len() {
            let tail = &generated[generated.len() - stop_seq.len()..];
            if tail == stop_seq.as_slice() {
                return true;
            }
        }
    }
    false
}

/// Simple pseudo-random number generator (xorshift32).
/// For production, use a proper RNG. This avoids the `rand` dependency.
fn simple_random() -> f32 {
    use std::sync::atomic::{AtomicU32, Ordering};
    static STATE: AtomicU32 = AtomicU32::new(0xDEADBEEF);

    let mut x = STATE.load(Ordering::Relaxed);
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    STATE.store(x, Ordering::Relaxed);

    (x as f32) / (u32::MAX as f32)
}
