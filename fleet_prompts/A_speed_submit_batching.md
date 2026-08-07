You are an expert in wgpu, Vulkan, and GPU compute pipeline optimization. I need to fix a severe performance bottleneck in a Rust+wgpu inference engine running on Tesla P100 via Vulkan.

## The problem: 0.1 t/s due to excessive queue.submit() calls

Current forward pass per layer does approximately 15-20 separate `queue.submit()` calls:
- 1 submit for attn RMSNorm
- 3 submits for Q/K/V projections (separate encoders)
- 3 submits for Q/K/V biases
- 1 submit for RoPE
- 1 submit for KV cache write
- 1 submit per attention head (2 heads × 3 ops = 6 submits)
- 1 submit for O projection
- 1 submit for attention residual
- 1 submit for FFN RMSNorm
- 2 submits for gate+up projections
- 1 submit for SwiGLU
- 1 submit for down projection
- 1 submit for FFN residual

Each `queue.submit()` on P100 Vulkan costs ~0.5-2ms (PCIe round-trip + driver overhead). At 28 layers × 15 submits × 1ms = **420ms per token minimum** just in submit overhead. That's the 0.1 t/s.

## The P100 Vulkan memory visibility constraint (CRITICAL)

We previously discovered that P100 Vulkan does NOT guarantee memory visibility between dependent compute passes within a single command encoder. Specifically:
- compute writes to buffer A → copy buffer A to buffer B in same encoder → NOT safe on P100
- compute writes to buffer A → compute reads buffer A in same encoder → NOT safe on P100

This is why we split into separate submits. But we over-split.

## What IS safe to batch in one encoder

Within a single command encoder, these are safe to batch (no RAW hazard):
1. **Independent ops** — ops that don't read each other's outputs
2. **Sequential ops with pipeline barriers** — wgpu inserts implicit barriers between compute passes in the same encoder on most drivers, but P100 Vulkan is buggy here

The SAFE batching strategy for P100:
- Batch ops that write to DIFFERENT buffers (no dependency)
- Submit before any op that READS a buffer written by a previous op in the same encoder
- Use separate encoders for dependent chains, but batch independent ops together

## Deliverable 1: Optimized execute_layer structure

Rewrite the submit pattern to minimize submits while staying safe on P100 Vulkan.

Target: **3-4 submits per layer** instead of 15-20.

Safe batching groups:
```
Submit 1: [attn_rmsnorm → normed_buf] + [Q_proj(normed) → q_buf] + [K_proj(normed) → k_buf] + [V_proj(normed) → v_buf]
  // All 4 ops write to DIFFERENT output buffers. normed_buf is read by Q/K/V but written by rmsnorm first.
  // WAIT: rmsnorm writes normed_buf, then Q/K/V read it — this IS a RAW hazard within one encoder on P100.
  // Solution: split rmsnorm into its own submit, then batch Q/K/V together.

Submit 1: attn_rmsnorm → normed_buf
Submit 2: Q_proj + K_proj + V_proj (all read normed_buf, write to different q/k/v bufs — safe to batch)
          + Q_bias + K_bias + V_bias (read q/k/v, write to same q/k/v — RAW hazard! need separate)
```

Actually work out the correct minimal submit sequence. Show your reasoning for each boundary.

Key insight: **Q/K/V projections all READ the same normed_buf but write to DIFFERENT output buffers** — they can be batched in one encoder after normed_buf is ready.

**Q_bias adds to q_buf in-place** — this reads AND writes q_buf, so it must come after Q_proj in a separate submit.

Work out the full optimal sequence. Target ≤ 5 submits per layer.

## Deliverable 2: Remove diagnostic readbacks

The current code has `readback_f32()` calls on every layer that do full GPU→CPU synchronization:
```rust
// In forward_pass.rs execute_layer (layer 0 only but still):
let hs_start = readback_f32(device, queue, hidden_state, 4);
let norm_weight_diag = readback_f32(device, queue, &weights.attn_norm, 4);
let normed_diag = readback_f32(device, queue, &normed, 4);
let q_diag = readback_f32(device, queue, &q_buf, 4);
let v_diag = readback_f32(device, queue, &v_buf, 4);
let diag = readback_f32(device, queue, &attn_output, 4);
```

And in generate.rs:
```rust
let hs_vals = readback_f32(device, queue, &hidden_state, 4);
let vals = readback_f32(device, queue, hidden_state, 4);
let all_vals = readback_f32(device, queue, hidden_state, config.hidden_dim as usize);
```

Each `readback_f32` does: create staging buffer → copy_buffer_to_buffer → submit → map_async → poll loop → read. This is a full GPU pipeline stall.

Provide:
- A `cfg!(debug_assertions)` guard pattern that compiles out all readbacks in release mode
- Or a `--diagnostic` CLI flag approach
- The exact lines to change in forward_pass.rs and generate.rs

## Deliverable 3: Persistent scratch buffers (already partially done)

The engine creates temporary buffers per-layer per-token:
```rust
let normed = device.create_buffer(...);  // per execute_layer call
let q_buf = device.create_buffer(...);
let k_buf = device.create_buffer(...);
// etc.
```

Show how to pre-allocate these in `ScratchBuffers` (already exists in scratch_buffers.rs) and reuse them across layers. The key constraint: buffers must not be aliased across concurrent ops (but we're single-threaded sequential, so reuse is safe).

## Deliverable 4: Timing instrumentation

Add a lightweight per-layer timer that measures actual GPU time (not wall clock):
```rust
// Use wgpu timestamp queries if available, else wall clock
pub struct LayerTimer {
    pub layer_ms: Vec<f32>,
    pub total_ms: f32,
}
```

Show how to add this to the generate loop and print a summary after generation:
```
Layer timing (28 layers, 1 token):
  L0: 18.2ms  L1: 17.8ms  ... L27: 18.1ms
  Total: 508ms/token = 2.0 t/s
  Breakdown: attn=45% ffn=40% overhead=15%
```

## OUTPUT FORMAT
```rust
// === ANALYSIS: Correct minimal submit sequence for P100 Vulkan ===
// Submit 1: ...
// Submit 2: ...
// (justify each boundary)

// === FILE: src/forward_pass.rs (optimized execute_layer) ===
// Show the full rewritten function with minimal submits

// === FILE: src/generate.rs (remove diagnostic readbacks) ===
// Show the changes

// === FILE: src/scratch_buffers.rs (persistent buffers) ===
// Show additions

// === FILE: src/layer_timer.rs ===
// Full timing module

// === EXPECTED SPEEDUP ===
// Current: ~15 submits/layer × 28 layers × ~1ms/submit = ~420ms overhead/token
// After: ~4 submits/layer × 28 layers × ~1ms/submit = ~112ms overhead/token
// Plus readback removal: saves ~6 × 28 × ~2ms = ~336ms/token
// Total expected: from 0.1 t/s → X t/s
```
