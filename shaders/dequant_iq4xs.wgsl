// WGSL IQ4_XS Dequantization — block-structured, matches llama.cpp dequantize_row_iq4_xs.
//
// IQ4_XS super-block: 136 bytes = 256 elements
// Layout:
//   [0..1]   d:        f16 super-block scale
//   [2..3]   scales_h: u16 — high 2 bits of each of 8 sub-block scales
//   [4..7]   scales_l: 4 bytes — low 4 bits of each of 8 sub-block scales (2 per byte)
//   [8..135] qs:       128 bytes — 4-bit quant indices (2 per byte)
//
// Sub-block scale reconstruction (6-bit signed, centered at 32):
//   scale_low  = nibble ib of scales_l (byte ib/2, nibble ib%2)
//   scale_high = bits [2*ib .. 2*ib+1] of scales_h
//   scale_6bit = (scale_high << 4) | scale_low  — then subtract 32
//
// Quant index → value via kvalues_iq4nl[16] lookup table.

struct Params {
    total_blocks: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

@group(0) @binding(0) var<storage, read>       raw_data:   array<u32>;
@group(0) @binding(1) var<storage, read_write> output_f32: array<f32>;
@group(0) @binding(2) var<uniform>             params:     Params;

// IQ4_XS / IQ4_NL lookup table (signed i8 values as f32)
const kvalues: array<f32, 16> = array<f32, 16>(
    -127.0, -104.0, -83.0, -65.0, -49.0, -35.0, -22.0, -10.0,
       1.0,   13.0,  25.0,  38.0,  53.0,  69.0,  89.0, 113.0
);

fn fp16_to_f32(bits: u32) -> f32 {
    let s = (bits >> 15u) & 0x1u;
    let e = (bits >> 10u) & 0x1fu;
    let m =  bits         & 0x3ffu;
    if (e == 0u) {
        if (m == 0u) { return 0.0; }
        return select(-1.0, 1.0, s == 0u) * f32(m) * 5.96046447e-8;
    }
    if (e == 31u) { return select(-1.0, 1.0, s == 0u) * 65504.0; }
    return select(-1.0, 1.0, s == 0u) * pow(2.0, f32(e) - 15.0) * (1.0 + f32(m) / 1024.0);
}

fn read_byte(block_byte_offset: u32, local_byte: u32) -> u32 {
    let abs_byte  = block_byte_offset + local_byte;
    let word_idx  = abs_byte / 4u;
    let byte_pos  = abs_byte % 4u;
    return (raw_data[word_idx] >> (byte_pos * 8u)) & 0xFFu;
}

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let global_elem = gid.x;
    let block_idx   = global_elem / 256u;
    let local_idx   = global_elem % 256u;

    if (block_idx >= params.total_blocks) { return; }

    let boff = block_idx * 136u;

    // Global f16 scale
    let d_lo = read_byte(boff, 0u);
    let d_hi = read_byte(boff, 1u);
    let d    = fp16_to_f32(d_lo | (d_hi << 8u));

    // Sub-block index (0..7)
    let ib = local_idx / 32u;

    // scales_h: u16 at bytes 2-3
    let sh_lo = read_byte(boff, 2u);
    let sh_hi = read_byte(boff, 3u);
    let scales_h = sh_lo | (sh_hi << 8u);

    // Low 4 bits of scale: nibble ib of scales_l (bytes 4-7)
    let sl_byte   = read_byte(boff, 4u + ib / 2u);
    let scale_low = select((sl_byte >> 4u) & 0x0Fu, sl_byte & 0x0Fu, ib % 2u == 0u);

    // High 2 bits of scale: bits [2*ib .. 2*ib+1] of scales_h
    let scale_high = (scales_h >> (ib * 2u)) & 0x03u;

    // 6-bit signed scale (subtract 32 to center)
    let scale_6bit = i32(scale_high << 4u | scale_low) - 32;

    // 4-bit quant index from qs (bytes 8-135)
    let qs_byte = read_byte(boff, 8u + local_idx / 2u);
    let q_idx   = select((qs_byte >> 4u) & 0x0Fu, qs_byte & 0x0Fu, local_idx % 2u == 0u);

    output_f32[global_elem] = d * f32(scale_6bit) * kvalues[q_idx];
}
