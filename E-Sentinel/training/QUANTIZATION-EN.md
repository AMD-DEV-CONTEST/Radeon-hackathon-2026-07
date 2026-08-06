# E-Sentinel Quantization Comparison Plan (#170)

> Status: **Both LoRA rounds were rejected by the quality gate; the production base model remains Stock Qwen3-8B.**
> This report compares **Stock FP16** vs **Stock GPTQ-Int4**.
> GPTQ is approved only for the Agent primary path; the Dual path retains FP16 due to quality degradation (see the Section 5 boundary).
> Research date: 2026-08-04 (based on vLLM docs + vLLM ROCm-related PRs)
> Measurement date: 2026-08-04 · Evidence file: `evals/results/quantization-gptq-20260804.json`

## 1. ROCm gfx1100 quantization support (version-specific, confirmed by in-house measurement)

| Quantization method | gfx1100 status | Evidence |
|---|---|---|
| **GPTQ (W4A16)** | ✅ RDNA3-specific dense W4A16 kernel (gfx1100, FP16/BF16) | vLLM `q_gemm_rdna3.cu` + **in-house measurement in this project** (successful load + end-to-end benchmark) |
| **AWQ (W4A16)** | ⚠️ Native HIP implementation exists only for **MoE** kernels (PR #44075, measured on RX 7900 XTX); **Qwen3-8B is a dense model, so MoE kernel support cannot be extrapolated to the availability of dense AWQ** | vLLM PR #44075 |
| bitsandbytes 8-bit | ❌ Compatibility table marks AMD as unsupported | vLLM supported_hardware table |
| FP8 / GGUF | ⚠️ Marked as supported in the table, but gfx1100 in practice prefers W4A16 | — |

**Version-specific boundary (important)**:

> vLLM 0.26's **RDNA3-specific W4A16 path** supports running GPTQ on gfx1100, and this project verified this through a successful load and an end-to-end benchmark. However, this **cannot be generalized** to all AMD GPUs or all vLLM GPTQ configurations — the vLLM general quantization compatibility table still marks GPTQ/AWQ on AMD GPUs as unsupported; this path is a version-specific, architecture-specific verification result.

**Route**: Primary route **GPTQ W4A16** (verified in-house); bitsandbytes is not used; **AWQ is not used as a fallback route** (insufficient evidence of dense support, see above).

## 2. Original plan vs. actual execution boundary

The original plan was a four-quadrant matrix of stock/tuned × FP16/quantized:

| Quadrant | Model | Precision | Actual execution |
|---|---|---|---|
| Q1 | Stock Qwen3-8B | FP16 | ✅ Deployed (`/workspace/Qwen3-8B`), baseline of this report |
| Q2 | Stock Qwen3-8B | GPTQ-Int4 | ✅ Measured in-house (`JunHowie/Qwen3-8B-GPTQ-Int4`) |
| Q3 | Tuned Qwen3-8B | FP16 | ❌ **Not executed** — both LoRA rounds rejected by the quality gate, production retains Stock (`FAILED-TUNED-LOG-EN.md`) |
| Q4 | Tuned Qwen3-8B | GPTQ-Int4 | ❌ **Not executed** — Q3 does not exist, so there are no tuned weights to quantize; AutoGPTQ build also failed on ROCm (toolchain limitation) |

**Honest boundary**: Q3/Q4 do not exist because the LoRA was rejected; no tuned quantization figures are fabricated. This report compares only **Q1 vs Q2** (Stock FP16 vs Stock GPTQ-Int4).

## 3. Implementation and verification record

1. **Q2 weight source**: `JunHowie/Qwen3-8B-GPTQ-Int4` (HF via hf-mirror), quant_method=gptq, bits=4, group=128, desc_act=false.
   (ModelScope `hiruyun/gptq-Qwen3-8B` is MThreads format `mudnn:true`; vLLM ROCm failed to load it — documented, switched to standard GPTQ.)
2. **Quality gate**: frozen human-gold 105 cases, local vLLM, agent (primary path) + dual (pure LLM) dual variants.
3. **Performance gate**: `scripts/bench-latency.mjs` (same script, same prompt, max_tokens=200, FP16 and GPTQ compared one-to-one).
4. **Metrics**: F1 / Severe Recall / FPR / κ + output tok/s / req/s + model-weight size.

## 4. Acceptance thresholds (go/no-go)

- Quantized F1 drop ≤ 0.01; Severe Recall drop ≤ 0.02
- **Model-weight size reduction ≥ 30%, or throughput improvement ≥ 15%** (meeting either is sufficient; model-weight size is the disk/loading size, **not equivalent to peak GPU VRAM** — peak VRAM was not separately measured with rocm-smi, stated honestly)
- All models use the same prompt / temperature / seed / gold checksum / baseline snapshot

## 5. Measured acceptance results (2026-08-04)

**Quality gate (frozen human-gold 105 cases, local)**:

| Variant | FP16 | GPTQ | Verdict |
|---|---|---|---|
| agent Recall / F1 / FPR / κ | 0.921 / 0.823 / 0.476 / 0.457 | 0.905 / 0.844 / 0.357 / 0.481 | **PASS** (Recall −0.016 ≤ 0.02, F1/κ rose) |
| dual Recall / F1 | 0.508 / 0.660 | 0.254 / 0.400 | **FAIL** (Recall −0.254) |

> **dual boundary (honest)**: This GPTQ weight significantly degrades the **Dual configuration as measured**. This is an observation of a single checkpoint under a single configuration and does not imply that "all pure-LLM or all quantized models are sensitive" — but it is sufficient to show that the Dual path should not use GPTQ by default.

**Performance gate (`scripts/bench-latency.mjs`, same script and same prompt)**:

| Metric | FP16 | GPTQ | Change |
|---|---|---|---|
| Model-weight size | 16GB | 5.7GB | **−64%** |
| Concurrency 1 output tok/s | 34 | 55 | **+62%** |
| Concurrency 8 output tok/s | 133 | 238 | **+79%** |
| Concurrency 1 single-request end-to-end latency (incl. generation) | 5891ms | 2345ms | **−60%** |

> **Benchmark method boundary (must be known)**:
> - **No warm-up**; only **1 request** is sent per concurrency level (not repeated and averaged); values are **single observations**.
> - The "5891→2345ms" above is actually **single-request end-to-end total latency** (including generating 200 tokens), **not first-token latency (TTFT)**. The actual TTFT sampled in vllm bench is ~74ms (`benchmarks/amd/summary.json`), but that data was collected for FP16 only and was not collected for GPTQ.
> - `max_tokens=200` is fixed, but the two groups' **actual output token counts were not recorded separately**; the differences between req/s and tok/s may partly result from differences in output length and **cannot be fully attributed to kernel speed improvements**.
> - The relative changes (−64% / +62% / +79% / −60%) are valid within the **same-script, same-prompt** FP16↔GPTQ comparison; the absolute values **cannot be directly compared** with vllm bench's random 2048/384 dataset (~175 tok/s) (different script, different input lengths).

**Conclusion**: Performance gate passed (model-weight size −64% ≥ 30%, throughput +62~79% ≥ 15%). Quality gate: **agent primary path PASS** (the deterministic tool layer compensates for the quantization loss), **dual degradation honestly recorded as a boundary**. GPTQ can be reported as an agent deployment optimization, but the benefit statement is limited to "model-weight size and throughput", and the single-measurement and method boundaries are disclosed.

## 6. References

- vLLM Quantization docs (general compatibility table; GPTQ/AWQ still marked as unsupported on AMD GPUs): https://docs.vllm.ai/en/latest/features/quantization/
- vLLM RDNA3 W4A16 dense kernel (gfx1100): https://github.com/vllm-project/vllm/pull/46186
- vLLM RDNA3 W4A16 kernel API docs: https://docs.vllm.ai/en/latest/api/vllm/model_executor/kernels/linear/mixed_precision/rdna3_w4a16/
- vLLM ROCm MoE W4A16 (gfx1100, not generalizable to dense): https://app.semanticdiff.com/gh/vllm-project/vllm/pull/44075/overview
- vLLM Supported Hardware: https://docs.vllm.ai/en/v0.15.0/features/quantization/
