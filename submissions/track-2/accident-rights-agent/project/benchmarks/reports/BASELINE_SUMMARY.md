# Radeon Cloud Qwen3-VL Baseline

Recorded on 2026-07-28 (UTC+8) using one AMD Navi31 Radeon GPU.

## Fixed configuration

| Item | Value |
|---|---|
| Model | Qwen/Qwen3-VL-8B-Instruct |
| Model storage | `/persistent/models/Qwen3-VL-8B-Instruct` |
| Precision | BF16 |
| vLLM | `0.16.1.dev0+g89a77b108.d20260318` |
| ROCm | 7.2.1 |
| Context | 16,384 tokens |
| Prefix Cache | Disabled explicitly |
| Endpoint | `http://127.0.0.1:8000/v1` |
| Requests / concurrency | 20 / 1 |
| Maximum output | 192 tokens |
| Temperature | 0 |

## Result

| Metric | Result |
|---|---:|
| Success | 20 / 20 (100%) |
| Wall time | 57.11 s |
| Requests/s | 0.350 |
| TTFT mean | 85.9 ms |
| TTFT P50 / P95 | 87.4 / 87.9 ms |
| End-to-end mean | 2.86 s |
| End-to-end P50 / P95 | 2.82 / 2.97 s |
| Decode throughput mean | 27.46 token/s |
| GPU utilization mean / peak | 59.06% / 100% |
| Socket power mean / peak | 111.19 W / 175 W |
| Peak VRAM | 44,246 MB |
| Peak edge / hotspot temperature | 47°C / 56°C |
| OOM / failed requests | 0 / 0 |

## Evidence

- Machine-readable report:
  `baseline-20260728T035633Z-c1.json`
- Raw AMD SMI log:
  `artifacts/amd-smi-baseline-20260728T035630Z.log`
- vLLM baseline log:
  `artifacts/vllm-baseline.log`
- Local-only and listener verification:
  `artifacts/baseline-run-20260728T035630Z.log`

The `artifacts/` directory is ignored by Git by default because raw runtime logs
can be large. Keep only reviewed, non-sensitive evidence when publishing.
