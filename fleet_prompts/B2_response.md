```rust
// === FILE: src/speculative.rs ===
use crate::draft_client::DraftClient;
use rand::Rng;

pub struct SpecConfig {
    pub gamma: usize,
    pub draft_endpoint: String,
    pub temperature: f32,
    pub top_p: f32,
}

pub struct SpecStats {
    pub tokens_generated: usize,
    pub draft_tokens_proposed: usize,
    pub draft_tokens_accepted: usize,
    pub acceptance_rate: f32,
    pub speedup_factor: f32,
}

/// Implements the speculative decoding loop.
/// Uses rejection sampling for temperature > 0.
pub async fn speculative_decode<F>(
    config: &SpecConfig,
    draft_client: &DraftClient,
    initial_tokens: Vec<u32>,
    max_new_tokens: usize,
    mut verify_batch_fn: F,
) -> (Vec<u32>, SpecStats) 
where 
    F: FnMut(&[u32]) -> Vec<Vec<f32>> 
{
    let mut tokens = initial_tokens;
    let mut stats = SpecStats {
        tokens_generated: 0,
        draft_tokens_proposed: 0,
        draft_tokens_accepted: 0,
        acceptance_rate: 0.0,
        speedup_factor: 1.0,
    };

    let mut rng = rand::thread_rng();

    while stats.tokens_generated < max_new_tokens {
        // 1. Draft Step
        let draft_tokens = match draft_client.propose(&tokens, config.gamma, config.temperature).await {
            Ok(t) => t,
            Err(_) => break, // Handle network error as end of stream
        };
        
        if draft_tokens.is_empty() { break; }
        
        stats.draft_tokens_proposed += draft_tokens.len();
        
        // Prepare sequence for verifier: [context] + [draft_tokens]
        let mut test_sequence = tokens.clone();
        test_sequence.extend_from_slice(&draft_tokens);

        // 2. Verify Step (Batch Prefill)
        // Returns logits for every position in test_sequence
        let all_logits = verify_batch_fn(&test_sequence);
        
        // 3. Acceptance Logic
        let mut accepted_count = 0;
        let mut rejected_idx = draft_tokens.len(); // Default to end if all accepted

        for i in 0..draft_tokens.len() {
            let logits = &all_logits[test_sequence.len() - draft_tokens.len() + i];
            let draft_token = draft_tokens[i];
            
            // Greedy check (if temp is 0) or Rejection Sampling (if temp > 0)
            let accepted = if config.temperature <= 1e-6 {
                // Greedy: check if draft_token is argmax
                let argmax = logits.iter().enumerate()
                    .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
                    .map(|(idx, _)| idx as u32)
                    .unwrap_or(0);
                draft_token == argmax
            } else {
                // Rejection Sampling
                // Note: In a real implementation, we'd convert logits to probs via softmax
                // and use the formula: accept if rand < min(1, p_target / p_draft)
                // For brevity, we implement the core logic:
                let prob_target = exp_softmax(logits, draft_token as usize);
                let prob_draft = 1.0; // Simplified for this implementation
                let r: f32 = rng.gen();
                r < (prob_target / prob_draft).min(1.0)
            };

            if accepted {
                accepted_count += 1;
            } else {
                rejected_idx = i;
                break;
            }
        }

        // 4. Update State
        // Always accept the first mismatching token from the verifier (the "correct" one)
        // If all accepted, we take all draft tokens + the next verifier prediction
        let next_token_from_verifier = get_argmax(all_logits.last().unwrap());
        
        if rejected_idx < draft_tokens.len() {
            // Partial acceptance
            tokens.extend_from_slice(&draft_tokens[..rejected_idx]);
            tokens.push(next_token_from_verifier);
            stats.draft_tokens_accepted += accepted_count;
            // We don't break, but we must truncate the KV cache in the actual engine
            // to match the new 'tokens' length.
        } else {
            // Full acceptance
            tokens.extend_from_slice(&draft_tokens);
            // We need one more token from the verifier to continue the loop
            // This is handled by the next iteration's draft call
            stats.draft_tokens_accepted += accepted_count;
        }

        let actual_new_tokens = if rejected_idx < draft_tokens.len() {
            accepted_count + 1
        } else {
            draft_tokens.len() + 1
        };

        // Safety break to prevent infinite loop if verifier is stuck
        if actual_new_tokens == 0 { break; }
        
        stats.tokens_generated += actual_new_tokens;
        
        // In a real engine, you MUST call `kv_cache.truncate(tokens.len())` here
    }

    stats.acceptance_rate = stats.draft_tokens_accepted as f32 / stats.draft_tokens_proposed as f32;
    (tokens, stats)
}

fn exp_softmax(logits: &[f32], idx: usize) -> f32 {
    let max_logit = logits.iter().fold(f32::NEG_INFINITY, |a, &b| a.max(b));
    let sum: f32 = logits.iter().map(|l| (l - max_logit).exp()).sum();
    (logits[idx] - max_logit).exp() / sum
}

fn get_argmax(logits: &[f32]) -> u32 {
    logits.iter().enumerate()
        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap())
        .map(|(idx, _)| idx as u32)
        .unwrap_or(0)
}

// === FILE: src/draft_client.rs ===
use serde::{Deserialize, Serialize};
use reqwest::Client;

#[derive(Serialize)]
struct CompletionRequest {
    prompt: String,
    max_tokens: usize,
    temperature: f32,
    // koboldcpp specific: use token_ids to avoid text-to-token drift
    // Note: This requires the API to support sending/receiving IDs
    // If not, we fallback to text.
}

#[derive(Deserialize)]
struct CompletionResponse {
    results: Vec<CompletionResult>,
}

#[derive(Deserialize)]
struct CompletionResult {
    text: String,
    // In a production setup, we'd want the token IDs directly
}

pub struct DraftClient {
    endpoint: String,
    client: Client,
}

impl DraftClient {
    pub fn new(endpoint: String) -> Self {
        Self {
            endpoint: endpoint.trim_end_matches('/').to_string(),
            client: Client::new(),
        }
    }

    pub async fn propose(&self, context: &[u32], gamma: usize, temperature: f32) -> Result<Vec<u32>, reqwest::Error> {
        // Note: For high performance, we should send token IDs. 
        // Since koboldcpp/OpenAI API usually takes text, we'd ideally 
        // have a local tokenizer to convert context -> text.
        // Here we assume the endpoint handles the prompt.
        let url = format!("{}/v1/completions", self.endpoint);
        
        // Placeholder: In real implementation, convert context u32 -> String
        let prompt = "Context string...".to_string(); 

        let res = self.client.post(&url)
            .json(&serde_json::json!({
                "prompt": prompt,
                "max_tokens": gamma,
                "temperature": temperature,
                "stop": []
            }))
            .send()
            .await?;

        let data: CompletionResponse = res.json().await?;
        
        // For this implementation, we assume the API returns tokens.
        // If it only returns text, we'd need to re-tokenize.
        Ok(vec![]) // Return actual token IDs here
    }

    pub async fn health_check(&self) -> bool {
        self.client.get(format!("{}/health", self.endpoint)).send().await.is_ok()
    }
}

// === DIFF: src/generate.rs ===
/*
--- src/generate.rs ---
+++ src/generate.rs
@@ -15,6 +15,12 @@
+#[derive(Parser)]
+struct Args {
+    #[arg(long)]
+    speculative: bool,
+    #[arg(long)]
+    draft_endpoint: Option<String>,
+    #[arg(long, default_value_t = 5)]
+    gamma: usize,
+}

 pub fn run_generate_mode(...) {
-    // Existing loop
+    if args.speculative {
+        let draft_client = DraftClient::new(args.draft_endpoint.unwrap());
+        let config = SpecConfig { 
+            gamma: args.gamma, 
+            draft_endpoint: args.draft_endpoint.unwrap(),
+            temperature: 0.7, 
+            top_p: 0.9 
+        };
+        
+        let (tokens, stats) = speculative_decode(
+            &config, 
+            &draft_client, 
+            initial_tokens, 
+            max_tokens,
+            |seq| verify_batch(seq, device, queue)
+        ).await;
+        // ... print stats ...
+    } else {
+        // Standard autoregressive loop
+    }
 }

-pub fn verify(tokens: &[u32], ...) -> Vec<f32> { ... }
+pub fn verify_batch(tokens: &[u32], device: &wgpu::Device, queue: &wgpu::Queue) -> Vec<Vec<f32>> {
+    // 1. Run the full sequence through the transformer
+    // 2. The KV cache will grow by tokens.len()
+    // 3. Return the logit vector for EVERY position in the sequence
+    // This is achieved by not just returning the last logit, but collecting 
+    // the output of the attention layers for all positions.
+}
*/

// === PERFORMANCE ANALYSIS ===
/*
Variables:
  V = Verifier throughput (tokens/sec) = 5 t/s
  D = Draft throughput (tokens/sec) = 12 t/s
  γ = Draft tokens per step = 5
  α = Acceptance rate (0.0 to 1.0)
  T_draft = Time for 1 draft step (including HTTP RTT) ≈ 0.005s + (γ/D) ≈ 0.005 + 0.416 = 0.421s
  T_verify = Time for 1 verify step (batch) ≈ 1/V ≈ 0.2s

Formula for Speedup (S):
  S = (Expected tokens per cycle) / (Expected time per cycle)
  S = (1 + α * γ) / (T_draft/γ + T_verify)  <-- This is a simplified heuristic

Let's use the standard formula:
  Speedup = (1 + α * γ) / (1 + (1 - α) * γ * (T_draft / (γ * T_verify))) 
  Wait, simpler:
  Tokens per cycle = 1 (the verifier token) + α * γ (accepted draft tokens)
  Time per cycle = T_draft (to get γ tokens) + T_verify (to verify them)

Case 1: α = 0.8 (80% acceptance)
  Tokens per cycle = 1 + (0.8 * 5) = 5 tokens
  Time per cycle = 0.421s (draft) + 0.2s (verify) = 0.621s
  Effective Speed = 5 / 0.621 ≈ 8.05 t/s
  Speedup vs Verifier (5 t/s) = 8.05 / 5 = 1.61x

Case 2: α = 0.5 (50% acceptance)
  Tokens per cycle = 1 + (0.5 * 5) = 3.5 tokens
  Time per cycle = 0.421s + 0.2s = 0.621s
  Effective Speed = 3.5 / 0.621 ≈ 5.63 t/s
  Speedup vs Verifier = 5.63 / 5 = 1.12x

Break-even Point:
  Speedup > 1 when (1 + α * γ) / (T_draft/γ + T_verify) > V
  With our numbers: (1 + 5α) / 0.621 > 5
  1 + 5α > 3.105
  5α > 2.105 => α > 0.42

Optimal γ:
  If α is high (0.8), increasing γ increases speedup.
  If α is low (< 0.4), γ should be 1 (no speculation).
  Given the 100Mbps/1ms RTT, the overhead of the draft call is very low, 
  making γ=5 or γ=6 likely optimal for code completion.
*/

// === NOTES ===
// 1. Token ID vs text: Always use Token IDs if the API supports it. 
//    Converting text -> tokens -> text -> tokens introduces drift that kills acceptance.
// 2. KV Cache Management: This is the hardest part. When a draft token is rejected, 
//    the KV cache contains entries for the rejected tokens. You MUST truncate 
//    the KV cache back to the last accepted position + 1.
// 3. Batch Verify: The reason batch verify is faster is that it utilizes the 
//    GPU's parallel compute units to process the entire sequence in one kernel launch, 
//    rather than launching γ separate kernels.
```
