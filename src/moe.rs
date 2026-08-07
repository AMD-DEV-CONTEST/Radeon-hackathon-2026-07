// src/moe.rs
use std::sync::Arc;
use crate::arena::InferenceArena;

#[derive(Debug)]
pub enum MoeError {
    ArenaOverflow,
    InvalidExpertIndex(usize),
}

pub struct MoeConfig {
    pub total_experts: usize,      // 128 for Qwen3.6
    pub num_active_experts: usize, // 8 for Top-8 routing
    pub hidden_size: usize,
    pub intermediate_size: usize,
}

pub struct MixtureOfExperts {
    pub config: MoeConfig,
    pub arena: Arc<InferenceArena>,
}

impl MixtureOfExperts {
    pub fn new(config: MoeConfig, arena: Arc<InferenceArena>) -> Self {
        Self { config, arena }
    }

    /// HIGH-PRECISION TOP-K EXPERT ROUTER
    /// Uses f64 arithmetic to evaluate gate logits, avoiding catastrophic cancellation.
    pub fn route_hidden_state(
        &self,
        hidden_state: &[f64],
        gate_weights: &[f64], // Shape: [total_experts, hidden_size]
        expert_indices_out: &mut [usize],
        expert_weights_out: &mut [f64],
    ) -> Result<(), MoeError> {
        let h_size = self.config.hidden_size;
        let num_exp = self.config.total_experts;
        let k = self.config.num_active_experts;

        let mut scores_scratch = [0.0f64; 128];

        if num_exp > scores_scratch.len() {
            return Err(MoeError::ArenaOverflow);
        }

        // Compute gating logits via high-precision dot products
        let mut max_logit = -f64::INFINITY;
        for exp_idx in 0..num_exp {
            let weight_offset = exp_idx * h_size;
            let mut dot_product = 0.0f64;
            for i in 0..h_size {
                dot_product += hidden_state[i] * gate_weights[weight_offset + i];
            }
            scores_scratch[exp_idx] = dot_product;
            if dot_product > max_logit {
                max_logit = dot_product;
            }
        }

        // Numerically stable Softmax
        let mut sum_exp = 0.0f64;
        for exp_idx in 0..num_exp {
            let exp_val = (scores_scratch[exp_idx] - max_logit).exp();
            scores_scratch[exp_idx] = exp_val;
            sum_exp += exp_val;
        }
        for exp_idx in 0..num_exp {
            scores_scratch[exp_idx] /= sum_exp;
        }

        // Selection Sort to extract Top-K active experts
        let mut selected_count = 0;
        let mut visited = [false; 128];

        while selected_count < k {
            let mut highest_prob = -1.0f64;
            let mut best_expert = 0;

            for exp_idx in 0..num_exp {
                if !visited[exp_idx] && scores_scratch[exp_idx] > highest_prob {
                    highest_prob = scores_scratch[exp_idx];
                    best_expert = exp_idx;
                }
            }

            visited[best_expert] = true;
            expert_indices_out[selected_count] = best_expert;
            expert_weights_out[selected_count] = highest_prob;
            selected_count += 1;
        }

        // Renormalize Top-K weights
        let k_weight_sum: f64 = expert_weights_out[0..k].iter().sum();
        for i in 0..k {
            expert_weights_out[i] /= k_weight_sum;
        }

        Ok(())
    }

    /// DISPATCH AND ACCUMULATION LOOP
    /// Routes matrix weights over correct physical hardware clusters.
    pub fn dispatch_experts(
        &self,
        hidden_state: &[f64],
        expert_indices: &[usize],
        expert_weights: &[f64],
        output_accumulator: &mut [f64],
    ) -> Result<(), MoeError> {
        let k = self.config.num_active_experts;
        let h_size = self.config.hidden_size;

        for step in 0..k {
            let expert_id = expert_indices[step];
            let weight_scale = expert_weights[step];

            let _expert_scratch = self.arena.storage.as_slice();

            // HARDWARE SHARDING BOUNDARY:
            // Experts 0-63 on GPU 0, Experts 64-127 on GPU 1
            if expert_id < 64 {
                // TODO: Dispatch to GPU 0 via GridBuffer::migrate
                for i in 0..h_size {
                    output_accumulator[i] += hidden_state[i] * weight_scale;
                }
            } else {
                // TODO: Dispatch to GPU 1 via GridBuffer::migrate
                for i in 0..h_size {
                    output_accumulator[i] += hidden_state[i] * weight_scale;
                }
            }
        }

        Ok(())
    }
}
