# XiangLens Radeon Benchmark Result

- Generated: `2026-08-05T13:11:56.652022+00:00`
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
| Time to first generated delta | 87.09 ms |
| Time to first final-content delta | 9960.18 ms |
| End-to-end model latency | 11919.78 ms |
| Prompt processing | 60.31 tok/s |
| Token generation | 83.42 tok/s |
| Valid structured JSON | 100.0% |

## Method

- Warmups excluded: `1`
- Measured runs: `5`
- Temperature: `0.0`
- Final-content budget: `384` tokens
- Reasoning budget: `2048` tokens
- Raw model content and chain-of-thought were not written to the result file.
- Peak VRAM and GPU utilization must be captured separately with ROCm tooling.
