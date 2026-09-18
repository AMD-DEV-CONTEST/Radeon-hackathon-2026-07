# Inference Optimization Report: float16 vs GPTQ-Int4

**Date**: 2026-08-03 · **Hardware**: AMD Radeon gfx1100 (Navi 31), 48 GB VRAM
**Stack**: ROCm 7.2.1 · PyTorch 2.9.1 · vLLM 0.16.1 (Triton Attention backend)

## Goal

Track 2 awards 20 points for targeted inference-speed optimization and up to
20 bonus points for quantization/distillation. This report is the reproducible
A/B evidence: the same Qwen2.5-7B-Instruct model served at float16 (baseline)
and GPTQ-Int4 (optimized), measured under identical conditions.

## Results (20 requests, max_tokens=128, identical prompt)

| Metric | float16 baseline | GPTQ-Int4 optimized | Change |
|---|---|---|---|
| **p50 latency** | 3.45 s | **1.01 s** | **↓ 70%** |
| **p95 latency** | 3.70 s | **1.21 s** | **↓ 67%** |
| **Throughput** | 29.2 tok/s | **95.6 tok/s** | **↑ 227%** |
| Model size in VRAM | 14.37 GiB | **5.44 GiB** | ↓ 62% |
| Model load time | 7.2 s | **4.1 s** | ↓ 43% |
| Available KV cache | 26.87 GiB / 503,120 tok | **35.84 GiB / 671,152 tok** | ↑ 33% |
| Peak VRAM | 47.3 GB (91%) | 47.6 GB (92%) | ≈ flat |

## Why this is a real optimization (not just a smaller model)

GPTQ-Int4 quantizes the model weights from 16-bit to 4-bit. This produces
**two independent gains**:

1. **Compute**: 4-bit weights are dequantized through optimized GPTQ kernels,
   and the smaller memory footprint means less bandwidth pressure per token —
   directly raising decode throughput from 29 → 96 tok/s.
2. **Capacity**: the 9 GiB freed in VRAM (14.37 → 5.44) is reallocated to the
   KV cache, raising the token budget from 503K → 671K (+33%). This means more
   concurrent sessions or longer context before OOM — directly relevant to the
   incident-response agent's multi-turn case memory.

Peak VRAM is flat because `gpu-memory-utilization=0.90` reserves the same
fraction regardless; the benefit shows up as larger KV cache, not lower total
usage.

## Reproduction

```bash
# Baseline (float16)
python -m vllm.entrypoints.openai.api_server \
  --model <Qwen2.5-7B-Instruct> \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.90 --max-model-len 8192 --dtype float16

# Optimized (GPTQ-Int4)
python -m vllm.entrypoints.openai.api_server \
  --model <Qwen2.5-7B-Instruct-GPTQ-Int4> \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.90 --max-model-len 8192 \
  --quantization gptq --dtype float16

# Benchmark (identical for both)
python scripts/rocm_capture.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model <served-name> --runs 20
```

## Quality trade-off (measured, not assumed)

GPTQ-Int4 is a lossy quantization, so the speed gain is only valuable if
diagnostic quality holds. Both variants were evaluated on the same 20-run
benchmark capture using four offline quality signals computed over the
recorded model outputs (`python scripts/quality_eval.py`).

| Quality metric | float16 | GPTQ-Int4 | Delta |
|---|---:|---:|---:|
| Root-cause hit rate | 100% | 100% | 0 pp |
| Structure conformance (Diagnosis heading) | 100% | 100% | 0 pp |
| Completion tokens (mean) | 102.0 | 98.4 | -3.6 |
| Completion tokens (std) | 3.1 | 5.2 | +2.1 |
| Lexical consistency (top-prefix ratio) | 100% | 65% | -35 pp |

**Result: no semantic regression.** Every Int4 run still names a valid
root-cause family (recent changes, configuration, bottleneck, resource
contention) and preserves the mandated `Diagnosis` heading — root-cause hit
rate and structure conformance are identical to float16 at 100%. The only
observable difference is surface-level: float16 repeats near-identical
wording on every repetition, while Int4 varies the phrasing of the diagnosis
("performance issues" vs "bottlenecks or increased load") while pointing at
the same root cause. For a human-in-the-loop SRE co-pilot this variation is
acceptable — the reviewer still receives the correct diagnosis and the same
approval gate.

## Evidence

- `docs/evidence/rocm-baseline.json` — float16, 20 runs
- `docs/evidence/rocm-int4.json` — GPTQ-Int4, 20 runs
- `docs/evidence/quality-eval.json` — offline quality evaluation output
- `docs/evidence/vllm-startup.log` — float16 startup (model load, KV cache)
- `docs/evidence/vllm-int4-startup.log` — Int4 startup (model load, KV cache)
