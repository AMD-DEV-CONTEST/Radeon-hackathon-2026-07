# ChronoSafe-Drive AMD ROCm Inference Benchmark

This benchmark uses frozen, held-out nuScenes temporal sequences. Timings cover device-resident model forward inference; dataset loading and host-to-device transfer are excluded.

## Environment

- GPU: AMD Radeon Graphics (gfx1100)
- ROCm/HIP: 7.2.53211-e1a6bc5663
- PyTorch: 2.9.1+rocm7.2.1.gitff65f5bc
- VRAM: 47.984 GiB
- Test sequences available: 30,142
- Model parameters: 56,968

## Latency and throughput

| Precision | Batch | p50 (ms) | p95 (ms) | p99 (ms) | Throughput (seq/s) | Peak allocated (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| fp32 | 1 | 0.558821 | 0.954580 | 1.019299 | 1,632.89 | 77.312 |
| fp32 | 32 | 0.571206 | 0.974368 | 1.056337 | 51,199.80 | 77.794 |
| fp32 | 256 | 0.636986 | 1.010295 | 1.078844 | 367,947.68 | 82.494 |
| fp32 | 1024 | 0.714952 | 1.003659 | 1.064934 | 1,371,235.75 | 98.604 |
| amp_fp16 | 1 | 0.657712 | 1.008337 | 1.140324 | 1,409.41 | 77.218 |
| amp_fp16 | 32 | 0.676867 | 1.070611 | 1.165203 | 43,672.76 | 77.483 |
| amp_fp16 | 256 | 0.682081 | 1.076404 | 1.187585 | 345,590.48 | 79.994 |
| amp_fp16 | 1024 | 0.694567 | 1.086294 | 1.201812 | 1,364,850.70 | 88.600 |

## FP32 versus AMP numerical verification

- Samples: 8,192
- Joint camera/LiDAR/delay classification agreement: 100.000000%
- Risk mean absolute error: 0.00008262
- Risk maximum absolute error: 0.00064528
- Verification: PASS

## AMP speedup over FP32

| Batch | p50 latency speedup | Throughput speedup |
|---:|---:|---:|
| 1 | 0.850x | 0.863x |
| 32 | 0.844x | 0.853x |
| 256 | 0.934x | 0.939x |
| 1024 | 1.029x | 0.995x |
