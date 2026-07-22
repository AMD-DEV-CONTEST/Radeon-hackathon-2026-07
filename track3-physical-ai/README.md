# 1bit.systems — Track 3: Physical AI / Robotics Submission

## Submission Contents

| File | Description |
|------|-------------|
| [`TECHNICAL_REPORT.md`](./TECHNICAL_REPORT.md) | Technical report — architecture, AMD GPU utilization, benchmarks |

## Source Code

**https://github.com/bong-water-water-bong/1bit-systems**

Key modules:
- `engine/npu/` — XDNA 2 NPU engine (C++23, INT8 kernels)
- `engine/gpu/` — GPU backend (Zig, Vulkan/CUDA/Metal)
- `src/backend_vulkan.cpp` — Vulkan inference backend
- `kernels/` — HIP GPU kernels
- `tools/vision_server.cpp` — Vision inference server

## Build Instructions

```bash
git clone https://github.com/bong-water-water-bong/1bit-systems
cd 1bit-systems
cmake -B build -G Ninja
cmake --build build --target zaya_server -j8
```

Requires: Ubuntu 24.04, g++ (C++23), ROCm 7.14+, XRT, CMake, Ninja
