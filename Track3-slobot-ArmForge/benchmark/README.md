# Benchmark snapshot

`key_action_bench_compare.json` is a development throughput comparison for multi-env key-action episode replay with pose jitter.

- Local rows: AMD Ryzen CPU + Genesis CPU backend
- HF rows: Hugging Face Jobs `a10g-small` (NVIDIA A10G) + Genesis CUDA

For contest AMD Radeon / ROCm evidence, re-run on GPU hardware:

```bash
python armforge/benchmark_key_action.py --backend amdgpu -B 8
```
