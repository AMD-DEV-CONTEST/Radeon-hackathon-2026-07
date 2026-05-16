//! Dynamic dequantization probe — validates shader bit-layout against a
//! llama.cpp-faithful CPU reference using a *discriminating* synthetic block.
//!
//! The previous probe filled ql/qh with all-equal bytes, which made every
//! output element identical regardless of indexing strategy. That allowed an
//! incorrect block-structure decode to silently pass. This version fills ql,
//! qh, and the sub-block scales with position-dependent values so each of the
//! 256 outputs is unique. We then compare GPU output against a CPU reference
//! that mirrors `dequantize_row_q6_K` from llama.cpp's `ggml-quants.c`.

use crate::shader_ops::DequantQ6KPipeline;
use tracing::{info, warn, error};

/// Result of the dequant probe.
#[derive(Debug)]
pub struct ProbeResult {
    pub passed: bool,
    pub expected: Vec<f32>,
    pub actual: Vec<f32>,
    pub max_error: f32,
}

fn f16_to_f32(bits: u16) -> f32 {
    half::f16::from_bits(bits).to_f32()
}

/// CPU reference matching llama.cpp's `dequantize_row_q6_K`.
fn cpu_dequant_q6_k(block: &[u8]) -> Vec<f32> {
    let mut out = vec![0.0f32; 256];
    let ql = &block[0..128];
    let qh = &block[128..192];
    let scales = &block[192..208];
    let d = f16_to_f32(u16::from_le_bytes([block[208], block[209]]));

    for half in 0..2usize {
        let ql_off = half * 64;
        let qh_off = half * 32;
        let sc_off = half * 8;
        let out_base = half * 128;

        for l in 0..32usize {
            let is = l / 16;
            let ql_a = ql[ql_off + l] as i32;
            let ql_b = ql[ql_off + l + 32] as i32;
            let qh_byte = qh[qh_off + l] as i32;

            let q1 = ((ql_a & 0xF) | (((qh_byte >> 0) & 3) << 4)) - 32;
            let q2 = ((ql_b & 0xF) | (((qh_byte >> 2) & 3) << 4)) - 32;
            let q3 = ((ql_a >> 4)  | (((qh_byte >> 4) & 3) << 4)) - 32;
            let q4 = ((ql_b >> 4)  | (((qh_byte >> 6) & 3) << 4)) - 32;

            let sc0 = (scales[sc_off + is]     as i8) as f32;
            let sc1 = (scales[sc_off + is + 2] as i8) as f32;
            let sc2 = (scales[sc_off + is + 4] as i8) as f32;
            let sc3 = (scales[sc_off + is + 6] as i8) as f32;

            out[out_base + l]      = d * sc0 * q1 as f32;
            out[out_base + l + 32] = d * sc1 * q2 as f32;
            out[out_base + l + 64] = d * sc2 * q3 as f32;
            out[out_base + l + 96] = d * sc3 * q4 as f32;
        }
    }
    out
}

/// Run the Q6_K dequant probe to validate shader correctness.
///
/// Builds a synthetic block where every ql byte, qh byte, and scale byte has
/// a distinct value so a wrong indexing strategy will produce visibly wrong
/// outputs at specific positions.
pub fn run_dequant_probe(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    dequant_pipeline: &DequantQ6KPipeline,
) -> ProbeResult {
    info!("Running Q6_K dequant probe (discriminating pattern)...");

    // 210-byte block, padded to 4-byte alignment.
    let mut probe_bytes = vec![0u8; 212];

    // ql[0..128]: byte i = (i & 0x7F) so high bit ignored — gives distinct nibbles per position.
    // Use a mix that exercises both low and high nibbles.
    for i in 0..128 {
        // Pick something where low nibble != high nibble != neighbors
        let low = (i as u8) & 0x0F;
        let high = ((i as u8).wrapping_mul(3) & 0x0F) ^ 0x05;
        probe_bytes[i] = (high << 4) | low;
    }

    // qh[128..192]: distinct per byte; each byte holds 4 crumbs (2 bits) for 4 outputs.
    for i in 0..64 {
        // 4 distinct 2-bit values packed
        let c0 = ((i + 0) as u8) & 0x03;
        let c1 = ((i + 1) as u8) & 0x03;
        let c2 = ((i + 2) as u8) & 0x03;
        let c3 = ((i + 3) as u8) & 0x03;
        probe_bytes[128 + i] = c0 | (c1 << 2) | (c2 << 4) | (c3 << 6);
    }

    // scales[192..208]: 16 distinct signed values spanning negative & positive.
    let scale_pattern: [i8; 16] = [
        1, -2, 3, -4, 5, -6, 7, -8,
        9, -10, 11, -12, 13, -14, 15, -16,
    ];
    for i in 0..16 {
        probe_bytes[192 + i] = scale_pattern[i] as u8;
    }

    // d = 1.0 (f16 = 0x3C00)
    probe_bytes[208] = 0x00;
    probe_bytes[209] = 0x3C;

    // Compute CPU reference
    let expected = cpu_dequant_q6_k(&probe_bytes[..210]);

    // Upload to GPU
    let input_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("probe_input"),
        size: 212,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_DST,
        mapped_at_creation: false,
    });
    queue.write_buffer(&input_buf, 0, &probe_bytes);

    let output_buf = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("probe_output"),
        size: 256 * 4,
        usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC,
        mapped_at_creation: false,
    });

    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor {
        label: Some("probe_encoder"),
    });
    dequant_pipeline.dispatch(device, queue, &mut encoder, &input_buf, &output_buf, 256);

    let staging = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("probe_staging"),
        size: 256 * 4,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
        mapped_at_creation: false,
    });
    encoder.copy_buffer_to_buffer(&output_buf, 0, &staging, 0, 256 * 4);
    queue.submit(std::iter::once(encoder.finish()));

    let slice = staging.slice(..);
    let (tx, rx) = std::sync::mpsc::channel();
    slice.map_async(wgpu::MapMode::Read, move |r| { let _ = tx.send(r); });
    loop {
        device.poll(wgpu::Maintain::Poll);
        if rx.try_recv().is_ok() { break; }
        std::thread::sleep(std::time::Duration::from_micros(10));
    }
    let data = slice.get_mapped_range();
    let actual: Vec<f32> = bytemuck::cast_slice(&data).to_vec();
    drop(data);
    staging.unmap();

    // Verify: every position must match
    let mut max_error = 0.0f32;
    let mut first_mismatch: Option<usize> = None;
    for i in 0..256 {
        let e = (actual[i] - expected[i]).abs();
        if e > max_error { max_error = e; }
        if e > 0.001 && first_mismatch.is_none() {
            first_mismatch = Some(i);
        }
    }

    let passed = max_error < 0.01;

    if passed {
        info!("✓ Dequant probe PASSED — GPU matches llama.cpp CPU reference (max_err={:.6})", max_error);
    } else {
        error!("✗ Dequant probe FAILED — max error: {:.4}", max_error);
        if let Some(idx) = first_mismatch {
            info!("  First mismatch at index {}: expected={} actual={}",
                idx, expected[idx], actual[idx]);
        }
        info!("  Expected[0..8]: {:?}", &expected[0..8]);
        info!("  Actual[0..8]:   {:?}", &actual[0..8]);
        info!("  Expected[32..40]: {:?}", &expected[32..40]);
        info!("  Actual[32..40]:   {:?}", &actual[32..40]);
        info!("  Expected[128..136]: {:?}", &expected[128..136]);
        info!("  Actual[128..136]:   {:?}", &actual[128..136]);
        warn!("  This means GPU shader and CPU dequant produce different bytes-to-element mappings.");
    }

    ProbeResult { passed, expected, actual, max_error }
}
