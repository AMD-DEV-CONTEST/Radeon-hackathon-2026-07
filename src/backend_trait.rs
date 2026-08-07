// src/backend_trait.rs
// Universal execution interface — both CUDA and WebGPU backends implement this.
// The rest of the codebase calls these methods without knowing which hardware is active.

/// The universal execution interface mapping computational tensors to physical hardware.
pub trait CesarOpsBackend: Send + Sync {
    /// Executes core matrix multiplication: C = A × B^T
    fn compute_matmul(
        &self,
        matrix_a: &[f32],
        matrix_b_t: &[f32],
        m: usize,
        k: usize,
        n: usize,
    ) -> Vec<f32>;

    /// Executes fused multi-head attention over context tokens
    fn compute_attention(
        &self,
        q: &[f32],
        k: &[f32],
        v: &[f32],
        seq_len: usize,
        head_dim: usize,
        n_heads: usize,
    ) -> Vec<f32>;

    /// Pipes live inference output into spatial detection pipelines
    fn run_geological_subtraction(
        &self,
        output_data: &[f32],
        target_lat: f64,
        target_lon: f64,
        magnetic_baseline: f32,
    ) -> Vec<f32>;

    /// Returns the backend name for logging
    fn backend_name(&self) -> &'static str;
}
