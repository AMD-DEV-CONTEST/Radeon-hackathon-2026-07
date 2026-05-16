//! Safe tensor loading with automatic chunking for Vulkan allocation limits.
//!
//! Intercepts tensor allocation during GGUF model loading. If a tensor's raw byte
//! footprint exceeds the 900MB ceiling, it's automatically routed through
//! `ChunkedTensor::from_weights()` instead of a single buffer allocation.
//!
//! Small tensors (biases, layer norms, attention QKV under 900MB) go through the
//! fast single-buffer path with zero overhead.

use crate::tensor_chunker::{ChunkedMatmulPipeline, ChunkedTensor, Dtype, MAX_ALLOC_BYTES};
use std::collections::HashMap;
use std::sync::Arc;
use tracing::{info, warn};

/// Allocation ceiling in bytes. Tensors above this get chunked.
const CHUNK_THRESHOLD: usize = MAX_ALLOC_BYTES;

/// Quantization type IDs from GGUF spec.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TensorType {
    F32 = 0,
    F16 = 1,
    Q4_0 = 2,
    Q4_1 = 3,
    Q5_0 = 6,
    Q5_1 = 7,
    Q8_0 = 8,
    Q4_K = 12,
    Q5_K = 13,
    Q6_K = 14,
    IQ4_XS = 17,
    BF16 = 28,
}

impl TensorType {
    /// Convert from raw GGUF quant_type u32.
    pub fn from_gguf(qt: u32) -> Option<Self> {
        match qt {
            0 => Some(Self::F32),
            1 => Some(Self::F16),
            2 => Some(Self::Q4_0),
            3 => Some(Self::Q4_1),
            6 => Some(Self::Q5_0),
            7 => Some(Self::Q5_1),
            8 => Some(Self::Q8_0),
            12 => Some(Self::Q4_K),
            13 => Some(Self::Q5_K),
            14 => Some(Self::Q6_K),
            17 => Some(Self::IQ4_XS),
            28 => Some(Self::BF16),
            _ => None,
        }
    }

    /// Map to our chunker's Dtype (for matmul dispatch).
    /// Only F32, F16, and Q4_K have native shader support.
    /// Others get dequantized to F32 before GPU upload.
    pub fn to_chunker_dtype(&self) -> Dtype {
        match self {
            Self::F32 => Dtype::F32,
            Self::F16 => Dtype::F16,
            Self::Q4_K | Self::Q4_0 | Self::Q4_1 => Dtype::Q4K,
            // Everything else gets dequantized to F32 for GPU compute
            _ => Dtype::F32,
        }
    }

    /// Compute raw byte size for a tensor of given element count.
    pub fn byte_size(&self, n_elements: usize) -> usize {
        match self {
            Self::F32 => n_elements * 4,
            Self::F16 | Self::BF16 => n_elements * 2,
            Self::Q4_0 => (n_elements + 31) / 32 * 18,
            Self::Q4_1 => (n_elements + 31) / 32 * 20,
            Self::Q5_0 => (n_elements + 31) / 32 * 34,
            Self::Q5_1 => (n_elements + 31) / 32 * 36,
            Self::Q8_0 => (n_elements + 31) / 32 * 34,  // 2 (f16) + 32 (i8)
            Self::Q4_K => (n_elements + 255) / 256 * 176,
            Self::Q5_K => (n_elements + 255) / 256 * 176, // 2+2+12+32+128
            Self::Q6_K => (n_elements + 255) / 256 * 210,
            Self::IQ4_XS => (n_elements + 255) / 256 * 136, // 2+2+4+128
        }
    }

    /// Whether this type needs dequantization before GPU matmul.
    pub fn needs_dequant(&self) -> bool {
        !matches!(self, Self::F32 | Self::F16 | Self::Q4_K)
    }
}

/// Error type for tensor loading failures.
#[derive(Debug)]
pub enum MemoryError {
    /// Tensor data is too short for the declared shape.
    DataTooShort { expected: usize, got: usize },
    /// Buffer allocation failed on GPU.
    AllocationFailed(String),
    /// Unsupported quantization type.
    UnsupportedType(u32),
}

impl std::fmt::Display for MemoryError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::DataTooShort { expected, got } =>
                write!(f, "Tensor data too short: need {} bytes, got {}", expected, got),
            Self::AllocationFailed(msg) => write!(f, "GPU allocation failed: {}", msg),
            Self::UnsupportedType(qt) => write!(f, "Unsupported GGUF quant type: {}", qt),
        }
    }
}

/// Handle to a loaded tensor — either a single buffer or chunked.
pub enum TensorHandle {
    /// Standard single-buffer tensor (fits under allocation ceiling).
    Single {
        buffer: wgpu::Buffer,
        shape: [usize; 2],
        dtype: Dtype,
    },
    /// Chunked tensor split across multiple buffers.
    Chunked {
        tensor: ChunkedTensor,
    },
}

impl TensorHandle {
    /// Returns true if this tensor required chunking.
    pub fn is_chunked(&self) -> bool {
        matches!(self, Self::Chunked { .. })
    }

    /// Get the shape [rows, cols].
    pub fn shape(&self) -> [usize; 2] {
        match self {
            Self::Single { shape, .. } => *shape,
            Self::Chunked { tensor } => [tensor.rows, tensor.cols],
        }
    }
}

/// Device-level tensor registry that tracks all loaded tensors for cleanup.
pub struct TensorRegistry {
    pub handles: HashMap<String, TensorHandle>,
    pub pipeline: ChunkedMatmulPipeline,
    pub device: Arc<wgpu::Device>,
    pub queue: Arc<wgpu::Queue>,
    pub stats: LoadStats,
}

/// Statistics about tensor loading.
#[derive(Debug, Default, Clone)]
pub struct LoadStats {
    pub total_tensors: usize,
    pub chunked_tensors: usize,
    pub single_tensors: usize,
    pub total_bytes: usize,
    pub total_chunks: usize,
}

impl TensorRegistry {
    /// Create a new registry with the chunked matmul pipeline.
    pub fn new(device: Arc<wgpu::Device>, queue: Arc<wgpu::Queue>) -> Self {
        let pipeline = ChunkedMatmulPipeline::new(&device);
        Self {
            handles: HashMap::new(),
            pipeline,
            device,
            queue,
            stats: LoadStats::default(),
        }
    }

    /// Load a tensor safely, automatically chunking if it exceeds the allocation ceiling.
    ///
    /// This is the main entry point called by the GGUF model loader for each tensor.
    /// Small tensors get a fast single-buffer path. Large tensors get chunked.
    pub fn load_tensor_safe(
        &mut self,
        name: &str,
        shape: [usize; 2],
        data_type: TensorType,
        raw_bytes: &[u8],
    ) -> Result<(), MemoryError> {
        let [rows, cols] = shape;
        let n_elements = rows * cols;
        let byte_size = data_type.byte_size(n_elements);

        // Validate data length
        if raw_bytes.len() < byte_size {
            return Err(MemoryError::DataTooShort {
                expected: byte_size,
                got: raw_bytes.len(),
            });
        }

        let dtype = data_type.to_chunker_dtype();

        let handle = if byte_size <= CHUNK_THRESHOLD {
            // ── Upload path: dequant + transpose at load time for weight matrices ──
            // 2D weight tensors (projections): dequant Q6_K → F32, then transpose [N×K] → [K×N]
            // 1D tensors (norms, biases): dequant only, no transpose
            let is_2d_weight = shape[0] > 1 && shape[1] > 1;
            let needs_dequant = data_type.needs_dequant() || dtype == Dtype::F16;

            let (upload_data, upload_size) = if needs_dequant {
                let n_elements = rows * cols;
                let mut f32_data = if dtype == Dtype::F16 {
                    dequant_f16_to_f32(&raw_bytes[..byte_size], n_elements)
                } else {
                    dequantize_to_f32(raw_bytes, n_elements, data_type)
                };

                // GGUF stores shapes as [cols, rows] = [K, N] (inner dim first).
                // The tiled matmul reads B as [K × N] which matches GGUF layout directly.
                // NO TRANSPOSE NEEDED.
                if is_2d_weight {
                    // No transpose — GGUF layout matches shader expectation
                }

                let bytes: Vec<u8> = f32_data.iter().flat_map(|f| f.to_le_bytes()).collect();
                (bytes, n_elements * 4)
            } else {
                // F32 tensor — no transpose needed, GGUF layout matches shader
                (raw_bytes[..byte_size].to_vec(), byte_size)
            };

            let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some(name),
                size: upload_size as u64,
                usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            });
            self.queue.write_buffer(&buffer, 0, &upload_data);

            self.stats.single_tensors += 1;
            // Shape stays as-is (GGUF [K, N] maps to shader [K × N])
            TensorHandle::Single { buffer, shape, dtype: Dtype::F32 }
        } else {
            // ── Chunked path: split across multiple buffers ──────────────────
            info!(
                "Chunking tensor '{}': {}x{} {:?} = {:.1}MB (exceeds {}MB ceiling)",
                name, rows, cols, dtype,
                byte_size as f64 / 1e6,
                CHUNK_THRESHOLD / 1_000_000
            );

            let tensor = ChunkedTensor::from_weights(
                &self.device,
                &self.queue,
                &raw_bytes[..byte_size],
                rows,
                cols,
                dtype,
            );

            self.stats.chunked_tensors += 1;
            self.stats.total_chunks += tensor.num_chunks;
            TensorHandle::Chunked { tensor }
        };

        self.stats.total_tensors += 1;
        self.stats.total_bytes += byte_size;
        self.handles.insert(name.to_string(), handle);

        Ok(())
    }

    /// Dispatch a matrix-vector multiply using a loaded tensor.
    ///
    /// Transparently handles both single-buffer and chunked tensors.
    pub fn dispatch_matmul(
        &self,
        name: &str,
        encoder: &mut wgpu::CommandEncoder,
        input_buf: &wgpu::Buffer,
        output_buf: &wgpu::Buffer,
    ) -> bool {
        let handle = match self.handles.get(name) {
            Some(h) => h,
            None => {
                warn!("Tensor '{}' not found in registry", name);
                return false;
            }
        };

        match handle {
            TensorHandle::Chunked { tensor } => {
                self.pipeline.dispatch(
                    &self.device,
                    &self.queue,
                    encoder,
                    tensor,
                    input_buf,
                    output_buf,
                );
                true
            }
            TensorHandle::Single { .. } => {
                // Single-buffer tensors use the standard matmul pipeline
                // (handled by gpu_context.rs matmul_gpu path)
                false
            }
        }
    }

    /// Print loading statistics.
    pub fn print_stats(&self) {
        info!(
            "Tensor loading complete: {} total ({} single, {} chunked across {} buffers), {:.2} GB",
            self.stats.total_tensors,
            self.stats.single_tensors,
            self.stats.chunked_tensors,
            self.stats.total_chunks,
            self.stats.total_bytes as f64 / 1e9,
        );
    }

    /// Drop all tensor handles, freeing GPU memory.
    pub fn clear(&mut self) {
        self.handles.clear();
        self.stats = LoadStats::default();
    }

    /// Get a reference to the underlying wgpu::Buffer for a single-buffer tensor.
    /// Returns None if the tensor is chunked or not found.
    pub fn get_buffer(&self, name: &str) -> Option<&wgpu::Buffer> {
        match self.handles.get(name)? {
            TensorHandle::Single { buffer, .. } => Some(buffer),
            TensorHandle::Chunked { .. } => None,
        }
    }

    /// Take ownership of a buffer from the registry (removes it).
    /// Used during model weight mapping to build LayerWeights structs.
    pub fn take_buffer(&mut self, name: &str) -> Option<wgpu::Buffer> {
        let handle = self.handles.remove(name)?;
        match handle {
            TensorHandle::Single { buffer, .. } => Some(buffer),
            TensorHandle::Chunked { .. } => {
                // Can't extract a single buffer from a chunked tensor
                None
            }
        }
    }
}


// ── CPU-side dequantization ─────────────────────────────────────────────────

/// Dequantize Q6_K / Q4_K / Q8_0 weights to F32 on CPU.
/// This is the simple path — GPU dequant via shader is faster but requires
/// an extra dispatch per layer. CPU dequant happens once at load time.
fn dequantize_to_f32(data: &[u8], n_elements: usize, dtype: TensorType) -> Vec<f32> {
    match dtype {
        TensorType::Q8_0 => dequant_q8_0(data, n_elements),
        TensorType::Q4_0 => dequant_q4_0(data, n_elements),
        TensorType::Q4_K => dequant_q4_k(data, n_elements),
        TensorType::Q6_K => dequant_q6_k(data, n_elements),
        TensorType::Q5_K => dequant_q5_k(data, n_elements),
        TensorType::IQ4_XS => dequant_iq4_xs(data, n_elements),
        _ => {
            // Fallback: treat as raw f32
            let mut out = vec![0.0f32; n_elements];
            let bytes_needed = n_elements * 4;
            if data.len() >= bytes_needed {
                for i in 0..n_elements {
                    out[i] = f32::from_le_bytes([
                        data[i*4], data[i*4+1], data[i*4+2], data[i*4+3]
                    ]);
                }
            }
            out
        }
    }
}

/// Convert F16 bytes to F32.
fn dequant_f16_to_f32(data: &[u8], n_elements: usize) -> Vec<f32> {
    let mut out = vec![0.0f32; n_elements];
    for i in 0..n_elements.min(data.len() / 2) {
        let bits = u16::from_le_bytes([data[i*2], data[i*2+1]]);
        out[i] = f16_to_f32(bits);
    }
    out
}

fn f16_to_f32(bits: u16) -> f32 {
    let sign = ((bits >> 15) & 1) as u32;
    let exp = ((bits >> 10) & 0x1F) as u32;
    let mant = (bits & 0x3FF) as u32;

    if exp == 0 {
        if mant == 0 { return 0.0; }
        // Subnormal
        let val = (mant as f32) * 5.9604644775390625e-8;
        return if sign == 1 { -val } else { val };
    }
    if exp == 31 {
        return if sign == 1 { f32::NEG_INFINITY } else { f32::INFINITY };
    }

    let f32_exp = (exp as i32 - 15 + 127) as u32;
    let f32_bits = (sign << 31) | (f32_exp << 23) | (mant << 13);
    f32::from_bits(f32_bits)
}

/// Q8_0: block_size=32, each block = 2 bytes scale (f16) + 32 bytes (i8 per element)
fn dequant_q8_0(data: &[u8], n_elements: usize) -> Vec<f32> {
    let block_size = 32;
    let block_bytes = 34; // 2 (f16 scale) + 32 (i8 values)
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let offset = b * block_bytes;
        if offset + block_bytes > data.len() { break; }

        let scale_bits = u16::from_le_bytes([data[offset], data[offset + 1]]);
        let scale = f16_to_f32(scale_bits);

        for i in 0..block_size {
            let elem_idx = b * block_size + i;
            if elem_idx >= n_elements { break; }
            let val = data[offset + 2 + i] as i8;
            out[elem_idx] = scale * (val as f32);
        }
    }
    out
}

/// Q4_0: block_size=32, each block = 2 bytes scale (f16) + 16 bytes (4-bit pairs)
fn dequant_q4_0(data: &[u8], n_elements: usize) -> Vec<f32> {
    let block_size = 32;
    let block_bytes = 18; // 2 (f16 scale) + 16 (nibble pairs)
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let offset = b * block_bytes;
        if offset + block_bytes > data.len() { break; }

        let scale_bits = u16::from_le_bytes([data[offset], data[offset + 1]]);
        let scale = f16_to_f32(scale_bits);

        for i in 0..16 {
            let byte = data[offset + 2 + i];
            let lo = (byte & 0x0F) as i32 - 8;
            let hi = ((byte >> 4) & 0x0F) as i32 - 8;

            let idx0 = b * block_size + i * 2;
            let idx1 = idx0 + 1;
            if idx0 < n_elements { out[idx0] = scale * (lo as f32); }
            if idx1 < n_elements { out[idx1] = scale * (hi as f32); }
        }
    }
    out
}

/// Q4_K: block_size=256, complex layout with sub-block scales
fn dequant_q4_k(data: &[u8], n_elements: usize) -> Vec<f32> {
    // Q4_K_M: 256 elements per super-block
    // Layout: 2 (d f16) + 2 (dmin f16) + 12 (scales) + 128 (nibbles) = 144 bytes
    let block_size = 256;
    let block_bytes = 144;
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let offset = b * block_bytes;
        if offset + block_bytes > data.len() { break; }

        let d = f16_to_f32(u16::from_le_bytes([data[offset], data[offset + 1]]));
        let dmin = f16_to_f32(u16::from_le_bytes([data[offset + 2], data[offset + 3]]));

        // Scales: 12 bytes starting at offset+4
        let scales_offset = offset + 4;
        // Nibbles: 128 bytes starting at offset+16
        let qs_offset = offset + 16;

        for sub in 0..8 {
            // Extract 6-bit scale and min for this sub-block
            let sc = extract_6bit(&data[scales_offset..scales_offset+6], sub);
            let mn = extract_6bit(&data[scales_offset+6..scales_offset+12], sub);

            let d_sc = d * (sc as f32);
            let d_mn = dmin * (mn as f32);

            for j in 0..32 {
                let elem_idx = b * block_size + sub * 32 + j;
                if elem_idx >= n_elements { break; }

                let byte_idx = (sub * 32 + j) / 2;
                let byte = data[qs_offset + byte_idx];
                let nibble = if j % 2 == 0 { byte & 0x0F } else { (byte >> 4) & 0x0F };

                out[elem_idx] = d_sc * (nibble as f32) - d_mn;
            }
        }
    }
    out
}

/// Q6_K: block_size=256, layout: ql[128] + qh[64] + scales[16] + d[2] = 210 bytes
///
/// Mirrors llama.cpp's `dequantize_row_q6_K` in `ggml-quants.c`. The 256
/// elements are processed as two 128-element halves. Within each half, an
/// inner loop l=0..32 produces 4 outputs at positions l, l+32, l+64, l+96
/// from interleaved ql/qh nibbles and signed sub-block scales.
fn dequant_q6_k(data: &[u8], n_elements: usize) -> Vec<f32> {
    let block_size = 256;
    let block_bytes = 210;
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let block_off = b * block_bytes;
        if block_off + block_bytes > data.len() { break; }
        let out_base_block = b * block_size;
        if out_base_block >= n_elements { break; }

        // Layout: ql[128 bytes] + qh[64 bytes] + scales[16 bytes] + d[2 bytes]
        let ql_all = &data[block_off..block_off + 128];
        let qh_all = &data[block_off + 128..block_off + 192];
        let scales = &data[block_off + 192..block_off + 208];
        let d_bits = u16::from_le_bytes([data[block_off + 208], data[block_off + 209]]);
        let d = f16_to_f32(d_bits);

        // Two 128-element halves
        for half in 0..2usize {
            let ql_off = half * 64;       // each half consumes 64 ql bytes
            let qh_off = half * 32;       // each half consumes 32 qh bytes
            let sc_off = half * 8;        // each half uses 8 of 16 scale entries
            let out_base = out_base_block + half * 128;

            for l in 0..32usize {
                let is = l / 16; // 0 for l<16, 1 for l>=16

                let ql_a = ql_all[ql_off + l] as i32;
                let ql_b = ql_all[ql_off + l + 32] as i32;
                let qh_byte = qh_all[qh_off + l] as i32;

                let q1 = ((ql_a & 0xF) | (((qh_byte >> 0) & 3) << 4)) - 32;
                let q2 = ((ql_b & 0xF) | (((qh_byte >> 2) & 3) << 4)) - 32;
                let q3 = ((ql_a >> 4)  | (((qh_byte >> 4) & 3) << 4)) - 32;
                let q4 = ((ql_b >> 4)  | (((qh_byte >> 6) & 3) << 4)) - 32;

                let sc0 = (scales[sc_off + is]     as i8) as f32;
                let sc1 = (scales[sc_off + is + 2] as i8) as f32;
                let sc2 = (scales[sc_off + is + 4] as i8) as f32;
                let sc3 = (scales[sc_off + is + 6] as i8) as f32;

                let i0 = out_base + l;
                let i1 = i0 + 32;
                let i2 = i0 + 64;
                let i3 = i0 + 96;

                if i0 < n_elements { out[i0] = d * sc0 * q1 as f32; }
                if i1 < n_elements { out[i1] = d * sc1 * q2 as f32; }
                if i2 < n_elements { out[i2] = d * sc2 * q3 as f32; }
                if i3 < n_elements { out[i3] = d * sc3 * q4 as f32; }
            }
        }
    }
    out
}

/// Q5_K: block_size=256, layout: ql[128] + qh[32] + scales[12] + d[2] + dmin[2] = 176 bytes
///
/// Mirrors llama.cpp `dequantize_row_q5_K` in `ggml-quants.c`.
/// 8 sub-blocks of 32 elements. Scales and mins are 6-bit packed in scales[12].
/// q5 = (ql_nibble) | (qh_bit << 4), value = d*scale*q5 - dmin*min
fn dequant_q5_k(data: &[u8], n_elements: usize) -> Vec<f32> {
    let block_size = 256;
    let block_bytes = 176;
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let off = b * block_bytes;
        if off + block_bytes > data.len() { break; }
        let out_base = b * block_size;
        if out_base >= n_elements { break; }

        // Layout: d[2] + dmin[2] + scales[12] + qh[32] + ql[128]
        let d    = f16_to_f32(u16::from_le_bytes([data[off],     data[off + 1]]));
        let dmin = f16_to_f32(u16::from_le_bytes([data[off + 2], data[off + 3]]));
        let sc   = &data[off + 4  .. off + 16];  // 12 bytes of packed 6-bit scales/mins
        let qh   = &data[off + 16 .. off + 48];  // 32 bytes high bits (1 bit per element)
        let ql   = &data[off + 48 .. off + 176]; // 128 bytes low nibbles (4 bits per element)

        // Extract 6-bit scale and min for each of 8 sub-blocks.
        // Packing: sc[0..5] hold scales[0..7] as 6-bit values (two per byte, lower then upper).
        //          sc[6..11] hold mins[0..7] the same way.
        // Actually llama.cpp uses a more complex interleaved packing — use the helper below.
        let (scales, mins) = unpack_q5k_scales(sc);

        for i in 0..256usize {
            let elem = out_base + i;
            if elem >= n_elements { break; }

            let sub = i / 32;
            let pos = i % 32;

            // Low 4 bits from ql
            let ql_byte = ql[i / 2];
            let ql_val = if i % 2 == 0 { ql_byte & 0x0F } else { (ql_byte >> 4) & 0x0F };

            // High bit from qh (1 bit per element, packed 8 per byte)
            let qh_byte = qh[pos / 8 + (sub / 4) * 4]; // stride by sub-block group
            // Simpler: qh is flat [32 bytes], element i → byte i/8, bit i%8
            let qh_byte2 = qh[i / 8];
            let qh_bit = (qh_byte2 >> (i % 8)) & 0x01;

            let q5 = (ql_val as i32) | ((qh_bit as i32) << 4);

            out[elem] = d * (scales[sub] as f32) * (q5 as f32)
                      - dmin * (mins[sub] as f32);
        }
    }
    out
}

/// Unpack Q5_K's 12-byte scale/min block into 8 scales and 8 mins.
/// llama.cpp packing: each value is 6 bits. Bytes 0-5 hold scales, bytes 6-11 hold mins,
/// but they're interleaved in 4-bit nibbles across the 12 bytes.
/// Exact layout from ggml-quants.c `get_scale_min_k4`:
///   if j < 4: scale = sc[j] & 63, min = sc[j+4] & 63
///   else:     scale = (sc[j+4] & 0xF) | ((sc[j-4] >> 6) << 4)
///             min   = (sc[j+4] >> 4)  | ((sc[j-0] >> 6) << 4)
fn unpack_q5k_scales(sc: &[u8]) -> ([u8; 8], [u8; 8]) {
    let mut scales = [0u8; 8];
    let mut mins   = [0u8; 8];
    for j in 0..8usize {
        if j < 4 {
            scales[j] = sc[j] & 63;
            mins[j]   = sc[j + 4] & 63;
        } else {
            scales[j] = (sc[j + 4] & 0x0F) | ((sc[j - 4] >> 6) << 4);
            mins[j]   = (sc[j + 4] >> 4)   | ((sc[j - 0] >> 6) << 4);
        }
    }
    (scales, mins)
}

/// Q5_K: simplified dequant — see full implementation above.
/// This stub is kept for the extract_6bit helper below.

/// IQ4_XS: block_size=256, layout: d[2] + scales_h[2] + scales_l[4] + qs[128] = 136 bytes
///
/// Mirrors llama.cpp `dequantize_row_iq4_xs` in `ggml-quants.c`.
/// 8 sub-blocks of 32 elements. Each sub-block has a 6-bit signed scale.
/// Quant indices are 4-bit, looked up in kvalues_iq4nl[16].
fn dequant_iq4_xs(data: &[u8], n_elements: usize) -> Vec<f32> {
    // IQ4_XS lookup table (same as iq4_nl)
    const KVALUES: [i32; 16] = [
        -127, -104, -83, -65, -49, -35, -22, -10,
           1,   13,  25,  38,  53,  69,  89, 113,
    ];

    let block_size = 256;
    let block_bytes = 136; // 2+2+4+128
    let n_blocks = (n_elements + block_size - 1) / block_size;
    let mut out = vec![0.0f32; n_elements];

    for b in 0..n_blocks {
        let off = b * block_bytes;
        if off + block_bytes > data.len() { break; }
        let out_base = b * block_size;
        if out_base >= n_elements { break; }

        // d: f16 at [0..1]
        let d = f16_to_f32(u16::from_le_bytes([data[off], data[off + 1]]));
        // scales_h: u16 at [2..3] — high 2 bits of each of 8 sub-block scales
        let scales_h = u16::from_le_bytes([data[off + 2], data[off + 3]]);
        // scales_l: [4..7] — low 4 bits of each of 8 sub-block scales, 2 per byte
        // qs: [8..135] — 4-bit quant indices, 2 per byte

        for i in 0..256usize {
            let elem = out_base + i;
            if elem >= n_elements { break; }

            let ib = i / 32; // sub-block index 0..7

            // Reconstruct 6-bit signed scale for this sub-block
            // Low 4 bits: nibble ib of scales_l (byte ib/2, nibble ib%2)
            let sl_byte = data[off + 4 + ib / 2];
            let scale_low = if ib % 2 == 0 { sl_byte & 0x0F } else { (sl_byte >> 4) & 0x0F };
            // High 2 bits: bits [2*ib .. 2*ib+1] of scales_h
            let scale_high = ((scales_h >> (ib * 2)) & 0x03) as u8;
            // Combine to 6-bit signed (subtract 32 to center)
            let scale_6bit = ((scale_high << 4) | scale_low) as i32 - 32;

            // 4-bit quant index
            let qs_byte = data[off + 8 + i / 2];
            let q_idx = if i % 2 == 0 { qs_byte & 0x0F } else { (qs_byte >> 4) & 0x0F } as usize;

            out[elem] = d * (scale_6bit as f32) * (KVALUES[q_idx] as f32);
        }
    }
    out
}

/// Extract a 6-bit value from a packed byte array at the given index.
fn extract_6bit(data: &[u8], idx: usize) -> u32 {
    let bit_offset = idx * 6;
    let byte_idx = bit_offset / 8;
    let bit_shift = bit_offset % 8;

    if byte_idx >= data.len() { return 0; }

    let mut val = (data[byte_idx] as u32) >> bit_shift;
    if bit_shift > 2 && byte_idx + 1 < data.len() {
        val |= (data[byte_idx + 1] as u32) << (8 - bit_shift);
    }
    val & 0x3F
}
