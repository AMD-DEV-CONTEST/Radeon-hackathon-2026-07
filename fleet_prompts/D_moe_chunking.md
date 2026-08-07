You are an expert in Rust, wgpu/WGSL, and large model inference on memory-constrained GPUs. I need a complete MoE forward path + >1GB tensor chunking strategy for a pure-Rust+wgpu inference engine on Tesla P100 (16GB VRAM, 976MB Vulkan allocation limit per buffer).

## Context
- Engine runs dense Qwen2.5-Coder-1.5B Q6_K at 0.1 t/s (bottleneck: too many queue.submit() calls per layer — fixing separately)
- Existing chunker: `ChunkedTensor` splits F32/F16/Q4K tensors across multiple wgpu::Buffers, each ≤900MB. Works for dense models.
- Goal: support Gemma-4-26B-MoE-IQ4_XS and Qwen3.6-35B-A3B-Q4_K_M

## The >1GB MoE problem
Gemma-4-26B-MoE has 8 experts. Expert weight tensors are stored concatenated:
- `blk.{i}.ffn_gate_exps.weight` shape: [n_experts=8, ffn_dim=14336, hidden_dim=3584]
- Size at IQ4_XS: 8 × 14336 × 3584 × (136/256) bytes ≈ **1.73 GB** — exceeds 976MB limit
- Same for ffn_up_exps and ffn_down_exps

The existing chunker doesn't know about the expert dimension. It just sees a huge flat tensor.

## Deliverable 1: Expert-aware chunking in tensor_loader_safe.rs

Extend `TensorHandle` to add a `MoeExperts` variant:
```rust
pub enum TensorHandle {
    Single { buffer: wgpu::Buffer, shape: [usize; 2], dtype: Dtype },
    Chunked { tensor: ChunkedTensor },
    MoeExperts {
        /// One buffer per expert. Each buffer holds [ffn_dim × hidden_dim] weights.
        expert_buffers: Vec<wgpu::Buffer>,
        n_experts: usize,
        expert_rows: usize,   // ffn_dim
        expert_cols: usize,   // hidden_dim
        dtype: Dtype,
    },
}
```

In `load_tensor_safe`, detect MoE expert tensors by name pattern (`ffn_gate_exps`, `ffn_up_exps`, `ffn_down_exps`) and split them into per-expert buffers at load time:
```rust
pub fn load_tensor_safe(&mut self, name: &str, shape: [usize; 2], data_type: TensorType, raw_bytes: &[u8]) -> Result<(), MemoryError> {
    // If name contains "exps" and shape[0] is divisible by n_experts:
    //   split into n_experts separate buffers, each [ffn_dim × hidden_dim]
    //   dequant each expert slice to F32 before upload
    //   store as TensorHandle::MoeExperts
}
```

Also add `get_expert_buffer(name: &str, expert_idx: usize) -> Option<&wgpu::Buffer>` to TensorRegistry.

## Deliverable 2: MoE gate shader (shaders/moe_gate.wgsl)

```wgsl
struct GateParams { hidden_dim: u32, n_experts: u32, k: u32, _pad: u32 }
@group(0) @binding(0) var<uniform> params: GateParams;
@group(0) @binding(1) var<storage, read> x: array<f32>;           // [hidden_dim]
@group(0) @binding(2) var<storage, read> w_router: array<f32>;    // [n_experts × hidden_dim]
@group(0) @binding(3) var<storage, read_write> expert_ids: array<u32>;     // [k]
@group(0) @binding(4) var<storage, read_write> expert_weights: array<f32>; // [k], normalized
```

Single workgroup (n_experts ≤ 256). Steps:
1. Compute logits[e] = dot(x, w_router[e*hidden_dim .. (e+1)*hidden_dim])
2. Stable softmax over all n_experts logits
3. Top-k selection (selection sort, k ≤ 8)
4. Renormalize selected weights to sum to 1.0
5. Write expert_ids[0..k] and expert_weights[0..k]

Use workgroup shared memory for the logits array. Handle n_experts up to 256.

## Deliverable 3: MoE FFN dispatch (src/moe_dispatch.rs)

CPU-side dispatch that reads expert_ids back from GPU (k ≤ 8, one readback per layer, ~10μs acceptable), then dispatches k matvec chains:

```rust
pub struct MoeDispatch {
    pub k: u32,
    pub n_experts: u32,
    pub hidden_dim: u32,
    pub ffn_dim: u32,
}

/// Dispatch MoE FFN for one token.
/// Reads expert_ids/weights from GPU, loops over k experts, accumulates output.
pub fn dispatch_moe_ffn(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    dispatch: &MoeDispatch,
    pipelines: &LayerPipelines,          // reuse existing matvec/swiglu pipelines
    hidden_state: &wgpu::Buffer,         // [hidden_dim] input
    expert_ids_buf: &wgpu::Buffer,       // [k] u32 — read back to CPU
    expert_weights_buf: &wgpu::Buffer,   // [k] f32 — read back to CPU
    gate_expert_bufs: &[wgpu::Buffer],   // [n_experts] each [ffn_dim × hidden_dim]
    up_expert_bufs: &[wgpu::Buffer],
    down_expert_bufs: &[wgpu::Buffer],
    scratch_gate: &wgpu::Buffer,         // [ffn_dim] scratch
    scratch_up: &wgpu::Buffer,
    scratch_silu: &wgpu::Buffer,
    output: &wgpu::Buffer,               // [hidden_dim] accumulated output (zeroed before call)
);
```

Strategy: CPU readback of expert_ids (k u32s = 32 bytes, negligible), then for each selected expert:
- gate_out = matvec(hidden_state, gate_expert_bufs[eid])  → scratch_gate
- up_out   = matvec(hidden_state, up_expert_bufs[eid])    → scratch_up
- silu_out = swiglu(scratch_gate, scratch_up)             → scratch_silu
- down_out = matvec(scratch_silu, down_expert_bufs[eid])  → temp
- output  += expert_weight * down_out   (weighted accumulate)

Reuse existing `dispatch_matvec` and `dispatch_swiglu` from forward_pass.rs.

## Deliverable 4: moe_combine.wgsl (weighted accumulate)
```wgsl
// output[i] += weight * expert_out[i]
struct CombineParams { n: u32, weight: f32, _pad0: u32, _pad1: u32 }
@group(0) @binding(0) var<uniform> params: CombineParams;
@group(0) @binding(1) var<storage, read> expert_out: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;
@compute @workgroup_size(256) fn main(@builtin(global_invocation_id) gid: vec3<u32>) { ... }
```

## Deliverable 5: forward_pass.rs integration sketch

Show the diff to `execute_layer` that routes through MoE when `arch.is_moe()`:
```rust
// BEFORE (dense FFN):
dispatch_rmsnorm(..., &ffn_normed, &weights.ffn_norm);
dispatch_matvec(..., &ffn_normed, &weights.gate_proj, &scratch_gate);
dispatch_matvec(..., &ffn_normed, &weights.up_proj, &scratch_up);
dispatch_swiglu(..., &scratch_gate, &scratch_up, &scratch_silu);
dispatch_matvec(..., &scratch_silu, &weights.down_proj, hidden_state);

// AFTER (MoE branch):
if arch.is_moe() {
    // 1. Gate: compute expert_ids + weights
    dispatch_moe_gate(..., &ffn_normed, &weights.moe_router, &expert_ids_buf, &expert_weights_buf);
    queue.submit(...); // flush gate before readback
    // 2. FFN: dispatch k experts, accumulate
    dispatch_moe_ffn(...);
} else {
    // dense path unchanged
}
```

## NOTES TO INCLUDE:
- Memory math: Gemma-4-26B-MoE expert buffers total size at IQ4_XS (dequanted to F32)
- Why per-expert split at load time beats sub-buffer binding (wgpu doesn't support sub-buffer offsets in bind groups without BufferBinding offset, which requires alignment)
- Renormalization: after top-k, weights must sum to 1.0 (divide each by sum of selected)
- Zero the output buffer before accumulation loop

## OUTPUT FORMAT
```rust
// === FILE: src/tensor_loader_safe.rs (MoeExperts variant + load logic) ===
// === FILE: shaders/moe_gate.wgsl ===
// === FILE: shaders/moe_combine.wgsl ===
// === FILE: src/moe_dispatch.rs ===
// === DIFF: src/forward_pass.rs ===
// === NOTES ===
```
Complete working code. No stubs.
