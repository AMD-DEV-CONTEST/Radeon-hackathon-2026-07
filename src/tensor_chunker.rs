//! Shader-level tensor chunking for Vulkan GPUs with per-allocation limits.
//!
//! Tesla P100 Vulkan drivers cap individual VkDeviceMemory allocations at ~976MB.
//! This module splits large weight matrices into multiple wgpu::Buffers that each
//! fit under that ceiling, then dispatches parallel compute shaders that compute
//! partial dot products and accumulates them via a reduction pass.
//!
//! Strategy: Column-split (split the K dimension).
//! - Each chunk holds a vertical slice of the weight matrix: [rows × chunk_cols]
//! - The matmul shader computes a partial dot product over chunk_cols elements
//! - The reduction shader sums all partial outputs into the final result
//!
//! This is transparent to the rest of the inference engine — `ChunkedTensor`
//! exposes the same matmul interface as a monolithic buffer would.

use bytemuck::{Pod, Zeroable};
use std::sync::Arc;
use wgpu;

/// Safe allocation ceiling — 900MB leaves headroom below the 976MB driver limit.
pub const MAX_ALLOC_BYTES: usize = 900_000_000;

/// Data type for weight storage.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Dtype {
    F32,
    F16,
    /// Q4_K: 4-bit quantized with per-block scales.
    /// Storage: 32 elements per 18 bytes (16 bytes data + 2 bytes scale).
    Q4K,
}

impl Dtype {
    /// Bytes per row of `cols` elements in this dtype.
    pub fn bytes_per_row(&self, cols: usize) -> usize {
        match self {
            Dtype::F32 => cols * 4,
            Dtype::F16 => cols * 2,
            Dtype::Q4K => {
                // Q4_K: 32 elements per block, each block = 18 bytes (16 data + 2 scale)
                let num_blocks = (cols + 31) / 32;
                num_blocks * 18
            }
        }
    }

    /// Bytes per element (approximate, for capacity planning).
    pub fn bytes_per_element_approx(&self) -> f64 {
        match self {
            Dtype::F32 => 4.0,
            Dtype::F16 => 2.0,
            Dtype::Q4K => 18.0 / 32.0, // 0.5625
        }
    }
}

/// Uniform parameters passed to the chunked matmul shader.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct ChunkedMatmulParams {
    /// Number of output rows (M dimension — typically 1 for token inference).
    pub m: u32,
    /// Number of columns in THIS chunk (partial K dimension).
    pub chunk_cols: u32,
    /// Total number of output elements (N = weight rows).
    pub n: u32,
    /// Column offset into the full K dimension for this chunk.
    pub col_offset: u32,
}

/// Uniform parameters for the reduction shader.
#[repr(C)]
#[derive(Debug, Clone, Copy, Pod, Zeroable)]
pub struct ReductionParams {
    /// Number of partial buffers to sum.
    pub num_chunks: u32,
    /// Number of output elements.
    pub n: u32,
    pub _pad0: u32,
    pub _pad1: u32,
}

/// A weight matrix split across multiple GPU buffers to stay under allocation limits.
pub struct ChunkedTensor {
    /// One buffer per chunk, each holding [rows × chunk_cols] weights.
    pub chunk_buffers: Vec<wgpu::Buffer>,
    /// Number of columns in each chunk (last may be smaller).
    pub chunk_col_counts: Vec<usize>,
    /// Total rows (N dimension — output size).
    pub rows: usize,
    /// Total columns (K dimension — input/hidden size).
    pub cols: usize,
    /// Data type.
    pub dtype: Dtype,
    /// Number of chunks.
    pub num_chunks: usize,
}

impl ChunkedTensor {
    /// Create a chunked tensor from raw weight data.
    ///
    /// `data` is the full weight matrix in row-major order [rows × cols],
    /// stored in the format specified by `dtype`.
    ///
    /// Returns a `ChunkedTensor` with buffers allocated on `device`.
    pub fn from_weights(
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        data: &[u8],
        rows: usize,
        cols: usize,
        dtype: Dtype,
    ) -> Self {
        let bytes_per_row = dtype.bytes_per_row(cols);
        let total_bytes = rows * bytes_per_row;
        assert!(
            data.len() >= total_bytes,
            "Data too short: got {} bytes, need {} for {}x{} {:?}",
            data.len(), total_bytes, rows, cols, dtype
        );

        // Calculate chunking along the column (K) dimension.
        // Each chunk stores ALL rows but only a subset of columns.
        // bytes_per_chunk_col = rows * dtype.bytes_per_element (for one column across all rows)
        let bytes_per_col_slice = match dtype {
            Dtype::F32 => rows * 4,
            Dtype::F16 => rows * 2,
            Dtype::Q4K => {
                // For Q4K, we chunk at block boundaries (32 elements).
                // bytes per "column-block" across all rows = rows * 18 / 32... 
                // Actually for Q4K it's simpler to chunk by rows (row-split).
                // But for consistency, we'll row-split Q4K.
                rows * 18 / 32 // approximate
            }
        };

        // For F32/F16: column-split. For Q4K: row-split (simpler with block alignment).
        let (chunk_buffers, chunk_col_counts, num_chunks) = if dtype == Dtype::Q4K {
            // Row-split for Q4K (each chunk gets a subset of rows, all columns)
            let row_bytes = dtype.bytes_per_row(cols);
            let max_rows_per_chunk = MAX_ALLOC_BYTES / row_bytes;
            let n_chunks = (rows + max_rows_per_chunk - 1) / max_rows_per_chunk;

            let mut buffers = Vec::with_capacity(n_chunks);
            let mut col_counts = Vec::with_capacity(n_chunks);

            for i in 0..n_chunks {
                let start_row = i * max_rows_per_chunk;
                let end_row = ((i + 1) * max_rows_per_chunk).min(rows);
                let chunk_rows = end_row - start_row;
                let chunk_bytes = chunk_rows * row_bytes;

                let start_byte = start_row * row_bytes;
                let end_byte = start_byte + chunk_bytes;

                let buffer = device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(&format!("chunk_q4k_{}", i)),
                    size: chunk_bytes as u64,
                    usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                });
                queue.write_buffer(&buffer, 0, &data[start_byte..end_byte]);
                buffers.push(buffer);
                // For row-split, "chunk_cols" represents chunk_rows for dispatch logic
                col_counts.push(chunk_rows);
            }

            (buffers, col_counts, n_chunks)
        } else {
            // Column-split for F32/F16
            let elem_size = match dtype {
                Dtype::F32 => 4usize,
                Dtype::F16 => 2usize,
                _ => unreachable!(),
            };

            // bytes for one column across all rows
            let col_stride = rows * elem_size;
            let max_cols_per_chunk = MAX_ALLOC_BYTES / col_stride;
            let n_chunks = (cols + max_cols_per_chunk - 1) / max_cols_per_chunk;

            let mut buffers = Vec::with_capacity(n_chunks);
            let mut col_counts = Vec::with_capacity(n_chunks);

            for i in 0..n_chunks {
                let start_col = i * max_cols_per_chunk;
                let end_col = ((i + 1) * max_cols_per_chunk).min(cols);
                let chunk_cols = end_col - start_col;
                let chunk_bytes = rows * chunk_cols * elem_size;

                // Extract column slice from row-major data.
                // Row-major layout: data[row * cols + col]
                // We need to extract columns [start_col..end_col] for all rows.
                let mut chunk_data = vec![0u8; chunk_bytes];
                for row in 0..rows {
                    let src_offset = (row * cols + start_col) * elem_size;
                    let dst_offset = (row * chunk_cols) * elem_size;
                    let row_slice_bytes = chunk_cols * elem_size;
                    chunk_data[dst_offset..dst_offset + row_slice_bytes]
                        .copy_from_slice(&data[src_offset..src_offset + row_slice_bytes]);
                }

                let buffer = device.create_buffer(&wgpu::BufferDescriptor {
                    label: Some(&format!("chunk_f32_{}", i)),
                    size: chunk_bytes as u64,
                    usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
                    mapped_at_creation: false,
                });
                queue.write_buffer(&buffer, 0, &chunk_data);
                buffers.push(buffer);
                col_counts.push(chunk_cols);
            }

            (buffers, col_counts, n_chunks)
        };

        tracing::info!(
            "ChunkedTensor: {}x{} {:?} → {} chunks (max {}MB each)",
            rows, cols, dtype, num_chunks,
            MAX_ALLOC_BYTES / 1_000_000
        );

        Self {
            chunk_buffers,
            chunk_col_counts,
            rows,
            cols,
            dtype,
            num_chunks,
        }
    }

    /// Returns true if this tensor needed chunking (more than 1 buffer).
    pub fn is_chunked(&self) -> bool {
        self.num_chunks > 1
    }

    /// Total bytes across all chunk buffers.
    pub fn total_bytes(&self) -> usize {
        let elem_size = match self.dtype {
            Dtype::F32 => 4,
            Dtype::F16 => 2,
            Dtype::Q4K => return self.chunk_col_counts.iter().map(|&r| self.dtype.bytes_per_row(self.cols) * r).sum(),
        };
        self.chunk_col_counts.iter().map(|&c| self.rows * c * elem_size).sum()
    }
}

/// Pipelines and bind group layouts for chunked matmul dispatch.
pub struct ChunkedMatmulPipeline {
    /// Chunked matmul (column-split partial dot product) — for multi-chunk tensors
    pub matmul_pipeline: wgpu::ComputePipeline,
    pub matmul_bgl: wgpu::BindGroupLayout,
    /// Reduction shader (sum partials)
    pub reduce_pipeline: wgpu::ComputePipeline,
    pub reduce_bgl: wgpu::BindGroupLayout,
    /// Tiled matmul (16×16 shared memory) — for single-chunk full matmuls
    pub tiled_pipeline: wgpu::ComputePipeline,
    pub tiled_bgl: wgpu::BindGroupLayout,
}

impl ChunkedMatmulPipeline {
    /// Create the chunked matmul and reduction pipelines.
    pub fn new(device: &wgpu::Device) -> Self {
        // Matmul shader: computes partial dot product for one chunk
        let matmul_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("chunked_matmul"),
            source: wgpu::ShaderSource::Wgsl(CHUNKED_MATMUL_WGSL.into()),
        });

        let matmul_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("chunked_matmul_bgl"),
            entries: &[
                // binding 0: input vector [K] (read-only storage)
                bgl_storage_ro(0),
                // binding 1: weight chunk [N × chunk_cols] (read-only storage)
                bgl_storage_ro(1),
                // binding 2: partial output [N] (read-write storage)
                bgl_storage_rw(2),
                // binding 3: params uniform
                bgl_uniform(3),
            ],
        });

        let matmul_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("chunked_matmul_layout"),
            bind_group_layouts: &[&matmul_bgl],
            push_constant_ranges: &[],
        });

        let matmul_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("chunked_matmul_pipeline"),
            layout: Some(&matmul_layout),
            module: &matmul_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        // Reduction shader: sums N partial buffers into final output
        let reduce_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("chunked_reduce"),
            source: wgpu::ShaderSource::Wgsl(REDUCTION_WGSL.into()),
        });

        let reduce_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("chunked_reduce_bgl"),
            entries: &[
                // binding 0: flat partials array [num_chunks × N] (read-only)
                bgl_storage_ro(0),
                // binding 1: final output [N] (read-write)
                bgl_storage_rw(1),
                // binding 2: params uniform
                bgl_uniform(2),
            ],
        });

        let reduce_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("chunked_reduce_layout"),
            bind_group_layouts: &[&reduce_bgl],
            push_constant_ranges: &[],
        });

        let reduce_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("chunked_reduce_pipeline"),
            layout: Some(&reduce_layout),
            module: &reduce_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        // Tiled matmul shader: 16×16 shared memory tiling for full matmuls
        let tiled_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("matmul_tiled"),
            source: wgpu::ShaderSource::Wgsl(include_str!("../shaders/matmul_tiled.wgsl").into()),
        });

        let tiled_bgl = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("tiled_matmul_bgl"),
            entries: &[
                bgl_storage_ro(0),  // matrix_a
                bgl_storage_ro(1),  // matrix_b
                bgl_storage_rw(2),  // matrix_c
                bgl_uniform(3),     // params {M, K, N, _pad}
            ],
        });

        let tiled_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("tiled_matmul_layout"),
            bind_group_layouts: &[&tiled_bgl],
            push_constant_ranges: &[],
        });

        let tiled_pipeline = device.create_compute_pipeline(&wgpu::ComputePipelineDescriptor {
            label: Some("tiled_matmul_pipeline"),
            layout: Some(&tiled_layout),
            module: &tiled_shader,
            entry_point: Some("main"),
            compilation_options: Default::default(),
            cache: None,
        });

        Self {
            matmul_pipeline,
            matmul_bgl,
            reduce_pipeline,
            reduce_bgl,
            tiled_pipeline,
            tiled_bgl,
        }
    }

    /// Dispatch a chunked matrix-vector multiply: output = weights × input.
    ///
    /// - `input_buf`: storage buffer containing the input vector [K elements, f32]
    /// - `output_buf`: storage buffer to write the result [N elements, f32]
    /// - `tensor`: the chunked weight tensor [N × K]
    /// - `encoder`: command encoder to record into
    /// - `device`: for creating temporary buffers
    /// - `queue`: for writing uniforms
    pub fn dispatch(
        &self,
        device: &wgpu::Device,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        tensor: &ChunkedTensor,
        input_buf: &wgpu::Buffer,
        output_buf: &wgpu::Buffer,
    ) {
        let n = tensor.rows; // output dimension
        let num_chunks = tensor.num_chunks;

        if num_chunks == 1 {
            // Single chunk — no reduction needed, write directly to output
            let params = ChunkedMatmulParams {
                m: 1,
                chunk_cols: tensor.chunk_col_counts[0] as u32,
                n: n as u32,
                col_offset: 0,
            };
            let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("chunk_params_0"),
                size: std::mem::size_of::<ChunkedMatmulParams>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

            let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some("chunk_bg_0"),
                layout: &self.matmul_bgl,
                entries: &[
                    wgpu::BindGroupEntry { binding: 0, resource: input_buf.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 1, resource: tensor.chunk_buffers[0].as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 2, resource: output_buf.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
                ],
            });

            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
            pass.set_pipeline(&self.matmul_pipeline);
            pass.set_bind_group(0, Some(&bg), &[]);
            // Dispatch: one invocation per output element, workgroup size 256
            let wg_count = ((n as u32) + 255) / 256;
            pass.dispatch_workgroups(wg_count, 1, 1);
            return;
        }

        // Multi-chunk path: dispatch per-chunk matmuls into partial buffers,
        // then reduce into final output.

        // Create partial output buffers (one per chunk, each [N] f32 elements)
        let partial_size = (n * 4) as u64; // f32
        let mut partial_bufs: Vec<wgpu::Buffer> = Vec::with_capacity(num_chunks);
        for i in 0..num_chunks {
            partial_bufs.push(device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(&format!("partial_{}", i)),
                size: partial_size,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }));
        }

        // Dispatch matmul for each chunk
        let mut col_offset: usize = 0;
        for i in 0..num_chunks {
            let chunk_cols = tensor.chunk_col_counts[i];
            let params = ChunkedMatmulParams {
                m: 1,
                chunk_cols: chunk_cols as u32,
                n: n as u32,
                col_offset: col_offset as u32,
            };
            let params_buf = device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(&format!("chunk_params_{}", i)),
                size: std::mem::size_of::<ChunkedMatmulParams>() as u64,
                usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
            queue.write_buffer(&params_buf, 0, bytemuck::cast_slice(&[params]));

            let bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: Some(&format!("chunk_bg_{}", i)),
                layout: &self.matmul_bgl,
                entries: &[
                    wgpu::BindGroupEntry { binding: 0, resource: input_buf.as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 1, resource: tensor.chunk_buffers[i].as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 2, resource: partial_bufs[i].as_entire_binding() },
                    wgpu::BindGroupEntry { binding: 3, resource: params_buf.as_entire_binding() },
                ],
            });

            let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
            pass.set_pipeline(&self.matmul_pipeline);
            pass.set_bind_group(0, Some(&bg), &[]);
            let wg_count = ((n as u32) + 255) / 256;
            pass.dispatch_workgroups(wg_count, 1, 1);

            col_offset += chunk_cols;
        }

        // Reduction pass: sum all partial buffers into output_buf
        // First, copy all partials into a single flat buffer [num_chunks × N]
        let flat_size = (num_chunks * n * 4) as u64;
        let flat_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("partials_flat"),
            size: flat_size,
            usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        for i in 0..num_chunks {
            encoder.copy_buffer_to_buffer(
                &partial_bufs[i], 0,
                &flat_buf, (i * n * 4) as u64,
                partial_size,
            );
        }

        // Dispatch reduction shader
        let reduce_params = ReductionParams {
            num_chunks: num_chunks as u32,
            n: n as u32,
            _pad0: 0,
            _pad1: 0,
        };
        let reduce_params_buf = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("reduce_params"),
            size: std::mem::size_of::<ReductionParams>() as u64,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        queue.write_buffer(&reduce_params_buf, 0, bytemuck::cast_slice(&[reduce_params]));

        let reduce_bg = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("reduce_bg"),
            layout: &self.reduce_bgl,
            entries: &[
                wgpu::BindGroupEntry { binding: 0, resource: flat_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 1, resource: output_buf.as_entire_binding() },
                wgpu::BindGroupEntry { binding: 2, resource: reduce_params_buf.as_entire_binding() },
            ],
        });

        let mut pass = encoder.begin_compute_pass(&wgpu::ComputePassDescriptor::default());
        pass.set_pipeline(&self.reduce_pipeline);
        pass.set_bind_group(0, Some(&reduce_bg), &[]);
        let wg_count = ((n as u32) + 255) / 256;
        pass.dispatch_workgroups(wg_count, 1, 1);
    }
}

// ── Helper functions for bind group layout entries ──────────────────────────

fn bgl_storage_ro(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only: true },
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn bgl_storage_rw(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Storage { read_only: false },
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

fn bgl_uniform(binding: u32) -> wgpu::BindGroupLayoutEntry {
    wgpu::BindGroupLayoutEntry {
        binding,
        visibility: wgpu::ShaderStages::COMPUTE,
        ty: wgpu::BindingType::Buffer {
            ty: wgpu::BufferBindingType::Uniform,
            has_dynamic_offset: false,
            min_binding_size: None,
        },
        count: None,
    }
}

// ── WGSL Shader Sources ─────────────────────────────────────────────────────

/// Chunked matmul shader: computes partial dot product for one column-chunk.
///
/// For each output element i (0..N):
///   partial_output[i] = sum over j in [0..chunk_cols] of:
///     input[col_offset + j] * weights[i * chunk_cols + j]
///
/// The input buffer contains the FULL input vector (all K elements).
/// The weight buffer contains only this chunk's columns (N × chunk_cols, row-major).
pub const CHUNKED_MATMUL_WGSL: &str = r#"
struct Params {
    m: u32,
    chunk_cols: u32,
    n: u32,
    col_offset: u32,
}

@group(0) @binding(0) var<storage, read> input: array<f32>;
@group(0) @binding(1) var<storage, read> weights: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;
@group(0) @binding(3) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n) {
        return;
    }

    var sum: f32 = 0.0;
    let weight_base = i * params.chunk_cols;
    let input_base = params.col_offset;

    // Unrolled inner loop for better throughput on P100
    var j: u32 = 0u;
    let cols = params.chunk_cols;

    // Process 4 elements at a time
    let cols_4 = cols & ~3u;
    while (j < cols_4) {
        sum += input[input_base + j]     * weights[weight_base + j];
        sum += input[input_base + j + 1u] * weights[weight_base + j + 1u];
        sum += input[input_base + j + 2u] * weights[weight_base + j + 2u];
        sum += input[input_base + j + 3u] * weights[weight_base + j + 3u];
        j = j + 4u;
    }
    // Remainder
    while (j < cols) {
        sum += input[input_base + j] * weights[weight_base + j];
        j = j + 1u;
    }

    output[i] = sum;
}
"#;

/// Reduction shader: sums N partial output buffers into one final output.
///
/// partials layout: [chunk_0[0..N], chunk_1[0..N], ..., chunk_{num_chunks-1}[0..N]]
/// For each output element i:
///   output[i] = sum over c in [0..num_chunks] of partials[c * N + i]
pub const REDUCTION_WGSL: &str = r#"
struct Params {
    num_chunks: u32,
    n: u32,
    _pad0: u32,
    _pad1: u32,
}

@group(0) @binding(0) var<storage, read> partials: array<f32>;
@group(0) @binding(1) var<storage, read_write> output: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let i = gid.x;
    if (i >= params.n) {
        return;
    }

    var sum: f32 = 0.0;
    for (var c: u32 = 0u; c < params.num_chunks; c = c + 1u) {
        sum += partials[c * params.n + i];
    }
    output[i] = sum;
}
"#;
