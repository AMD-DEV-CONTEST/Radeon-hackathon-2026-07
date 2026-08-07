#!/usr/bin/env python3
"""
Inject corrections, good examples, and lessons learned into the nautivecs store.
Entries are added with zero embeddings (will be re-embedded when P100s are free).
The text content is still searchable via keyword matching in the index.

Run: python3 fleet_prompts/inject_corrections.py
"""

import json
import hashlib
import time
import os

STORE_PATH = "/mnt/data-external/cesarops/nautivecs/store.json"

def make_entry(text: str, file_path: str, symbol_name: str, tags: str = "") -> dict:
    content_hash = hashlib.md5(text.encode()).hexdigest()[:16]
    return {
        "text": text,
        "file_path": file_path,
        "symbol_name": symbol_name,
        "symbol_type": "lesson",
        "line_start": 1,
        "line_end": text.count('\n') + 1,
        "content_hash": content_hash,
        "tags": tags,
        "embedding": [0.0] * 1024,  # will be re-embedded later
    }

# ── All corrections and good examples ────────────────────────────────────────

ENTRIES = [

# ── Q6_K DEQUANT ROOT CAUSE ──────────────────────────────────────────────────
make_entry("""
CORRECTION: Q6_K dequantization block-structured indexing (llama.cpp match)

WRONG (naive sequential):
  ql_byte = ql[idx/2]
  qh_byte = qh[idx/4], shift = (idx%4)*2
  scale = scales[idx/16]

CORRECT (llama.cpp dequantize_row_q6_K):
  Process 256-element block as TWO 128-element halves.
  For each half, inner loop l=0..32 produces 4 outputs at l, l+32, l+64, l+96.
  Interleaved scale indices: sc[sc_off + is], sc[sc_off + is+2], sc[sc_off + is+4], sc[sc_off + is+6]
  where is = l/16.

  for half in 0..2:
    ql_off = half * 64; qh_off = half * 32; sc_off = half * 8
    for l in 0..32:
      is = l / 16
      q1 = ((ql[ql_off+l] & 0xF) | (((qh[qh_off+l]>>0)&3)<<4)) - 32
      q2 = ((ql[ql_off+l+32] & 0xF) | (((qh[qh_off+l]>>2)&3)<<4)) - 32
      q3 = ((ql[ql_off+l]>>4) | (((qh[qh_off+l]>>4)&3)<<4)) - 32
      q4 = ((ql[ql_off+l+32]>>4) | (((qh[qh_off+l]>>6)&3)<<4)) - 32
      out[out_base+l]    = d * scales[sc_off+is]   * q1
      out[out_base+l+32] = d * scales[sc_off+is+2] * q2
      out[out_base+l+64] = d * scales[sc_off+is+4] * q3
      out[out_base+l+96] = d * scales[sc_off+is+6] * q4

LESSON: Validate dequant against llama.cpp byte-for-byte. A probe with all-equal bytes
cannot catch indexing bugs — use position-discriminating patterns.

RESULT: Fixed garbled output. Engine now produces "2+2 equals 4." and "Hello! How can I"
""",
"research_log/corrections.md", "q6k_dequant_fix",
"q6k,dequant,llama.cpp,wgsl,rust,correction,critical"),

# ── IQ4_XS DEQUANT ───────────────────────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: IQ4_XS dequantization (136 bytes per 256-element block)

Block layout: d[2] + scales_h[2] + scales_l[4] + qs[128]
8 sub-blocks of 32 elements each.

Sub-block scale reconstruction (6-bit signed, centered at 32):
  ib = element_index / 32  (sub-block 0..7)
  scale_low  = nibble ib of scales_l: byte = scales_l[ib/2], nibble = ib%2==0 ? low : high
  scale_high = bits [2*ib .. 2*ib+1] of scales_h
  scale_6bit = (scale_high << 4) | scale_low  -- then subtract 32

Quant index: nibble of qs[i/2], low if i even, high if i odd
Value: d * scale_6bit * kvalues_iq4nl[q_idx]

kvalues_iq4nl = [-127, -104, -83, -65, -49, -35, -22, -10, 1, 13, 25, 38, 53, 69, 89, 113]

WGSL sign-extension for 6-bit: i32(val) - 32  (NOT bitcast — bitcast doesn't sign-extend bytes)
""",
"research_log/corrections.md", "iq4xs_dequant",
"iq4xs,dequant,wgsl,rust,gemma4,good_example"),

# ── WGSL SIGN EXTENSION BUG ──────────────────────────────────────────────────
make_entry("""
CORRECTION: WGSL sign extension for packed bytes

WRONG: bitcast<i32>(byte_value)  -- bitcast reinterprets bits, does NOT sign-extend
WRONG: i32(bitcast<i32>(u32_val >> 24u))  -- shifts don't sign-extend either

CORRECT for i8 from u32:
  let byte = (packed_u32 >> shift) & 0xFFu;
  let signed = i32(byte) - select(0, 256, byte >= 128u);

CORRECT for 6-bit signed (centered at 32):
  let val6 = (high_bits << 4u) | low_bits;  // 0..63
  let signed6 = i32(val6) - 32;

CORRECT for Q8_0 i8 weights:
  let q = i32(data[offset + 2u + k]);
  let signed_q = q - select(0, 256, q >= 128);
  // OR: use the byte directly as i8 by subtracting 128 if >= 128
""",
"research_log/corrections.md", "wgsl_sign_extension",
"wgsl,sign_extension,i8,correction,common_bug"),

# ── P100 VULKAN SUBMIT HAZARD ─────────────────────────────────────────────────
make_entry("""
CORRECTION: P100 Vulkan RAW (Read-After-Write) hazard in compute passes

P100 Vulkan does NOT guarantee memory visibility between dependent compute passes
within a single command encoder. You MUST submit before any op that reads a buffer
written by a previous op in the same encoder.

SAFE to batch in one encoder (no RAW hazard):
- Multiple ops that write to DIFFERENT output buffers from the same source
- Example: Q_proj + K_proj + V_proj all read normed_buf, write to q/k/v (different) → SAFE

UNSAFE in one encoder (RAW hazard):
- RMSNorm writes normed_buf → Q_proj reads normed_buf → MUST submit between them
- Bias add writes q_buf → RoPE reads q_buf → MUST submit between them

OPTIMAL submit sequence per transformer layer (8 submits vs 15-20 naive):
  S1: attn_rmsnorm → normed
  S2: Q_proj + K_proj + V_proj (all read normed, write different bufs)
  S3: Q_bias + K_bias + V_bias (in-place, batch all three)
  S4: RoPE_Q + RoPE_K + KV_cache_write
  S5: attention (handled internally)
  S6: O_proj
  S7: attn_residual
  S8: ffn_rmsnorm
  S9: gate_proj + up_proj
  S10: swiglu
  S11: down_proj
  S12: ffn_residual (caller submits)
""",
"research_log/corrections.md", "p100_vulkan_submit_hazard",
"p100,vulkan,wgpu,submit,hazard,performance,correction"),

# ── WGSL ASYNC FN BUG ────────────────────────────────────────────────────────
make_entry("""
CORRECTION: WGSL does not have async functions

WRONG: async fn main(@builtin(global_invocation_id) id: vec3<u32>) { ... }
CORRECT: fn main(@builtin(global_invocation_id) id: vec3<u32>) { ... }

WGSL compute shaders are synchronous. There is no async/await in WGSL.
The @compute decorator marks the entry point. Workgroup synchronization
uses workgroupBarrier() for shared memory, not async primitives.
""",
"research_log/corrections.md", "wgsl_no_async",
"wgsl,async,correction,common_bug"),

# ── WGSL STRUCT IN FUNCTION BUG ──────────────────────────────────────────────
make_entry("""
CORRECTION: WGSL struct definitions must be at module scope, not inside functions

WRONG:
  fn main() {
    struct Entry { val: f32, idx: u32 }  // ERROR: struct inside function
    var pairs: array<Entry, 256>;
  }

CORRECT:
  struct Entry { val: f32, idx: u32 }  // at module scope
  fn main() {
    var pairs: array<Entry, 256>;
  }

Also: WGSL arrays in function scope must have a compile-time constant size.
var<workgroup> arrays must be at module scope.
""",
"research_log/corrections.md", "wgsl_struct_scope",
"wgsl,struct,scope,correction,common_bug"),

# ── GOOD EXAMPLE: MATVEC VEC4 ────────────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: WGSL matvec with vec4 input loads (4x memory bus utilization)

// Input stored as array<vec4<f32>> for 128-bit loads
@group(0) @binding(0) var<storage, read> input: array<vec4<f32>>;
@group(0) @binding(1) var<storage, read> weights: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<f32>;

struct Params { N: u32, K: u32, K_vec4: u32, _pad: u32 }

@compute @workgroup_size(256, 1, 1)
fn main(@builtin(global_invocation_id) gid: vec3<u32>) {
    let n = gid.x;
    if (n >= params.N) { return; }
    var sum: f32 = 0.0;
    let w_base = n * params.K;
    for (var i: u32 = 0u; i < params.K_vec4; i = i + 1u) {
        let v = input[i];
        sum += v.x * weights[w_base + i*4u];
        sum += v.y * weights[w_base + i*4u + 1u];
        sum += v.z * weights[w_base + i*4u + 2u];
        sum += v.w * weights[w_base + i*4u + 3u];
    }
    // Handle K % 4 != 0 tail
    for (var k: u32 = params.K_vec4 * 4u; k < params.K; k = k + 1u) {
        sum += input[k/4u][k%4u] * weights[w_base + k];
    }
    output[n] = sum;
}

NOTE: Input buffer must be bound as array<vec4<f32>>, not array<f32>.
This requires the input to be 16-byte aligned (f32 × 4 = 16 bytes).
""",
"research_log/good_examples.md", "matvec_vec4",
"wgsl,matvec,vec4,optimization,good_example,p100"),

# ── GOOD EXAMPLE: RMSNORM WITH VEC4 ─────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: RMSNorm with vec4 loads and parallel reduction tree

Already implemented correctly in shaders/rmsnorm.wgsl:
- Uses array<vec4<f32>> for input, weight, output
- Parallel reduction tree (log2 steps, not sequential)
- Workgroup size 256 for good P100 occupancy
- Phase 1: each thread accumulates sum-of-squares over its stride
- Phase 2: reduction tree in shared memory
- Phase 3: broadcast rms_scale from shared_sum[0]
- Phase 4: apply normalization with vec4 multiply

This is the reference pattern for all reduction kernels.
""",
"research_log/good_examples.md", "rmsnorm_vec4",
"wgsl,rmsnorm,vec4,reduction,good_example,p100"),

# ── GOOD EXAMPLE: Q6_K WGSL SHADER ──────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: Q6_K WGSL dequant shader (block-structured, matches llama.cpp)

Key pattern for per-element decode:
  let half = local_idx / 128u;      // 0 or 1
  let in_half = local_idx % 128u;   // 0..127
  let slot = in_half / 32u;         // 0,1,2,3 (which of 4 outputs from this l)
  let l = in_half % 32u;            // 0..31

  ql_off = half * 64u; qh_off = 128u + half * 32u; sc_off = 192u + half * 8u

  ql_a = read_byte(boff, ql_off + l)
  ql_b = read_byte(boff, ql_off + l + 32u)
  qh_b = read_byte(boff, qh_off + l)

  slot 0: q_low = ql_a & 0xF, qh_shift = 0
  slot 1: q_low = ql_b & 0xF, qh_shift = 2
  slot 2: q_low = (ql_a >> 4) & 0xF, qh_shift = 4
  slot 3: q_low = (ql_b >> 4) & 0xF, qh_shift = 6

  qh_bits = (qh_b >> qh_shift) & 0x3u
  q6 = i32(q_low | (qh_bits << 4u)) - 32

  is = l / 16u
  scale_byte = read_byte(boff, sc_off + is + slot * 2u)
  scale_signed = i32(scale_byte) - select(0, 256, scale_byte >= 128u)

  output = d * f32(scale_signed) * f32(q6)
""",
"research_log/good_examples.md", "q6k_wgsl_shader",
"wgsl,q6k,dequant,good_example,shader"),

# ── GEMMA 4 MODEL GRADES ─────────────────────────────────────────────────────
make_entry("""
MODEL PERFORMANCE GRADES: Gemma 4 26B MoE IQ4_XS (P100 :5001/:5555)

Overall: B- / 7/10

STRENGTHS:
- Architecture and math: strong. Correctly identifies bandwidth bottlenecks,
  gives good performance estimates, understands MoE routing.
- Algorithm design: solid. Speculative decoding algorithm correct,
  submit batching analysis correct.
- Rust code: generally correct, compiles with minor fixes.

WEAKNESSES:
- WGSL correctness: produces plausible-looking shaders with subtle bugs:
  * Uses 'async fn' in WGSL (doesn't exist)
  * Wrong sign extension: bitcast<i32> doesn't sign-extend bytes
  * Defines structs inside functions (not allowed in WGSL)
  * Produces pseudo-code stubs mid-shader
  * Wrong nibble extraction order for IQ4_XS scales_l
- Needs compile-check loop: almost always needs 1-2 rounds of error feedback

BEST USE: Architecture design, algorithm sketching, Rust code, performance math.
AVOID: Trusting WGSL output without compile-check. Always run through conductor.sh.

CONDUCTOR PATTERN: dispatch → extract → cargo build → send errors back → retry (max 3 rounds)
""",
"research_log/model_grades.md", "gemma4_grade",
"model_grade,gemma4,fleet,conductor,lessons"),

# ── CORRECTOR CASCADE ────────────────────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: Corrector cascade for tool call fixing

When main model (35B) produces malformed tool call JSON, try correctors in order:
1. marvin-14b at 100.102.158.111:5555 (primary, full ChatML prompt, 600 tok)
2. picasso-tiny at 100.102.158.111:5571 (P1000 TinyLlama, minimal prompt, 200 tok)
3. laptop-tiny at 100.110.214.86:5571 (M2200 TinyLlama, minimal prompt, 200 tok)

Tiny model prompt (ultra-minimal, works with 1.1B):
  "Fix this JSON tool call. Output ONLY valid JSON, nothing else.
   Format: {\"name\": \"tool_name\", \"arguments\": {\"key\": \"value\"}}
   Tools: write_file, read_file, cargo_check, think_harder, remember, run_command
   Input: {stripped_content}
   Fixed JSON:"

Full model prompt (14B+, ChatML):
  <|im_start|>system
  You are a tool-call JSON fixer. Output ONLY the corrected JSON.
  Format: {"name": "tool_name", "arguments": {"key": "value"}}
  <|im_end|>
  <|im_start|>user
  Fix: {stripped_content}
  <|im_end|>
  <|im_start|>assistant

After getting response, use extract_json_from_text() to find the first { ... } block.
""",
"research_log/good_examples.md", "corrector_cascade",
"corrector,cascade,tool_call,json,good_example"),

# ── THINK HARDER PATTERN ─────────────────────────────────────────────────────
make_entry("""
GOOD EXAMPLE: Using think_harder for code debugging

When a worker produces buggy code, instead of just sending raw errors back,
route through the forge's think_harder tool which:
1. Queries nautivecs for relevant context (our corrections, llama.cpp source, etc.)
2. Queries WSO (web search oracle) for current docs
3. Returns combined context to prepend to the retry prompt

Pattern for conductor loop with think_harder:
  1. Worker produces code with errors
  2. Extract errors from cargo build
  3. Call forge /send with message:
     "think_harder about these WGSL compile errors: {errors}
      Then fix the code in {file_path}"
  4. Forge injects nautivecs context (our corrections) + web search results
  5. Worker gets enriched context and produces better fix

This is especially useful for WGSL bugs because our corrections DB now contains
the common patterns (sign extension, struct scope, async fn, etc.)
""",
"research_log/good_examples.md", "think_harder_pattern",
"think_harder,forge,nautivecs,conductor,good_example"),

]

# ── Write to store ────────────────────────────────────────────────────────────

print(f"Loading store ({STORE_PATH})...")
with open(STORE_PATH, 'r') as f:
    store = json.load(f)

print(f"Current entries: {len(store)}")

# Check for duplicates by content_hash
existing_hashes = {e.get('content_hash') for e in store}
new_entries = [e for e in ENTRIES if e['content_hash'] not in existing_hashes]

print(f"New entries to add: {len(new_entries)} (skipping {len(ENTRIES) - len(new_entries)} duplicates)")

store.extend(new_entries)

print(f"Writing store ({len(store)} total entries)...")
with open(STORE_PATH, 'w') as f:
    json.dump(store, f)

print(f"Done. Added {len(new_entries)} entries.")
print("Note: embeddings are zero — will be computed when P100s are free.")
print("Restart nautivecs to pick up new entries: kill $(pgrep nautivecs-cli) && ...")
