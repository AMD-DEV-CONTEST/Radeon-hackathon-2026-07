# AMD ROCm benchmark

- GPU: AMD Radeon Graphics
- PyTorch: 2.9.1+rocm7.2.1.gitff65f5bc (HIP 7.2.53211-e1a6bc5663)
- CPU threads available: 64

## Summary

- The optimiser step alone runs up to **41x faster** on ROCm than on the CPU.
- End-to-end training still tops out at **1.05x** against a tuned CPU, because the HighwayEnv simulation dominates wall-clock time.
- GPU utilisation during real training stays under 3% and peak VRAM is about 110 MB, so the accelerator is idle almost the whole run.
- Running many small training jobs concurrently on one GPU is actively harmful: nine parallel jobs collapsed to 85 steps/s in aggregate versus 650 steps/s on CPU, because the tiny kernels serialise on a single HIP context.
- ROCm becomes worthwhile as soon as the policy grows (image observations, wider networks, larger batches); the gradient table below quantifies the headroom.

## Gradient-step throughput (optimiser only)

Environment simulation is excluded, so this isolates the part of the workload a GPU can accelerate. Speedup above 1.0 means ROCm wins.

| Network | Params | Batch | CPU steps/s | ROCm steps/s | Speedup | GPU util | Peak VRAM |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 64x64 | 12,298 | 64 | 159 | 737 | **4.64x** | 37% | 108 MB |
| 64x64 | 12,298 | 512 | 87 | 742 | **8.56x** | 38% | 109 MB |
| 64x64 | 12,298 | 4096 | 47 | 607 | **12.82x** | 46% | 113 MB |
| 256x256 | 147,466 | 64 | 108 | 725 | **6.70x** | 41% | 110 MB |
| 256x256 | 147,466 | 512 | 62 | 684 | **10.99x** | 47% | 111 MB |
| 256x256 | 147,466 | 4096 | 27 | 522 | **18.97x** | 60% | 130 MB |
| 1024x1024 | 2,162,698 | 64 | 48 | 710 | **14.86x** | 44% | 133 MB |
| 1024x1024 | 2,162,698 | 512 | 31 | 513 | **16.56x** | 56% | 135 MB |
| 1024x1024 | 2,162,698 | 4096 | 5 | 115 | **23.44x** | 88% | 209 MB |
| 2048x2048 | 8,519,690 | 64 | 15 | 625 | **41.15x** | 56% | 206 MB |
| 2048x2048 | 8,519,690 | 512 | 14 | 245 | **17.11x** | 81% | 206 MB |
| 2048x2048 | 8,519,690 | 4096 | 2 | 33 | **14.63x** | 91% | 350 MB |

## End-to-end training throughput

Full DQN training with the default 256x256 policy. The CPU column that matters is the tuned one (`OMP_NUM_THREADS=1`); with the default 64 threads the CPU baseline loses 25-35% to thread synchronisation on batch-64 updates.

| Parallel envs | CPU 64 threads | CPU 1 thread (tuned) | ROCm | ROCm vs tuned CPU | GPU util |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 60 | **60** | 59 | 0.97x | 3% |
| 4 | 155 | **218** | 208 | 0.96x | 3% |
| 8 | 248 | **330** | 348 | 1.05x | 2% |
| 16 | 405 | **604** | 610 | 1.01x | 2% |
| 32 | 532 | **795** | 816 | 1.03x | 2% |
