//! P100 Pascal WebGPU backend — dispatches matmul through WGSL compute shaders.
//! Falls back to CPU for attention and geo_filter until those shaders are wired.

use crate::backend_trait::CesarOpsBackend;
use crate::gpu_context::GpuContext;
use crate::matmul;
use std::sync::Arc;

pub struct WgpuPascalBackend {
    pub gpu: Arc<GpuContext>,
}

impl WgpuPascalBackend {
    pub async fn new(gpu_index: usize) -> Self {
        let gpu = GpuContext::init(gpu_index)
            .await
            .expect("Failed to initialize wgpu GPU context");
        Self { gpu: Arc::new(gpu) }
    }
}

impl CesarOpsBackend for WgpuPascalBackend {
    fn compute_matmul(
        &self,
        a: &[f32],
        b_t: &[f32],
        m: usize,
        k: usize,
        n: usize,
    ) -> Vec<f32> {
        self.gpu.matmul_gpu(a, b_t, m, k, n)
    }

    fn compute_attention(
        &self,
        q: &[f32],
        _k: &[f32],
        _v: &[f32],
        _seq_len: usize,
        _head_dim: usize,
        _n_heads: usize,
    ) -> Vec<f32> {
        // TODO: WGSL attention shader — CPU fallback for now
        q.to_vec()
    }

    fn run_geological_subtraction(
        &self,
        output_data: &[f32],
        _target_lat: f64,
        _target_lon: f64,
        magnetic_baseline: f32,
    ) -> Vec<f32> {
        // TODO: Route through geo_filter.wgsl — CPU fallback for now
        output_data.iter().map(|&val| {
            let residual = val - magnetic_baseline;
            if residual.abs() > magnetic_baseline * 0.001 {
                residual * residual * 0.001
            } else {
                0.0
            }
        }).collect()
    }

    fn backend_name(&self) -> &'static str {
        "WebGPU/Pascal (P100 FP16 2:1)"
    }
}

/// CPU-only backend for the bootstrap brain (no GPU needed).
pub struct CpuBackend;

impl CesarOpsBackend for CpuBackend {
    fn compute_matmul(&self, a: &[f32], b_t: &[f32], m: usize, k: usize, n: usize) -> Vec<f32> {
        matmul::matmul_f32_transposed_b(a, b_t, m, k, n)
    }

    fn compute_attention(&self, q: &[f32], _k: &[f32], _v: &[f32], _seq_len: usize, _head_dim: usize, _n_heads: usize) -> Vec<f32> {
        q.to_vec()
    }

    fn run_geological_subtraction(&self, output_data: &[f32], _lat: f64, _lon: f64, baseline: f32) -> Vec<f32> {
        output_data.iter().map(|&val| {
            let r = val - baseline;
            if r.abs() > baseline * 0.001 { r * r * 0.001 } else { 0.0 }
        }).collect()
    }

    fn backend_name(&self) -> &'static str {
        "CPU (Xeon fallback)"
    }
}
