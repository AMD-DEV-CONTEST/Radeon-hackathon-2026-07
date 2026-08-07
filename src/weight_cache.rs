//! Pre-dequantized weight cache.
//! Dequantizes all model tensors once at load time and optionally uploads to GPU.
//! Eliminates per-token dequantization overhead (~90% of CPU inference time).

use std::collections::HashMap;
use crate::bridge;
use crate::gpu_context::GpuContext;
use crate::loader::ModelWeights;
use tracing::info;

/// CPU-side weight cache: all tensors pre-dequantized to f32.
pub struct WeightCache {
    pub tensors: HashMap<String, Vec<f32>>,
}

impl WeightCache {
    /// Dequantize all model tensors upfront. Takes a few seconds but saves massive time per token.
    pub fn from_model(weights: &ModelWeights) -> Self {
        info!("Pre-dequantizing {} tensors...", weights.tensors.len());
        let start = std::time::Instant::now();

        let mut tensors = HashMap::with_capacity(weights.tensors.len());

        for (name, region) in &weights.tensors {
            if let Some(bytes) = weights.tensor_bytes(name) {
                let n_elements: usize = region.shape.iter().product();
                let data = bridge::dequantize_tensor(bytes, region.quant_type, n_elements);
                tensors.insert(name.clone(), data);
            }
        }

        let elapsed = start.elapsed();
        let total_mb: usize = tensors.values().map(|v| v.len() * 4).sum::<usize>() / (1024 * 1024);
        info!("Weight cache ready: {} tensors, {}MB f32, built in {:?}", tensors.len(), total_mb, elapsed);

        Self { tensors }
    }

    /// Get a pre-dequantized tensor by name.
    pub fn get(&self, name: &str) -> Option<&[f32]> {
        self.tensors.get(name).map(|v| v.as_slice())
    }
}

/// GPU-resident weight cache: tensors stored as wgpu Buffers in VRAM.
/// Used for the forward pass — no per-token upload needed.
pub struct GpuWeightCache {
    pub buffers: HashMap<String, wgpu::Buffer>,
    pub gpu: std::sync::Arc<GpuContext>,
}

impl GpuWeightCache {
    /// Upload all pre-dequantized weights to GPU VRAM.
    /// Call this once at model load time.
    pub fn upload(cpu_cache: &WeightCache, gpu: std::sync::Arc<GpuContext>) -> Self {
        info!("Uploading weights to GPU VRAM...");
        let start = std::time::Instant::now();

        let mut buffers = HashMap::with_capacity(cpu_cache.tensors.len());
        let mut total_bytes: u64 = 0;

        for (name, data) in &cpu_cache.tensors {
            let bytes: &[u8] = bytemuck::cast_slice(data);
            let size = bytes.len() as u64;

            let buffer = gpu.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(name),
                size,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            });

            gpu.queue.write_buffer(&buffer, 0, bytes);
            total_bytes += size;
            buffers.insert(name.clone(), buffer);
        }

        // Flush all uploads
        gpu.queue.submit(std::iter::empty());
        gpu.device.poll(wgpu::Maintain::Wait);

        let elapsed = start.elapsed();
        info!("GPU weight upload complete: {} buffers, {}MB VRAM, {:?}",
            buffers.len(), total_bytes / (1024 * 1024), elapsed);

        Self { buffers, gpu }
    }

    /// Get a weight buffer reference for binding in compute passes.
    pub fn get_buffer(&self, name: &str) -> Option<&wgpu::Buffer> {
        self.buffers.get(name)
    }

    /// Run matmul using a pre-uploaded weight buffer (no upload needed per token).
    /// A[m,k] × B_T[n,k]^T → C[m,n]
    /// `a_f32` is the small input (hidden state), uploaded per-token (only ~6KB).
    /// `weight_name` references the pre-uploaded weight buffer in VRAM.
    pub fn matmul_with_cached_weight(
        &self,
        a_f32: &[f32],
        weight_name: &str,
        m: usize,
        k: usize,
        n: usize,
    ) -> Option<Vec<f32>> {
        let weight_buf = self.buffers.get(weight_name)?;

        // Upload only the small input vector (hidden state: 1×1536 = 6KB)
        let a_bytes: &[u8] = bytemuck::cast_slice(a_f32);
        self.gpu.queue.write_buffer(&self.gpu.buf_a, 0, a_bytes);

        // Write dimensions
        let dims = crate::wgpu_uniform::MatrixDimensions {
            m: m as u32,
            k: k as u32,
            n: n as u32,
            pad: 0,
        };
        self.gpu.queue.write_buffer(&self.gpu.buf_dims, 0, bytemuck::bytes_of(&dims));

        // Bind group using the pre-uploaded weight buffer directly
        let bind_group = self.gpu.device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("cached_matmul_bg"),
            layout: &self.gpu.bind_group_layout,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: self.gpu.buf_a.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: weight_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: self.gpu.buf_c.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 3, resource: self.gpu.buf_dims.as_entire_binding() },
            ],
        });

        let mut encoder = self.gpu.device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
            label: Some("cached_matmul_enc"),
        });

        {
            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor {
                label: Some("cached_matmul_pass"),
                timestamp_writes: None,
            });
            pass.set_pipeline(&self.gpu.matmul_pipeline);
            pass.set_bind_group(0, &bind_group, &[]);
            pass.dispatch_workgroups(
                ((n + 15) / 16) as u32,
                ((m + 15) / 16) as u32,
                1,
            );
        }

        // Readback
        let output_bytes = (m * n * 4) as u64;
        let staging = self.gpu.device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("cached_staging"),
            size: output_bytes,
            usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
            mapped_at_creation: false,
        });
        encoder.copy_buffer_to_buffer(&self.gpu.buf_c, 0, &staging, 0, output_bytes);

        let sub_idx = self.gpu.queue.submit(std::iter::once(encoder.finish()));
        let slice = staging.slice(0..output_bytes);

        let (tx, rx) = std::sync::mpsc::channel();
        slice.map_async(wgpu::MapMode::Read, move |result| {
            let _ = tx.send(result);
        });

        self.gpu.device.poll(wgpu::Maintain::WaitForSubmissionIndex(sub_idx));
        rx.recv().ok()?.ok()?;

        let mapped = slice.get_mapped_range();
        let result: Vec<f32> = bytemuck::cast_slice(&mapped).to_vec();
        drop(mapped);
        staging.unmap();

        Some(result)
    }
}
