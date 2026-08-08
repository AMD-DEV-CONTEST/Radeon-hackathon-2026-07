# Native Backend Scaffold

This folder is the future native acceleration layer for Screen-AI.

Current status:

```text
scaffold only
```

Why it exists:

- show the hackathon architecture is AMD-ready
- keep CUDA/HIP differences isolated in one shim
- avoid vendor-specific conditionals in algorithm code
- preserve CPU as the default runtime

Planned files:

```text
gpu_compat.h
screen_gpu_backend.cpp
screen_gpu_backend.cu
screen_gpu_backend.h
Makefile
```

Build idea:

```bash
make cpu
make cuda CUDA_ARCH=sm_80
make hip HIP_ARCH=gfx1201
```

For the first working hackathon demo, Python/OpenCV/ONNXRuntime remains the implementation path. This native layer is the roadmap for optimized ROCm/CUDA parity.

## SSD Tier Policy

`ssd_tier_policy.c` is a tiny C reference for the codiii-style hot-store decision:

```text
resident core + warm LFRU cache + SSD-cold artifacts
```

It chooses whether a hotter cold item should replace the weakest resident slot
using a frequency + recency score with hysteresis. The Python runtime currently
implements the live orchestration; this C policy is the native migration path for
low-overhead tier decisions.

## Endpoint Ranking

`endpoint_rank.c` mirrors the runtime click-target scoring policy in tiny C:

```text
text match + UIA confidence + sane bounds + source priority -> endpoint score
```

The Python `screen.click_text` tool remains the live implementation, while this
native module is ready for a DLL/shared-library path when the scanner loop needs
lower latency.
