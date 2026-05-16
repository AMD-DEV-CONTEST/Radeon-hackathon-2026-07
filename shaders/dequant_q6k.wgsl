// WGSL Q6_K Dequantization — block-structured indexing matching llama.cpp.
//
// Q6_K super-block: 210 bytes = 256 elements
// Byte layout (GGUF native order):
//   [0..127]   ql: 128 bytes — lower 4 bits per element (interleaved)
//   [128..191] qh: 64 bytes — upper 2 bits per element (interleaved)
//   [192..207] scales: 16 bytes — 16 signed i8 sub-block scales
//   [208..209] d: 2 bytes — f16 super-block scale
//
// llama.cpp processes each block as two 128-element halves. Within each half
// l = 0..32 produces 4 outputs at relative positions l, l+32, l+64, l+96 from
// interleaved ql/qh nibbles + four interleaved sub-block scales.

struct Params {
    total_blocks: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

@group(0) @binding(0) var<storage, read> raw_data: array<u32>;
@group(0) @binding(1) var<storage, read_write> output_f32: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;

fn fp16_to_f32(bits: u32) -> f32 {
    let s = (bits >> 15u) & 0x1u;
    let e = (bits >> 10u) & 0x1fu;
    let m = bits & 0x3ffu;
    if (e == 0u) {
        if (m == 0u) { return 0.0; }
        return select(-1.0, 1.0, s == 0u) * f32(m) * 5.96046447e-8;
    }
    if (e == 31u) { return select(-1.0, 1.0, s == 0u) * 65504.0; }
    return select(-1.0, 1.0, s == 0u) * pow(2.0, f32(e) - 15.0) * (1.0 + f32(m) / 1024.0);
}

// Read a single byte from the raw u32 array at a given byte offset within a block
fn read_byte(block_byte_offset: u32, local_byte: u32) -> u32 {
    let abs_byte = block_byte_offset + local_byte;
    let word_idx = abs_byte / 4u;
    let byte_in_word = abs_byte % 4u;
    return (raw_data[word_idx] >> (byte_in_word * 8u)) & 0xFFu;
}

fn signed_byte(b: u32) -> i32 {
    return i32(b) - select(0, 256, b >= 128u);
}

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let global_elem = gid.x;
    let block_idx = global_elem / 256u;
    let local_idx = global_elem % 256u;

    if (block_idx >= params.total_blocks) { return; }

    let block_byte_offset = block_idx * 210u;

    // Global f16 scale (bytes 208-209)
    let d_lo = read_byte(block_byte_offset, 208u);
    let d_hi = read_byte(block_byte_offset, 209u);
    let d = fp16_to_f32(d_lo | (d_hi << 8u));

    // Block-structured decode: figure out which (half, l, slot) this element is.
    // Within a half (128 elems): slot = local/32 (0..3), l = local%32.
    let half = local_idx / 128u;             // 0 or 1
    let in_half = local_idx % 128u;          // 0..127
    let slot = in_half / 32u;                // 0,1,2,3
    let l = in_half % 32u;                   // 0..31

    let ql_off = half * 64u;
    let qh_off = 128u + half * 32u;
    let sc_off = 192u + half * 8u;

    // Each `l` reads ql[ql_off + l], ql[ql_off + l + 32], qh[qh_off + l]
    let ql_a = read_byte(block_byte_offset, ql_off + l);
    let ql_b = read_byte(block_byte_offset, ql_off + l + 32u);
    let qh_b = read_byte(block_byte_offset, qh_off + l);

    // 4 candidate quants
    // q1: ql_a low  | qh bits 0..1, output position l       (slot 0)
    // q2: ql_b low  | qh bits 2..3, output position l+32    (slot 1)
    // q3: ql_a high | qh bits 4..5, output position l+64    (slot 2)
    // q4: ql_b high | qh bits 6..7, output position l+96    (slot 3)
    var q_low: u32;
    var qh_shift: u32;
    if (slot == 0u) {
        q_low = ql_a & 0xFu;
        qh_shift = 0u;
    } else if (slot == 1u) {
        q_low = ql_b & 0xFu;
        qh_shift = 2u;
    } else if (slot == 2u) {
        q_low = (ql_a >> 4u) & 0xFu;
        qh_shift = 4u;
    } else {
        q_low = (ql_b >> 4u) & 0xFu;
        qh_shift = 6u;
    }
    let qh_bits = (qh_b >> qh_shift) & 0x3u;
    let q6 = i32(q_low | (qh_bits << 4u)) - 32;

    // Sub-block scale: is = l/16; per-slot offsets are 0,2,4,6 within the half.
    let is = l / 16u;
    let scale_byte = read_byte(block_byte_offset, sc_off + is + slot * 2u);
    let scale_signed = signed_byte(scale_byte);

    output_f32[global_elem] = d * f32(scale_signed) * f32(q6);
}
