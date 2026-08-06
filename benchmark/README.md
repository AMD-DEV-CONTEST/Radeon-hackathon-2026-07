# Benchmark

`rocm_perf.py` benchmarks SmolVLA inference latency / FPS / GPU memory on CPU vs
the AMD ROCm GPU and writes `results.json` here.

```bash
python benchmark/rocm_perf.py \
    --checkpoint outputs/train/smolvla_cube_pick/checkpoints/last/pretrained_model \
    --repo-id so101/cube_pick --dataset-root datasets/cube_pick \
    --devices cpu cuda --iters 50 --warmup 10
```

`results.json` is gitignored (regenerate on the Radeon machine). Example shape:

```json
{
  "results": [
    {"device": "cpu",  "latency_ms_mean": 812.4, "fps": 1.2,  "gpu_mem_mb": null},
    {"device": "cuda", "latency_ms_mean": 28.7,  "fps": 34.8, "gpu_mem_mb": 1930,
     "gpu_name": "AMD Radeon AI PRO R9700", "torch_hip": "7.2.1"}
  ]
}
```
