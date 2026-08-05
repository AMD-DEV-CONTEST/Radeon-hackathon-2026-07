# XiangLens Radeon Benchmark Result

- Generated: `2026-08-05T13:13:04.579640+00:00`
- Runtime: `llama.cpp llama-server on AMD ROCm`
- GPU: `AMD Radeon PRO W7900`
- ROCm: `Runtime Version: 1.18`
- llama.cpp: `da5b448622ce8f8265bed15a7f80c5cf17894511`
- Model: `mradermacher/Qwen3.6-35B-A3B-Fable-5-Distill-i1-GGUF:Q6_K`
- Endpoint: `http://127.0.0.1:8000/v1`
- Workload: `multimodal`

## Median Results

| Metric | Median |
|---|---:|
| Time to first generated delta | 825.58 ms |
| Time to first final-content delta | 10728.70 ms |
| End-to-end model latency | 12694.04 ms |
| Prompt processing | 450.64 tok/s |
| Token generation | 83.16 tok/s |
| Valid structured JSON | 100.0% |

## Method

- Warmups excluded: `0`
- Measured runs: `1`
- Temperature: `0.0`
- Final-content budget: `384` tokens
- Reasoning budget: `2048` tokens
- Raw model content and chain-of-thought were not written to the result file.
- Peak VRAM and GPU utilization must be captured separately with ROCm tooling.
