```rust
// === ANALYSIS: Correct minimal submit sequence for P100 Vulkan ===
// The P100 Vulkan driver fails to synchronize RAW (Read-After-Write) hazards within a single encoder.
// Therefore, any buffer that is WRITTEN by an op and then READ by another must be in a separate submit.
// However, multiple ops that WRITE to DIFFERENT buffers can be batched if they all READ from the same source.

// Layer Sequence:
// 1. [RMSNorm] -> writes normed_buf.
//    (Boundary: normed_buf is now ready)
// 2. [Q_proj, K_proj, V_proj] -> all READ normed_buf, but write to DIFFERENT buffers (q_buf, k_buf, v_buf).
//    (Boundary: q_buf, k_buf, v_buf are now ready)
// 3. [Q_bias, K_bias, V_bias] -> these are in-place additions. Each reads and writes its own buffer.
//    (Boundary: q_buf, k_buf, v_buf are fully updated)
// 4. [Attention] -> reads q, k, v; writes attn_out.
//    (Boundary: attn_out is ready)
// 5. [Attn_Residue] -> reads attn_out and hidden_state; writes updated hidden_state.
//    (Boundary: hidden_state is updated)
// 6. [FFN_Gate, FFN_Up] -> reads hidden_state; writes to different FFN buffers.
// 7. [FFN_Down] -> reads FFN buffers; writes to FFN_out.
// 8. [FFN_Residue] -> reads FFN_out and hidden_state; writes updated hidden_state.

// Target: ~6-8 submits per layer (down from 20+).

// === FILE: src/forward_pass.rs (optimized execute_layer) ===

pub fn execute_layer(
    &self,
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    scratch: &mut ScratchBuffers,
    layer_idx: usize,
) {
    // 1. RMSNorm (Write normed_buf)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("norm_enc") });
    self.rms_norm_pass(&mut encoder, ...); 
    queue.submit(Some(encoder.finish()));

    // 2. Projections (Read normed_buf, Write q, k, v)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("proj_enc") });
    self.q_proj_pass(&mut encoder, &scratch.normed, &mut scratch.q_buf, ...);
    self.k_proj_pass(&mut encoder, &scratch.normed, &mut scratch.k_buf, ...);
    self.v_proj_pass(&mut encoder, &scratch.normed, &mut scratch.v_buf, ...);
    queue.submit(Some(encoder.finish()));

    // 3. Biases (In-place: Read q, Write q)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("bias_enc") });
    self.bias_pass(&mut encoder, &scratch.q_buf, &scratch.q_bias, ...);
    self.bias_pass(&mut encoder, &scratch.k_buf, &scratch.k_bias, ...);
    self.bias_pass(&mut encoder, &scratch.v_buf, &scratch.v_bias, ...);
    queue.submit(Some(encoder.finish()));

    // 4. Attention (Read q, k, v; Write attn_out)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("attn_enc") });
    self.attention_pass(&mut encoder, &scratch.q_buf, &scratch.k_buf, &scratch.v_buf, &mut scratch.attn_out, ...);
    queue.submit(Some(encoder.finish()));

    // 5. Attention Residue (Read attn_out + hidden; Write hidden)
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("attn_res_enc") });
    self.residue_pass(&mut encoder, &scratch.attn_out, &mut self.hidden_state, ...);
    queue.submit(Some(encoder.finish()));

    // 6. FFN (Gate/Up -> Down -> Residue)
    // ... similar pattern of 3-4 submits ...
}

// === FILE: src/generate.rs (remove diagnostic readbacks) ===

// Use a macro or cfg guard to ensure zero overhead in release
macro_rules! diagnostic_readback {
    ($device:expr, $queue:expr, $buf:expr, $len:expr) => {
        if cfg!(debug_assertions) {
            // Actual heavy readback logic
            readback_f32($device, $queue, $buf, $len)
        } else {
            // Compile-time zero cost
            0.0f32 
        }
    };
}

// Inside generate loop:
// OLD: let hs_vals = readback_f32(device, queue, &hidden_state, 4);
// NEW:
let _hs_vals = diagnostic_readback!(device, queue, &hidden_state, 4); 

// === FILE: src/scratch_buffers.rs (persistent buffers) ===

pub struct ScratchBuffers {
    pub normed: wgpu::Buffer,
    pub q_buf: wgpu::Buffer,
    pub k_buf: wgpu::Buffer,
    pub v_buf: wgpu::Buffer,
    pub attn_out: wgpu::Buffer,
    pub ffn_gate: wgpu::Buffer,
    pub ffn_up: wgpu::Buffer,
    // ...
}

impl ScratchBuffers {
    pub fn new(device: &wgpu::Device, config: &Config) -> Self {
        // Pre-allocate all buffers once at startup
        Self {
            normed: device.create_buffer(&wgpu::BufferDescriptor { label: Some("normed"), size: ..., usage: wgpu::BufferUsages::STORAGE | wgpu::BufferUsages::COPY_SRC }),
            q_buf: device.create_buffer(...),
            // ...
        }
    }
}

// === FILE: src/layer_timer.rs ===

use std::time::Instant;

pub struct LayerTimer {
    pub start_time: Instant,
    pub layer_times: Vec<f32>,
}

impl LayerTimer {
    pub fn new(num_layers: usize) -> Self {
        Self {
            start_time: Instant::now(),
            layer_times: vec![0.0; num_layers],
        }
    }

    pub fn mark_layer(&mut self, layer_idx: usize, duration: std::time::Duration) {
        self.layer_times[layer_idx] = duration.as_secs_f32() * 1000.0;
    }

    pub fn print_summary(&self, total_tokens: usize) {
        let total_duration = self.start_time.elapsed();
        println!("\n--- Generation Summary ---");
        println!("Total Time: {:.2}s for {} tokens", total_duration.as_secs_f32(), total_tokens);
        println!("Avg: {:.2} t/s", total_tokens as f32 / total_duration.as_secs_f32());
        println!("Layer Breakdown (ms):");
        for (i, t) in self.layer_times.iter().enumerate() {
            print!("L{:02}: {:.1}ms  ", i, t);
            if (i + 1) % 4 == 0 { println!(); }
        }
        println!("\n--------------------------\n");
    }
}

// === EXPECTED SPEEDUP ===
// Current: ~15 submits/layer × 28 layers × ~1ms/submit = ~420ms overhead/token
// After: ~6 submits/layer × 28 layers × ~1ms/submit = ~168ms overhead/token
// Plus readback removal: saves ~6 × 28 × ~2ms = ~336ms/token
// Total expected: from 0.1 t/s → ~1.5 - 2.5 t/s
```
