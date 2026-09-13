# Aegis GPU Benchmark Report

> **This is a template.** Run `python benchmarks/benchmark_inference.py --concurrency 1 4 8 16`
> against a live vLLM/ROCm server (see `docs/ROCM_SETUP.md`) and paste the generated
> `benchmarks/results/<timestamp>.json` numbers in below before submitting. Numbers
> generated on a non-AMD host are not valid for the AMD DevMaster judging criteria —
> the script itself will report `gpu_metrics_available: false` if run without ROCm.

## Test environment

| | |
|---|---|
| GPU | *(e.g. AMD Radeon RX 7900 XTX, 24GB)* |
| ROCm version | *(e.g. 6.1)* |
| Model | *(e.g. Qwen2.5-14B-Instruct, fp16)* |
| vLLM flags | `--dtype float16 --gpu-memory-utilization 0.90 --max-num-seqs 32 --enable-prefix-caching` |
| Host CPU/RAM | *(fill in)* |

## Results

| Concurrency | Aggregate tok/s | p50 latency (ms) | p95 latency (ms) | GPU util % | VRAM used % |
|---|---|---|---|---|---|
| 1 | | | | | |
| 4 | | | | | |
| 8 | | | | | |
| 16 | | | | | |

## Multi-agent workflow timing

Run a full incident investigation (`POST /api/v1/incidents`) and record from the
`AgentRun.total_duration_ms` field and individual `AgentStep.duration_ms` /
`tokens_per_second` values (visible in the frontend's agent trace timeline or via
`GET /api/v1/incidents/{id}`):

| Agent | Typical duration (ms) | Typical tok/s |
|---|---|---|
| planner | | |
| log_analyst | | |
| metrics_analyst | | |
| deploy_correlator | | |
| runbook_retriever | | |
| synthesizer | | |
| remediation | | |
| **Total wall-clock (parallel investigators)** | | — |

## RAG / embedding latency

| Operation | Latency (ms) |
|---|---|
| Single-chunk embedding | |
| Runbook search (top_k=5) | |

## Notes / analysis

*(Fill in: does tokens/sec scale sub-linearly with concurrency as expected from
batching? Where does GPU utilization saturate? Any VRAM pressure at concurrency=16?)*
