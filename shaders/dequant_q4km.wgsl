// WGSL Q4_K_M Dequantization Kernel for Tesla P100
// Converts Q4_K_M quantized blocks to F32 for matmul consumption.
//
// Q4_K_M super-block layout (144 bytes per 256 elements):
//   - d: f16 (2 bytes) — global scale
//   - dmin: f16 (2 bytes) — global minimum
//   - scales: 12 bytes — 8 sub-block scales + 8 sub-block mins packed
//   - qs: 128 bytes — 256 weights as 4-bit nibbles (2 per byte)
//
// Each super-block = 256 weights. Each sub-block = 32 weights.
// Workgroup: 256 threads process 1 super-block (1 thread per weight).

struct Params {
    total_blocks: u32,
    _pad0: u32,
    _pad1: u32,
    _pad2: u32,
}

@group(0) @binding(0) var<storage, read> quant_data: array<u32>;
@group(0) @binding(1) var<storage, read_write> output_f32: array<f32>;
@group(0) @binding(2) var<uniform> params: Params;

// Convert FP16 bit pattern to f32
fn fp16_to_f32(bits: u32) -> f32 {
    let sign = (bits >> 15u) & 1u;
    let exp = (bits >> 10u) & 0x1Fu;
    let mant = bits & 0x3FFu;

    var result: f32;
    if (exp == 0u) {
        // Subnormal or zero
        result = f32(mant) * 5.9604644775390625e-8;
    } else if (exp == 31u) {
        // Inf/NaN — clamp to large value
        result = 65504.0;
    } else {
        result = pow(2.0, f32(i32(exp) - 15)) * (1.0 + f32(mant) / 1024.0);
    }

    if (sign == 1u) {
        result = -result;
    }
    return result;
}

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    // Each thread dequantizes one weight element.
    // block_idx = which 256-element super-block
    // local_idx = position within the super-block [0..255]
    let global_elem = gid.x;
    let block_idx = global_elem / 256u;
    let local_idx = global_elem % 256u;

    if (block_idx >= params.total_blocks) {
        return;
    }

    // Q4_K_M block is 144 bytes = 36 u32s
    // Layout in u32 words:
    //   [0]: lower 16 bits = d (f16), upper 16 bits = dmin (f16)
    //   [1..3]: 12 bytes of scales (3 u32s)
    //   [4..35]: 128 bytes of nibble data (32 u32s)
    let block_base = block_idx * 36u;

    // Extract d and dmin
    let d_dmin_word = quant_data[block_base];
    let d = fp16_to_f32(d_dmin_word & 0xFFFFu);
    let dmin = fp16_to_f32((d_dmin_word >> 16u) & 0xFFFFu);

    // Determine sub-block index [0..7] and position within sub-block [0..31]
    let sub_block = local_idx / 32u;
    let sub_pos = local_idx % 32u;

    // Extract 6-bit scale and min for this sub-block from the 12-byte scales region.
    // The scales are packed as: first 8 scales (6-bit each) in bytes 0..5,
    // then 8 mins (6-bit each) in bytes 6..11.
    // Total: 48 bits for scales + 48 bits for mins = 96 bits = 12 bytes.
    let scales_base = block_base + 1u; // starts at word offset 1

    // Read the 12 bytes as 3 u32s
    let s0 = quant_data[scales_base];
    let s1 = quant_data[scales_base + 1u];
    let s2 = quant_data[scales_base + 2u];

    // Extract 6-bit scale for sub_block (bits [sub_block*6 .. sub_block*6+5] of first 48 bits)
    var sc: u32;
    let sc_bit_offset = sub_block * 6u;
    if (sc_bit_offset < 32u) {
        sc = (s0 >> sc_bit_offset) & 0x3Fu;
        // Handle crossing word boundary
        if (sc_bit_offset > 26u) {
            let overflow_bits = sc_bit_offset + 6u - 32u;
            sc = (sc | ((s1 & ((1u << overflow_bits) - 1u)) << (6u - overflow_bits))) & 0x3Fu;
        }
    } else {
        let adj_offset = sc_bit_offset - 32u;
        sc = (s1 >> adj_offset) & 0x3Fu;
        if (adj_offset > 26u) {
            let overflow_bits = adj_offset + 6u - 32u;
            sc = (sc | ((s2 & ((1u << overflow_bits) - 1u)) << (6u - overflow_bits))) & 0x3Fu;
        }
    }

    // Extract 6-bit min for sub_block (bits [sub_block*6 .. sub_block*6+5] of second 48 bits)
    var mn: u32;
    let mn_bit_offset = sub_block * 6u + 48u; // offset by 48 bits (the scales portion)
    let mn_word_offset = mn_bit_offset / 32u;
    let mn_local_bit = mn_bit_offset % 32u;

    if (mn_word_offset == 1u) {
        mn = (s1 >> mn_local_bit) & 0x3Fu;
        if (mn_local_bit > 26u) {
            let overflow_bits = mn_local_bit + 6u - 32u;
            mn = (mn | ((s2 & ((1u << overflow_bits) - 1u)) << (6u - overflow_bits))) & 0x3Fu;
        }
    } else {
        // mn_word_offset == 2
        mn = (s2 >> mn_local_bit) & 0x3Fu;
    }

    // Extract the 4-bit nibble for this element from the qs region
    // qs starts at word offset 4 (byte offset 16 within the block)
    let qs_base = block_base + 4u;
    let byte_idx = local_idx / 2u;  // which byte (0..127)
    let nibble_hi = local_idx & 1u; // 0 = low nibble, 1 = high nibble

    let word_idx = byte_idx / 4u;
    let byte_in_word = byte_idx % 4u;
    let qs_word = quant_data[qs_base + word_idx];
    let byte_val = (qs_word >> (byte_in_word * 8u)) & 0xFFu;

    var nibble: u32;
    if (nibble_hi == 0u) {
        nibble = byte_val & 0x0Fu;
    } else {
        nibble = (byte_val >> 4u) & 0x0Fu;
    }

    // Dequantize: weight = d * sc * nibble - dmin * mn
    let weight = d * f32(sc) * f32(nibble) - dmin * f32(mn);

    output_f32[global_elem] = weight;
}
