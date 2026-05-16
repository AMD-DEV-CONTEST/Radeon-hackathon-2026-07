You are an expert in transformer architectures, MoE routing, and Rust + wgpu compute shaders. I'm writing a pure-Rust + wgpu inference engine targeting Vulkan on Tesla P100s. I need a complete MoE forward path design.

## Context
- Existing engine runs dense Qwen2.5-Coder-1.5B Q6_K with coherent output.
- Forward pass per layer in `src/forward_pass.rs`: Attn RMSNorm → QKV proj+bias → RoPE → KV cache write → multi-head attention (QK^T, softmax, AV) → O proj → residual → FFN RMSNorm → gate(silu)*up → down → residual.
- We have these pipelines already: matvec, matvec_bias, matmul_tiled, rmsnorm, rope, softmax, attention (QK), attn_value (AV), swiglu, add, transpose, dequant_q4km, dequant_q6k.
- Goal: support Qwen3-MoE and Gemma-4-MoE.

## Architectural targets
**Qwen3-MoE** (e.g. Qwen3.6-35B-A3B-MXFP4_MOE):
- Tensor names: `blk.{i}.ffn_gate_inp.weight` (router), `blk.{i}.ffn_gate_exps.weight`, `blk.{i}.ffn_up_exps.weight`, `blk.{i}.ffn_down_exps.weight` (experts concatenated along expert dim).
- Routing: top-k softmax gating, k=2..8, normalize selected weights.
- No shared experts.

**Gemma-4-MoE** (Gemma-4-26B-MoE-IQ4_XS):
- Same tensor name pattern.
- Routing: top-2.
- Sliding window attention (window=4096).

## Deliverable
A complete MoE forward path that drops into our existing per-layer execution.

Provide all of:

### 1. Top-k gate kernel
WGSL shader `moe_gate.wgsl`:
- Input: hidden state `x[hidden_dim]`, router weight `w_gate[n_experts × hidden_dim]`.
- Compute logits = x @ w_gate^T → softmax → top-k.
- Output: `expert_ids[k]` (u32), `expert_weights[k]` (f32, normalized to sum to 1).
- Uniform: `struct GateParams { hidden_dim: u32, n_experts: u32, k: u32, _pad: u32 }`.
- Single workgroup is fine since n_experts is small (<= 256).

### 2. Per-expert FFN dispatch
A Rust function:
```rust
pub fn dispatch_moe_ffn(
    encoder: &mut wgpu::CommandEncoder,
    pipelines: &MoePipelines,
    hidden_state: &wgpu::Buffer,    // [hidden_dim]
    expert_ids: &wgpu::Buffer,      // [k]
    expert_weights: &wgpu::Buffer,  // [k]
    expert_gate_w: &wgpu::Buffer,   // [n_experts × ffn_dim × hidden_dim]
    expert_up_w: &wgpu::Buffer,
    expert_down_w: &wgpu::Buffer,
    scratch_gate: &wgpu::Buffer,    // [ffn_dim] — reused per expert
    scratch_up: &wgpu::Buffer,      // [ffn_dim]
    scratch_silu_up: &wgpu::Buffer, // [ffn_dim]
    output: &wgpu::Buffer,          // [hidden_dim] — accumulated
    k: u32,
);
```
- Strategy: read `expert_ids` back to CPU after the gate dispatch (k <= 8, single readback per layer is fine), then for each expert do `gate=silu(x@W_gate_e); up=x@W_up_e; down=W_down_e@(gate*up); output += weight_e * down`.
- Alternative (better): do it entirely on GPU using indirect dispatch or a kernel that reads `expert_ids` from a buffer. Pick whichever is simpler and explain tradeoffs.
- We want to reuse our existing matvec / matvec_bias / swiglu pipelines where possible.

### 3. Weighted accumulation kernel
WGSL `moe_combine.wgsl` if needed: out[i] += weight * expert_out[i].
(Or fuse into the down-projection.)

### 4. Tensor loading
Show how to extract per-expert weight slices from the concatenated `ffn_gate_exps.weight` tensor. Shape is `[n_experts, ffn_dim, hidden_dim]` in row-major. Provide either:
- A "per-expert offset" function that returns a byte offset + length to bind a sub-region of the concatenated buffer, OR
- A loader that splits at GGUF read time into n_experts separate buffers.

Recommend which is better for our chunked-tensor loader (some tensors get split across multiple wgpu buffers for large models).

### 5. Integration sketch
Show the changes to `forward_pass.rs::execute_layer` so when `arch.is_moe()` is true, we route through the MoE FFN path instead of the dense gate/up/down/swiglu sequence. A minimal diff is fine.

OUTPUT FORMAT:
```rust
// === FILE: shaders/moe_gate.wgsl ===
... full file ...

// === FILE: shaders/moe_combine.wgsl (optional) ===
...

// === FILE: src/moe.rs ===
... pipeline structs, dispatch_moe_ffn, expert weight slicing helper ...

// === DIFF: src/forward_pass.rs ===
... unified diff or before/after blocks ...

// === NOTES ===
- routing math gotchas (renormalization after top-k)
- numerical concerns (logit scaling, fp16 vs fp32 in router)
- memory: how big is the per-expert weight buffer for Gemma-4-MoE? (8 experts × ffn_dim × hidden_dim × bytes_per_element)
- whether to read expert_ids back to CPU vs GPU-side dispatch
```

Be concrete and complete. Working code over hand-waving.
