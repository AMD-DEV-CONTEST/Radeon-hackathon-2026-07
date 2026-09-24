# AMD ROCm benchmark

- GPU: AMD Radeon Graphics
- PyTorch: 2.9.1+rocm7.2.1.gitff65f5bc (HIP 7.2.53211-e1a6bc5663)
- CPU threads available to PyTorch: 64

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

Full DQN training with the default 256x256 policy. The environment runs on the CPU in every case, which is why the device barely matters.

| Parallel envs | CPU steps/s | ROCm steps/s | Speedup | GPU util |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 60 | 59 | 0.99x | 3% |
| 4 | 155 | 208 | 1.35x | 3% |
| 8 | 248 | 348 | 1.41x | 2% |
| 16 | 405 | 610 | 1.51x | 2% |
| 32 | 532 | 816 | 1.53x | 2% |
