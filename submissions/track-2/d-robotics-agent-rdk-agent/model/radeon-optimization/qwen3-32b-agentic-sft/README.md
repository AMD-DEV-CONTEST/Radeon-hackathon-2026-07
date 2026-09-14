# Qwen3-32B-Agentic-SFT Inference Optimization on AMD Radeon (gfx1100)

## 1. Purpose

Optimize the inference of the competition's **main 32B agent model** on the
Radeon serving machine, with a real A/B benchmark against the unmodified
production inference path, and without changing the model identity or hurting
tool-calling quality.

## 2. Model identity

| Field | Value |
|---|---|
| Alias | `Qwen3-32B-Agentic-SFT-r1-v3` |
| Base | `unsloth/Qwen3-32B-bnb-4bit` @ `7f721e74a6a8cc9ee352f7e49303a2c1705f9083` |
| Adapter | `checkpoint-000119`, `adapter_model.safetensors` SHA-256 `4dcee6914e3f9c61aeb33529208bf7e63f37c4c5ae5e0e37e7f7c6b3bfff20bf` |

`benchmark.py` verifies the base `config.json`, the adapter SHA-256 and the
frozen test-set SHA-256 **fail-closed** before every run.

## 3. Environment (measured on the real machine)

Host `u-7701-ae3eba8a`, AMD Radeon gfx1100 (48 GB VRAM), ROCm 7.2.1,
Python 3.12.3, torch 2.9.1+rocm7.2.0, transformers 5.5.0, peft 0.19.1,
bitsandbytes 0.50.0 (native ROCm kernels confirmed loaded), accelerate 1.14.0.
Production stack: bnb NF4 4-bit base + PEFT online LoRA served by
`model/model/serving/qwen3_agentic_openai_server.py`.

## 4. Bottleneck found on the real machine

Measured through the live production server and direct probes:

- **Decode ~8.7 tok/s** at GPU util 99% (short prompt); ~6.5 tok/s at
  production prompt lengths (3-6k tokens).  Prior identity probes (same
  outputs, base vs SFT service) show the **online LoRA path amplifies
  latency 1.55-1.9x** over the bare 4-bit base.
- **Prefill ~450 tok/s** -> 6k-token production prompts cost ~13 s before the
  first token exists.
- **The production server does not actually stream**: it generates the full
  completion, then chunks it into SSE.  User-visible TTFT therefore equals
  the full end-to-end latency (observed 16-60 s per request).

## 5. Candidate optimizations considered

All candidates were evaluated against primary sources and then **measured on
the real machine** (canary runs) before acceptance:

| Candidate | Real-machine result | Decision |
|---|---|---|
| Merge LoRA into NF4 base (`peft merge_and_unload`) | E2E x1.72, **but the model degenerates to near-base behavior**: the LoRA delta (norm ~0.3/projection) is far below the NF4 quantization step; the applied weight change has cosine ~0.006 with the intended delta.  Tool-call exactness dropped 1.0 -> 0.5 on canary. | **Rejected** (destroys the SFT) |
| `torch.compile` (reduce-overhead / inductor) + StaticCache | +35-40% decode on a ~900-token canary prompt, **but padded static-cache attention cost grows with cache length** (11.7 tok/s @ ~900 KV slots -> 6.5 @ 4608 -> 3.6 @ 12288); at real 3-6k prompts it is *slower* than eager, and each new cache length recompiles for 60-120 s. | **Rejected** (slower at production lengths) |
| Cast fp32 LoRA adapters to bf16 only | Token-identical output, no measurable speedup alone | Superseded by lean LoRA |
| **Lean LoRA execution** (minimal forward: `base(x) + (x@A^T)@(s*B)^T`, adapters bf16, scaling folded) | +3-4% decode, **token-identical** output on canary | **Accepted** |
| **True token streaming** (`TextIteratorStreamer`) | First token reaches the consumer right after prefill; no numerics change | **Accepted** |
| vLLM / llama.cpp engine swap | vLLM ROCm does not support bitsandbytes quantization and gfx1100 is not a supported quantized path; converting the quant format would change the frozen base identity | Rejected without implementation |
| Prompt/tool-schema reduction | Changes model inputs -> breaks A/B comparability and risks tool-calling | Rejected |

## 6. Why the final optimization was selected

The two accepted changes attack the two bottlenecks that survived
falsification on the real machine, are tiny and reversible, provably preserve
tool-calling (lean LoRA is canary-token-identical; gates re-verify on the
full run), and honestly classify as:

- **User-visible streaming/TTFT optimization** - true streaming.
- **Runtime optimization (small)** - lean LoRA decode path.

The two big-ceiling candidates (merge, compile+static-cache) were implemented
and measured first, and rejected **on evidence**; the numbers are preserved
above and in `results.json.boundaries`.

## 7. What the code does

- `runtime.py` - loads the frozen base + adapter and exposes
  `Runtime(model, adapter, arm).generate(...)`.
  - `arm="baseline"`: byte-for-byte replica of the production inference path
    (bnb NF4 + PEFT online LoRA, SDPA, fp32 RMSNorm, bf16 autocast, greedy).
  - `arm="optimized"`: same weights and math, plus `apply_lean_lora()`
    (runtime.py:102-121, enabled at :163) and real token streaming
    (runtime.py:192-221).
  - Both arms measure TTFT with the same streamer instrument; the baseline's
    *user-visible* TTFT is its e2e latency because the production server
    buffers before streaming (runtime.py:255).
- `benchmark.py` - single judge entry point.  Verifies identities
  fail-closed, deterministically selects a representative subset of the
  frozen held-out test set (`select_tasks()`: first task of every category +
  second task of the 4 largest categories -> 14 tasks / 44 assistant turns,
  covering single & multi tool-call turns, tool names/arguments, final text
  answers, live diagnostics and controlled actuation), replays each assistant
  turn (temperature=0, max_tokens=2048, same scoring rules as
  `model/benchmark/eval_ab.py`), 2 warmup records + 2 measured passes per
  arm, each arm in a fresh subprocess, and writes `results.json`.
- `results.json` - auto-generated on the Radeon machine by `benchmark.py`
  (never hand-edited).

No production source files were modified; the production server was only
stopped during the benchmark to free the GPU and restarted afterwards
(`deployments/.../runtime/start_qwen3_agentic_openai.sh`).  The optimization
is therefore **validated but not yet wired into the live serving path**.

## 8. One-command reproduction

On the Radeon host (production server stopped so the GPU is free):

```bash
cd /workspace/radeon-optimization/qwen3-32b-agentic-sft
/workspace/qwen36-agentic-sft/.venv/bin/python benchmark.py --run-dir run-full
# quick compatibility check instead: add --canary  (2 tasks, 1 pass)
```

`results.json` appears in the run dir.  Code SHA-256s are embedded in
`results.json.code_sha256` and must match this repo's files.

## 9. Baseline vs Optimized results (full run, Radeon gfx1100)

Run `radeon-ab-20260806T065217Z` (2026-08-06, UTC), 14 tasks / 44 assistant
turns / 2 measured passes = 88 trials per arm, temperature=0, 0 failures.

| Metric | Baseline (production path) | Optimized | Change |
|---|---|---|---|
| **User-visible TTFT p50** | 17.41 s | **8.26 s** | **2.11x faster** |
| **User-visible TTFT p95** | 83.97 s | **12.89 s** | **6.52x faster** |
| E2E latency p50 | 17.41 s | 16.87 s | 1.03x |
| E2E latency p95 | 83.97 s | 81.90 s | 1.03x |
| E2E latency mean | 32.43 s | 31.52 s | 1.03x |
| Decode tokens/s p50 | 6.54 | 6.72 | +2.8% |
| Prompt tokens (total) | 387,274 | 387,274 | identical inputs |
| Completion tokens (total) | 12,532 | 12,532 | identical outputs |
| Peak GPU VRAM | 27.99 GB | 28.06 GB | ~same |
| Failures / timeouts / truncations | 0 / 0 / 0 | 0 / 0 / 0 | - |

The internal first-token latency of the baseline is 8.57 s (p50) - the
production server already pays the prefill, then withholds all tokens until
generation ends.  Streaming makes that first token *visible*, which is why
the user-visible TTFT gain is honest to classify as a streaming/TTFT
optimization rather than a kernel speedup; the +2.8% decode is the (small)
runtime component from lean LoRA.

## 10. Quality preservation

Scoring reuses the frozen exact-match contract of the existing A/B evaluation
(tool name/arguments/count/finish-reason exactness, final-answer cleanliness).
Gates required for acceptance (all enforced in `benchmark.py`):
tool names not worse, tool arguments/calls within 2 pp, no new truncation,
final answers clean, zero failures.

Full-run outcome: **all 88 optimized outputs are byte-identical to the
baseline outputs** (output agreement 88/88 = 1.0), so every quality metric is
exactly equal between arms - tool-name exactness 0.700, tool-argument
exactness 0.667, tool-calls exactness 0.667 (the model's inherent score
against the frozen references), final answers clean 28/28, no truncation,
no failures.  All gates passed.

## 11. Limitations

- Single-request (batch=1) path; no concurrent-load numbers.
- Lean LoRA computes the adapter matmuls in bf16 (production uses fp32);
  canary-token-identical, full-run drift bounded by the output-agreement
  metric and quality gates in `results.json`.
- Decode throughput itself improves only ~2.8%; the large user-visible TTFT
  gain comes from streaming during generation, not from faster kernels - it
  is classified accordingly.
- Absolute tool-call exactness (0.667) is the model's own score against the
  frozen references and is **not** affected by this optimization (both arms
  produced identical outputs); this work does not claim any accuracy gain.
- The optimization is proven in this benchmark runtime; wiring it into
  `qwen3_agentic_openai_server.py` is a separate, not-yet-done step.
- Results are specific to gfx1100 + ROCm 7.2.1 + torch 2.9.1 + transformers
  5.5.0 + bitsandbytes 0.50.0.
- Subset replay (14 of 113 frozen tasks), selection deterministic and
  metadata-driven (`select_tasks()`).

## References (primary sources)

- PEFT merge-into-4bit rounding caveat: https://github.com/huggingface/peft/issues/2321
- bitsandbytes ROCm installation/support: https://huggingface.co/docs/bitsandbytes/main/en/installation
- PyTorch SDPA / AOTriton on ROCm (gfx1100): https://github.com/ROCm/aotriton and https://rocm.docs.amd.com/en/docs-7.1.1/how-to/rocm-for-ai/inference-optimization/model-acceleration-libraries.html
- torch.compile cudagraphs static-cache interaction: https://pytorch.org/docs/stable/torch.compiler_cudagraph_trees.html
- Transformers generation / streaming: https://huggingface.co/docs/transformers/main/en/generation_strategies
- vLLM ROCm support matrix: https://docs.vllm.ai/en/latest/getting_started/installation/gpu.html#amd-rocm
