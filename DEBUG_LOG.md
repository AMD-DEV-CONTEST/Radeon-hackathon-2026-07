# CESARops Inference Engine — Debug Log

## Model: Qwen2.5-Coder-1.5B-Instruct Q6_K
- hidden_dim=1536, intermediate_dim=8960, n_heads=12, n_kv_heads=2
- head_dim=128, n_layers=28, vocab_size=151936, rope_theta=1000000

## Bugs Found & Fixed

### 1. GPU Sync (P100 Vulkan storage buffer hazard)
- **Symptom**: FFN output wrong when all ops batched in single command encoder
- **Root cause**: P100 Vulkan driver doesn't properly barrier storage buffer RAW between compute passes in same encoder
- **Fix**: Split into separate encoder+submit per operation group
- **Verification**: FFN diagnostic matches Python reference to 4 decimal places at all 6 steps

### 2. RoPE shader gid.x vs lid.x
- **Symptom**: Only head 0 was being rotated
- **Root cause**: `pair_idx = gid.x` — for workgroup 1+, gid.x >= 64 >= half_dim, all threads return early
- **Fix**: Changed to `pair_idx = lid.x` (local_invocation_id)
- **Verification**: RoPE now applies to all heads

### 3. Attention score clamp destroying signal
- **Symptom**: Attention scores clamped to [-30, 30], layer 0 scores ~182 both hit ceiling → softmax uniform [0.5, 0.5]
- **Root cause**: `clamp(score, -30, 30)` added earlier as stability measure
- **Fix**: Removed clamp entirely. Softmax max-subtraction handles large values correctly.
- **Verification**: Scores now pass through, softmax produces meaningful distributions

### 4. vocab_size mismatch (152064 metadata vs 151936 tensor)
- **Symptom**: lm_head matvec dispatched for 152064 rows but buffer only has 151936
- **Root cause**: GGUF metadata reports padded vocab, actual tensor is smaller
- **Fix**: Use token_embd.weight tensor shape[1] for vocab_size
- **Verification**: Config now shows 151936V

### 5. matmul_f32.wgsl deprecated syntax
- **Symptom**: Shader compilation panic at startup
- **Root cause**: Old `[[group(0), binding(0)]]` syntax, wgpu requires `@group(0) @binding(0)`
- **Fix**: Updated shader syntax

## Verified Correct (matches Python reference exactly)

### Single-token (pos=0) full 28-layer path:
- Token 9707 ("Hello"):
  - FFN-only: top token 97309 (logit 18.12) ✓
  - With attention: top token 135144 (logit 18.88) ✓
- Token 13048 ("Hi"):
  - With attention: top token 47117 (logit 16.19) ✓

### Two-token (pos=1) decode:
- Sequence [9707, 135144] at pos=1:
  - L0 H0 scores=[181.962, 183.605] probs=[0.162, 0.838] ✓
  - Top token at pos=1: 88359 ✓

### Component-level verification:
- Dequant Q6_K: PASS (256 elements match Python)
- Embedding lookup: PASS (values match for tokens 0, 9707, 13048)
- RMSNorm: PASS (layer 0 FFN norm matches Python)
- Matvec (gate, up, down, Q, K, V, O projections): ALL PASS
- SwiGLU: PASS
- Attention (pos=0, trivial): PASS
- Attention (pos=1, kv_len=2): PASS (scores match Python)
- Residual additions: PASS
- Final RMSNorm + lm_head: PASS
- Sampling (greedy argmax): PASS

## CURRENT STATUS: Multi-token prefill broken

### What works:
- 1-token prompt → first generated token is CORRECT
- 2-token decode (pos=1 after pos=0 prefill) is CORRECT

### What's broken:
- Multi-token prompts (e.g. chat template with 14 tokens) produce garbled output
- The prefill loop processes tokens sequentially (pos=0, 1, 2, ..., 13)
- Each position's attention sees all previous positions via KV cache
- Something goes wrong when kv_len > 2

### Top suspects:
1. **KV cache pointer/offset issue at longer sequences** — the cache write at pos=N might be overwriting pos=0 or reading wrong offsets when kv_len grows
2. **Causal mask dimensioning** — the attention shader uses `kv_len = cur_pos + 1` which should be correct, but maybe the softmax workgroup dispatch doesn't handle kv_len > 256 (workgroup size)
3. **Softmax with kv_len > 1 workgroup** — our softmax dispatches 1 workgroup of 256 threads. For kv_len > 256, threads stride. But for kv_len=14, this should be fine (14 < 256).

### Key observation:
- Output is IDENTICAL with and without RoPE for multi-token prompts
- This was tested when attention residual was disabled, so may not apply now
- Need to retest with current code (attention enabled)

## Architecture Notes

### KV Cache Layout:
- `[pos][n_kv_heads][head_dim]` = `[pos][2][128]`
- Stride between positions: `n_kv_heads * head_dim * 4` = `2 * 128 * 4` = 1024 bytes
- K at position p, head h: offset = `p * 256 + h * 128` (in elements)

### Attention Dispatch:
- Per-head: QK^T → softmax → AV, each in separate submit
- Fresh scores_buf and probs_buf per head (no reuse)
- kv_stride = n_kv_heads * head_dim = 256
- kv_head_offset = kv_head * head_dim

### Forward Pass Order:
1. Attn RMSNorm → submit
2. QKV projections → submit
3. Biases + RoPE → submit
4. KV cache write → submit
5. Multi-head attention (per-head submits) → submit per head
6. O_proj → submit
7. Attention residual → submit
8. FFN RMSNorm → submit
9. Gate + Up → submit
10. SwiGLU → submit
11. Down → submit
12. FFN residual → caller submits

## Files:
- `src/forward_pass.rs` — layer execution with split submits
- `src/generate.rs` — token generation loop
- `src/attention_dispatch.rs` — multi-head attention with per-head submits
- `src/main.rs` — model loading, config, generation entry point
- `shaders/attention.wgsl` — QK^T dot product
- `shaders/softmax.wgsl` — stable softmax with parallel reduction
- `shaders/attn_value.wgsl` — AV weighted sum
- `shaders/rope.wgsl` — RoPE rotation (half-split pairs)
- `shaders/matvec.wgsl` — matrix-vector multiply
- `shaders/rmsnorm.wgsl` — RMSNorm with vec4 loads
- `shaders/swiglu.wgsl` — fused SwiGLU activation


---

## 2026-05-16 — ROOT CAUSE FOUND AND FIXED: Q6_K block-structured indexing

### Symptom
After fixing every other suspected issue (RoPE head indexing, attention clamps,
vocab size, GPU sync hazards, bias staging, fused matvec_bias), the engine
still produced garbled tokens. Koboldcpp with the SAME GGUF produced coherent
output ("2+2 equals", ".").

### Root cause
`dequant_q6_k` (CPU + GPU shader + probe) used naive sequential indexing:
- `ql_byte = ql[idx/2]`, low/high nibble by `idx%2`
- `qh_byte = qh[idx/4]`, 2-bit slice by `idx%4`
- `scale = scales[idx/16]`

llama.cpp's `dequantize_row_q6_K` (`ggml-quants.c`) processes each 256-element
super-block as **two 128-element halves**. Inside each half, an inner loop
`l = 0..32` produces **4 outputs at relative positions `l, l+32, l+64, l+96`**
from interleaved ql/qh nibbles and 4 *interleaved* sub-block scale entries
(`is, is+2, is+4, is+6`). Magnitudes were close (global scale `d` correct) but
values were permuted to wrong positions, so logits were noise.

The Python "reference" probe used the same wrong indexing, producing circular
validation. Bytes themselves were never the issue — the byte-to-element
mapping was.

### Fixes applied
1. **`src/tensor_loader_safe.rs::dequant_q6_k`** — rewritten to follow
   llama.cpp's two-halves / inner-32 pattern with interleaved scales.
2. **`shaders/dequant_q6k.wgsl`** — same block-structured decode in WGSL.
   Per-element: derive `(half, slot, l)` from `local_idx`, read the right
   ql/qh bytes, pick the right qh shift and scale offset for the slot.
3. **`src/dequant_probe.rs`** — replaced uniform-byte synthetic block with a
   *discriminating* pattern (distinct ql, qh, and scale bytes per position)
   and a CPU reference function that mirrors llama.cpp exactly. A wrong
   indexing strategy would now visibly fail at specific positions.

### Verification
- Build: `cargo build --release` — clean.
- `Dequant probe PASSED — GPU matches llama.cpp CPU reference (max_err=0.000000)`.
- `generate "Hello" --max-tokens 5` →
  `Hello! How can I` (token IDs `[9707, 0, 2585, 646, 358]`).
- `generate "What is 2+2?" --max-tokens 15` →
  `2+2 equals 4.` (token IDs `[17, 10, 17, 16819, 220, 19, 13]`).

Coherent multi-token output achieved. Engine reaches parity with koboldcpp on
the prompts we used as ground truth.

### Lesson
Cross-validate against an *independent* reference implementation (llama.cpp's
own decode loop, byte-for-byte), not against your own Python port that may
share the same bug. A probe with all-equal bytes can hide an indexing bug
because every output ends up identical regardless of mapping.
