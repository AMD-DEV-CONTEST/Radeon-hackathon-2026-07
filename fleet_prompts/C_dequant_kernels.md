You are an expert in llama.cpp quantization formats and WGSL compute shaders. I need production-quality dequantization kernels for a Rust+wgpu inference engine targeting Tesla P100 via Vulkan.

## Context
Engine already has working Q6_K and Q4_K_M dequant (CPU Rust + WGSL GPU shader). Both follow llama.cpp's `ggml-quants.c` exactly. The Q6_K fix was critical — naive sequential indexing was wrong; the correct approach uses block-structured two-halves/inner-32 loops.

## Existing pattern (Q6_K CPU reference):
```rust
fn dequant_q6_k(data: &[u8], n_elements: usize) -> Vec<f32> {
    // 210 bytes per 256-element block: ql[128] + qh[64] + scales[16] + d[2]
    for b in 0..n_blocks {
        for half in 0..2usize {
            let ql_off = half * 64; let qh_off = half * 32; let sc_off = half * 8;
            for l in 0..32usize {
                let is = l / 16;
                let q1 = ((ql[ql_off+l] & 0xF) | (((qh[qh_off+l]>>0)&3)<<4)) as i32 - 32;
                let q2 = ((ql[ql_off+l+32] & 0xF) | (((qh[qh_off+l]>>2)&3)<<4)) as i32 - 32;
                let q3 = ((ql[ql_off+l]>>4) | (((qh[qh_off+l]>>4)&3)<<4)) as i32 - 32;
                let q4 = ((ql[ql_off+l+32]>>4) | (((qh[qh_off+l]>>6)&3)<<4)) as i32 - 32;
                let sc0 = (scales[sc_off+is] as i8) as f32;
                let sc1 = (scales[sc_off+is+2] as i8) as f32;
                let sc2 = (scales[sc_off+is+4] as i8) as f32;
                let sc3 = (scales[sc_off+is+6] as i8) as f32;
                out[out_base+l] = d * sc0 * q1 as f32;
                out[out_base+l+32] = d * sc1 * q2 as f32;
                out[out_base+l+64] = d * sc2 * q3 as f32;
                out[out_base+l+96] = d * sc3 * q4 as f32;
            }
        }
    }
}
```

## WGSL pattern (Q6_K GPU shader):
```wgsl
// 256 threads, one per output element
// read_byte(block_byte_offset, local_byte) -> u32 helper reads from array<u32>
// Derive (half, slot, l) from local_idx, read interleaved ql/qh/scale bytes
@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let block_idx = gid.x / 256u; let local_idx = gid.x % 256u;
    // ... block-structured decode ...
    output_f32[gid.x] = d * f32(scale_signed) * f32(q6);
}
```

## DELIVERABLES — provide all three for each quant type:

### 1. IQ4_XS (136 bytes per 256-element block)
Block layout:
```c
struct block_iq4_xs {
    ggml_half d;        // [0..1] f16 super-block scale
    uint16_t scales_h;  // [2..3] high 2 bits of each of 8 sub-block scales
    uint8_t scales_l[4];// [4..7] low 4 bits of each of 8 sub-block scales (2 per byte)
    uint8_t qs[128];    // [8..135] 4-bit quants, 2 per byte
};
// 8 sub-blocks of 32 elements each
// sub-block ib (0..7): scale_low = nibble ib of scales_l (ib/2 byte, ib%2 nibble)
//                      scale_high = bits [2*ib .. 2*ib+1] of scales_h
//                      scale_6bit = (scale_high << 4) | scale_low, then - 32 for signed
// quant index q = nibble of qs[i/2] (low if i even, high if i odd)
// value = d * scale_6bit * kvalues_iq4nl[q]
static const int8_t kvalues_iq4nl[16] = {
    -127, -104, -83, -65, -49, -35, -22, -10, 1, 13, 25, 38, 53, 69, 89, 113
};
```

### 2. Q5_K (176 bytes per 256-element block)
Block layout (from llama.cpp `ggml-quants.h`):
```c
struct block_q5_K {
    ggml_half d;         // [0..1] super-block scale
    ggml_half dmin;      // [2..3] super-block min
    uint8_t scales[12];  // [4..15] 6-bit scales + mins, packed
    uint8_t qh[32];      // [16..47] high bits (1 per element, 8 per byte)
    uint8_t qs[128];     // [48..175] low 4 bits (2 per byte)
};
// 8 sub-blocks of 32 elements
// Scale/min extraction: same 6-bit packed format as Q4_K
// q5 = (ql_nibble) | (qh_bit << 4), then value = d*scale*q5 - dmin*min
```

### 3. Q8_0 (34 bytes per 32-element block — simplest)
Block layout:
```c
struct block_q8_0 {
    ggml_half d;    // [0..1] scale
    int8_t qs[32];  // [2..33] signed 8-bit quants
};
// value = d * qs[i]
```

## For each quant type provide:

**(a) Rust CPU function** — exact same signature pattern:
```rust
fn dequant_iq4_xs(data: &[u8], n_elements: usize) -> Vec<f32> { ... }
fn dequant_q5_k(data: &[u8], n_elements: usize) -> Vec<f32> { ... }
fn dequant_q8_0(data: &[u8], n_elements: usize) -> Vec<f32> { ... }
```
`f16_to_f32(u16) -> f32` is already in scope (manual bit manipulation, no crate needed).

**(b) WGSL shader** — exact binding layout:
```wgsl
struct Params { total_blocks: u32, _pad0: u32, _pad1: u32, _pad2: u32 }
@group(0) @binding(0) var<storage, read> raw_data: array<u32>;
@group(0) @binding(1) var<storage, read_write> output_f32: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;
fn read_byte(block_byte_offset: u32, local_byte: u32) -> u32 { ... }
@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) { ... }
```

**(c) Discriminating probe** — a synthetic block where every output element is unique (different ql/qh/scale bytes per position), plus the expected CPU output. This catches indexing bugs that uniform-byte probes miss.

## ALSO: compute_tensor_size additions
Add these cases to the existing match in `loader.rs::compute_tensor_size`:
```rust
fn compute_tensor_size(shape: &[usize], quant_type: u32) -> usize {
    let n = shape.iter().product::<usize>();
    match quant_type {
        // existing...
        17 => (n + 255) / 256 * 136,  // IQ4_XS
        13 => (n + 255) / 256 * 176,  // Q5_K
        8  => (n + 31) / 32 * 34,     // Q8_0 (already exists but verify)
        // ...
    }
}
```
Verify the byte counts: IQ4_XS=136, Q5_K=176, Q8_0=34. Show your math.

## OUTPUT FORMAT
```
// === IQ4_XS ===
// Rust CPU: fn dequant_iq4_xs ...
// WGSL: shaders/dequant_iq4xs.wgsl ...
// Probe: ...

// === Q5_K ===
// ...

// === Q8_0 ===
// ...

// === compute_tensor_size additions ===
// ...

// === NOTES ===
// - gotchas per quant type
// - byte count verification
```

Be precise. No placeholders. Working code only.
