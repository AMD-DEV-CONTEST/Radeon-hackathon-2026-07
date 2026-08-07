//! GGUF Model Loader — memory-maps model weights from RAID into GridBuffers.
//!
//! Uses memmap2 for zero-copy file access. Parses GGUF v3 header format.
//! Shards MoE experts across GPUs based on IronProfile.

use std::collections::HashMap;
use std::fs::File;
use std::io::{self, Read, Seek, SeekFrom};
use std::path::{Path, PathBuf};
use memmap2::Mmap;
use tracing::info;

use crate::hardware::IronProfile;

/// GGUF magic number ("GGUF" as little-endian u32: 0x46554747)
const GGUF_MAGIC: u32 = 0x46554747;

/// Metadata about a single tensor in the GGUF file.
#[derive(Debug, Clone)]
pub struct TensorMeta {
    pub name: String,
    pub shape: Vec<usize>,
    pub offset: u64,
    pub size: usize,
    pub quant_type: u32,
    pub n_dims: u32,
}

/// All model weights loaded as memory-mapped regions.
#[derive(Debug)]
pub struct ModelWeights {
    pub tensors: HashMap<String, TensorRegion>,
    pub n_layers: usize,
    pub n_experts: usize,
    pub hidden_dim: usize,
    pub n_heads: usize,
    pub n_kv_heads: usize,
    pub vocab_size: usize,
    pub data_offset: usize,
    /// Full GGUF metadata table — used by arch_detect for family/MoE/RoPE detection.
    pub metadata: HashMap<String, GgufValue>,
    /// All tensor names, in load order. Useful for quick checks like "any name ends in attn_q.bias".
    pub tensor_names: Vec<String>,
    _mmap: Mmap, // Keep mmap alive
}

/// A region of the memory-mapped file representing one tensor.
#[derive(Debug, Clone)]
pub struct TensorRegion {
    pub offset: usize,
    pub size: usize,
    pub shape: Vec<usize>,
    pub quant_type: u32,
}

/// GGUF metadata value types — exposed publicly so arch_detect can walk them.
#[derive(Debug, Clone)]
pub enum GgufValue {
    U32(u32),
    I32(i32),
    F32(f32),
    Str(String),
    U64(u64),
    Bool(bool),
    Array(Vec<GgufValue>),
    Other,
}

/// Load a GGUF model file via mmap.
pub fn load(path: &Path, _profile: &IronProfile) -> Result<ModelWeights, io::Error> {
    let file = File::open(path)?;
    let mmap = unsafe { Mmap::map(&file)? };

    info!("Loading GGUF from {} ({:.2} GB)", path.display(), mmap.len() as f64 / 1e9);

    let mut cursor = 0usize;

    // Parse header
    let magic = read_u32(&mmap, &mut cursor);
    if magic != GGUF_MAGIC {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "Not a GGUF file"));
    }

    let version = read_u32(&mmap, &mut cursor);
    if version < 2 || version > 3 {
        return Err(io::Error::new(io::ErrorKind::InvalidData,
            format!("Unsupported GGUF version: {}", version)));
    }

    let n_tensors = read_u64(&mmap, &mut cursor) as usize;
    let n_metadata = read_u64(&mmap, &mut cursor) as usize;

    info!("GGUF v{}: {} tensors, {} metadata entries", version, n_tensors, n_metadata);

    // Parse metadata key-value pairs
    let mut metadata: HashMap<String, GgufValue> = HashMap::new();
    for _ in 0..n_metadata {
        let key = read_gguf_string(&mmap, &mut cursor);
        let value = read_gguf_value(&mmap, &mut cursor);
        metadata.insert(key, value);
    }

    // Extract model dimensions from metadata
    let n_layers = get_u32_meta(&metadata, "llama.block_count")
        .or_else(|| get_u32_meta(&metadata, "qwen2.block_count"))
        .unwrap_or(48) as usize;
    let hidden_dim = get_u32_meta(&metadata, "llama.embedding_length")
        .or_else(|| get_u32_meta(&metadata, "qwen2.embedding_length"))
        .unwrap_or(5120) as usize;
    let n_heads = get_u32_meta(&metadata, "llama.attention.head_count")
        .or_else(|| get_u32_meta(&metadata, "qwen2.attention.head_count"))
        .unwrap_or(40) as usize;
    let n_kv_heads = get_u32_meta(&metadata, "llama.attention.head_count_kv")
        .or_else(|| get_u32_meta(&metadata, "qwen2.attention.head_count_kv"))
        .unwrap_or(8) as usize;
    let vocab_size = get_u32_meta(&metadata, "llama.vocab_size")
        .or_else(|| get_u32_meta(&metadata, "qwen2.vocab_size"))
        .unwrap_or(152064) as usize;
    let n_experts = get_u32_meta(&metadata, "llama.expert_count")
        .or_else(|| get_u32_meta(&metadata, "qwen2.expert_count"))
        .unwrap_or(0) as usize;

    info!("Model: {} layers, {} hidden, {} heads, {} kv_heads, {} vocab, {} experts",
        n_layers, hidden_dim, n_heads, n_kv_heads, vocab_size, n_experts);

    // Parse tensor info
    let mut tensors: HashMap<String, TensorRegion> = HashMap::new();
    let mut tensor_names: Vec<String> = Vec::with_capacity(n_tensors);
    for _ in 0..n_tensors {
        let name = read_gguf_string(&mmap, &mut cursor);
        let n_dims = read_u32(&mmap, &mut cursor);
        let mut shape = Vec::with_capacity(n_dims as usize);
        for _ in 0..n_dims {
            shape.push(read_u64(&mmap, &mut cursor) as usize);
        }
        let quant_type = read_u32(&mmap, &mut cursor);
        let offset = read_u64(&mmap, &mut cursor) as usize;

        let size = compute_tensor_size(&shape, quant_type);

        tensor_names.push(name.clone());
        tensors.insert(name, TensorRegion {
            offset,
            size,
            shape,
            quant_type,
        });
    }

    info!("Parsed {} tensor regions", tensors.len());

    // Data section starts after all tensor info, aligned to 32 bytes
    let data_offset = (cursor + 31) & !31;
    info!("Data section offset: {} (cursor was at {})", data_offset, cursor);

    Ok(ModelWeights {
        tensors,
        n_layers,
        n_experts,
        hidden_dim,
        n_heads,
        n_kv_heads,
        vocab_size,
        data_offset,
        metadata,
        tensor_names,
        _mmap: mmap,
    })
}

/// Get the raw bytes for a tensor from the mmap.
impl ModelWeights {
    pub fn tensor_bytes(&self, name: &str) -> Option<&[u8]> {
        let region = self.tensors.get(name)?;
        let start = self.data_offset + region.offset;
        let end = start + region.size;
        if end <= self._mmap.len() {
            Some(&self._mmap[start..end])
        } else {
            tracing::warn!("Tensor {} out of bounds: start={}, end={}, mmap_len={}", 
                name, start, end, self._mmap.len());
            None
        }
    }
}

// --- GGUF parsing helpers ---

fn read_u32(data: &[u8], cursor: &mut usize) -> u32 {
    let val = u32::from_le_bytes(data[*cursor..*cursor + 4].try_into().unwrap());
    *cursor += 4;
    val
}

fn read_u64(data: &[u8], cursor: &mut usize) -> u64 {
    let val = u64::from_le_bytes(data[*cursor..*cursor + 8].try_into().unwrap());
    *cursor += 8;
    val
}

fn read_i32(data: &[u8], cursor: &mut usize) -> i32 {
    let val = i32::from_le_bytes(data[*cursor..*cursor + 4].try_into().unwrap());
    *cursor += 4;
    val
}

fn read_f32(data: &[u8], cursor: &mut usize) -> f32 {
    let val = f32::from_le_bytes(data[*cursor..*cursor + 4].try_into().unwrap());
    *cursor += 4;
    val
}

fn read_gguf_string(data: &[u8], cursor: &mut usize) -> String {
    let len = read_u64(data, cursor) as usize;
    let s = String::from_utf8_lossy(&data[*cursor..*cursor + len]).to_string();
    *cursor += len;
    s
}

fn read_gguf_value(data: &[u8], cursor: &mut usize) -> GgufValue {
    let value_type = read_u32(data, cursor);
    match value_type {
        0 => GgufValue::U32(read_u32(data, cursor)),       // UINT32
        1 => GgufValue::I32(read_i32(data, cursor)),       // INT32
        2 => GgufValue::F32(read_f32(data, cursor)),       // FLOAT32
        4 => GgufValue::U32(read_u32(data, cursor)),       // UINT16 (read as u32)
        5 => GgufValue::I32(read_i32(data, cursor)),       // INT16
        6 => GgufValue::F32(read_f32(data, cursor)),       // FLOAT64 (lossy)
        7 => GgufValue::Bool({                              // BOOL
            let v = data[*cursor];
            *cursor += 1;
            v != 0
        }),
        8 => GgufValue::Str(read_gguf_string(data, cursor)), // STRING
        9 => {                                              // ARRAY
            let arr_type = read_u32(data, cursor);
            let arr_len = read_u64(data, cursor) as usize;
            let mut arr = Vec::with_capacity(arr_len);
            for _ in 0..arr_len {
                // Simplified: skip array contents for now
                arr.push(GgufValue::Other);
            }
            // Skip the actual array data based on type
            let elem_size = match arr_type {
                0 | 4 => 4, // u32, u16
                1 | 5 => 4, // i32, i16
                2 | 6 => 4, // f32, f64
                7 => 1,     // bool
                8 => {
                    // String array - need to read each
                    for _ in 0..arr_len {
                        let _ = read_gguf_string(data, cursor);
                    }
                    return GgufValue::Array(arr);
                }
                10 => 8, // u64
                _ => 4,
            };
            *cursor += arr_len * elem_size;
            GgufValue::Array(arr)
        },
        10 => GgufValue::U64(read_u64(data, cursor)),      // UINT64
        _ => {
            // Unknown type - skip 8 bytes as best guess
            *cursor += 8;
            GgufValue::Other
        }
    }
}

fn get_u32_meta(metadata: &HashMap<String, GgufValue>, key: &str) -> Option<u32> {
    match metadata.get(key) {
        Some(GgufValue::U32(v)) => Some(*v),
        Some(GgufValue::I32(v)) => Some(*v as u32),
        _ => None,
    }
}

/// Compute tensor size in bytes based on shape and quantization type.
fn compute_tensor_size(shape: &[usize], quant_type: u32) -> usize {
    let n_elements: usize = shape.iter().product();
    match quant_type {
        0  => n_elements * 4,                          // F32
        1  => n_elements * 2,                          // F16
        2  => (n_elements + 31) / 32 * 18,             // Q4_0
        3  => (n_elements + 31) / 32 * 20,             // Q4_1
        6  => (n_elements + 31) / 32 * 34,             // Q5_0
        7  => (n_elements + 31) / 32 * 36,             // Q5_1
        8  => (n_elements + 31) / 32 * 34,             // Q8_0: 2(f16) + 32(i8)
        12 => (n_elements + 255) / 256 * 176,          // Q4_K
        13 => (n_elements + 255) / 256 * 176,          // Q5_K: 2+2+12+32+128
        14 => (n_elements + 255) / 256 * 210,          // Q6_K
        17 => (n_elements + 255) / 256 * 136,          // IQ4_XS: 2+2+4+128
        28 => n_elements * 2,                          // BF16
        30 => n_elements * 2,                          // F16 alt
        _  => n_elements * 2,                          // Unknown: conservative 2 bytes
    }
}
