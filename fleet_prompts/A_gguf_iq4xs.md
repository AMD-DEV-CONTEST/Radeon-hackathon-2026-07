You are an expert in GGUF file format and llama.cpp's quantization kernels. I am writing a pure-Rust + wgpu/WGSL inference engine and I need two deliverables.

## Context
- Engine already loads Qwen2.5-Coder-1.5B Q6_K and produces coherent output ("2+2 equals 4.").
- Existing per-quant CPU dequant lives in `src/tensor_loader_safe.rs` and matching WGSL lives in `shaders/dequant_q*.wgsl`.
- We have working Q4_K_M and Q6_K. We need IQ4_XS to run Gemma-4-26B-MoE-IQ4_XS.gguf.
- We use the `half` crate (f16) and read raw bytes with `bytemuck`.
- I have read llama.cpp's `ggml-quants.c` for Q6_K and want the same fidelity for IQ4_XS.

## Deliverable 1: GGUF arch auto-detection
Write a Rust function:
```
pub struct ArchInfo {
    pub family: ModelFamily,         // existing enum: Qwen2_5, Gemma4, Llama3, Phi3, DeepSeekV2
    pub is_moe: bool,
    pub n_experts: u32,
    pub n_experts_used: u32,
    pub sliding_window: Option<u32>,
    pub rope_theta: f32,
    pub rope_partial_dim: Option<u32>,
    pub head_dim: u32,
    pub n_heads: u32,
    pub n_kv_heads: u32,
    pub hidden_dim: u32,
    pub ffn_dim: u32,
    pub n_layers: u32,
    pub vocab_size: u32,
    pub has_qkv_bias: bool,
}

pub fn detect_arch(metadata: &HashMap<String, GgufValue>, tensor_names: &[String]) -> ArchInfo;
```
Map these GGUF keys (read llama.cpp gguf.h if needed):
- general.architecture (qwen2, qwen2moe, qwen3moe, gemma, gemma2, gemma3, llama, deepseek2)
- {arch}.expert_count, {arch}.expert_used_count
- {arch}.attention.sliding_window (Gemma)
- {arch}.rope.freq_base, {arch}.rope.scaling.factor, {arch}.rope.dimension_count
- {arch}.embedding_length, {arch}.feed_forward_length, {arch}.block_count
- {arch}.attention.head_count, {arch}.attention.head_count_kv
- has_qkv_bias: True if any tensor name ends in `attn_q.bias`

Code must compile against:
```
#[derive(Debug, Clone)]
pub enum GgufValue { U32(u32), I32(i32), F32(f32), Bool(bool), String(String), Array(Vec<GgufValue>), U64(u64), I64(i64) }
```

## Deliverable 2: IQ4_XS dequantizer
Reference llama.cpp's `dequantize_row_iq4_xs` in `ggml-quants.c`.

Block layout for IQ4_XS (256 elements per super-block, 136 bytes):
```
struct block_iq4_xs {
    ggml_half d;          // 2 bytes f16 super-block scale
    uint16_t scales_h;    // 2 bytes high bits of 8 sub-block scales
    uint8_t scales_l[4];  // 4 bytes low bits, 4 bits per scale, 8 scales
    uint8_t qs[128];      // 128 bytes, 4-bit quants
};
```
The 4-bit quants index a 16-entry signed lookup table:
```
static const int8_t kvalues_iq4nl[16] = {
    -127, -104, -83, -65, -49, -35, -22, -10,
    1, 13, 25, 38, 53, 69, 89, 113,
};
```

Reconstruction per element i in 0..256:
- sub-block index ib = i / 32 (8 sub-blocks of 32)
- sub-block scale 6-bit signed: low 4 bits from scales_l[ib/2] nibble, high 2 bits from scales_h shifted, then sub 32
- quant index q = lookup nibble from qs[i/2] (low if i even, high if i odd)
- value = d * sub_scale * kvalues_iq4nl[q]

Provide:

(a) **Rust CPU function** following the same shape as our Q6_K reference — block-structured, no naive sequential. Place in tensor_loader_safe.rs:
```rust
fn dequant_iq4_xs(data: &[u8], n_elements: usize) -> Vec<f32> { ... }
```
where f16_to_f32 is already in scope.

(b) **WGSL shader** `dequant_iq4xs.wgsl` matching this binding layout:
```
struct Params { total_blocks: u32, _pad0: u32, _pad1: u32, _pad2: u32 }
@group(0) @binding(0) var<storage, read> raw_data: array<u32>;
@group(0) @binding(1) var<storage, read_write> output_f32: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;
@compute @workgroup_size(256, 1, 1) fn main(@builtin(global_invocation_id) gid: vec3<u32>) { ... }
```
Use a `read_byte(block_byte_offset, local_byte) -> u32` helper like our Q6_K shader. Encode kvalues_iq4nl as a constant array. Block size is 136 bytes.

(c) **Discriminating probe pattern** — distinct values at every position so a wrong indexing strategy fails visibly.

OUTPUT FORMAT:
```rust
// === FILE: src/arch_detect.rs ===
... full file ...

// === FILE: src/tensor_loader_safe.rs (add these functions) ===
... ...

// === FILE: shaders/dequant_iq4xs.wgsl ===
... full file ...

// === NOTES ===
- key gotchas
- byte counts / size verification
```
Be precise about byte offsets. Verify your math: 2 + 2 + 4 + 128 = 136 bytes.
