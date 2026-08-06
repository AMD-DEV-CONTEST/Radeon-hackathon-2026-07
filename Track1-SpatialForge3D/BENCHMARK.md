# SpatialForge 3D - Batch Benchmark

**Hardware:** AMD Radeon Graphics (gfx1100), 48 GB VRAM

**Stack:** ROCm 7.2.1, PyTorch 2.9.1+gitff65f5b, TripoSR

**Config:** mesh grid 256, foreground ratio 0.85, background removal on

**Model load (one-time):** 6572 ms

**Assets generated:** 14

## Per-asset results

| Asset | Preprocess | Inference (GPU) | Mesh (CPU) | Export | Total | Vertices | Peak VRAM |
|---|---|---|---|---|---|---|---|
| captured | 1102 ms | **1030 ms** | 1333 ms | 98 ms | 3563 ms | 42,998 | 2.39 GB |
| chair | 10 ms | **1389 ms** | 1317 ms | 83 ms | 2800 ms | 42,153 | 2.39 GB |
| flamingo | 11 ms | **1009 ms** | 1293 ms | 27 ms | 2340 ms | 23,008 | 2.39 GB |
| hamburger | 72 ms | **1006 ms** | 1313 ms | 89 ms | 2481 ms | 55,736 | 2.39 GB |
| horse | 74 ms | **1007 ms** | 1308 ms | 34 ms | 2424 ms | 45,172 | 2.39 GB |
| iso_house | 732 ms | **1025 ms** | 1354 ms | 78 ms | 3189 ms | 58,143 | 2.39 GB |
| marble | 522 ms | **1029 ms** | 1370 ms | 88 ms | 3008 ms | 69,167 | 2.39 GB |
| police_woman | 78 ms | **998 ms** | 1334 ms | 84 ms | 2494 ms | 76,872 | 2.39 GB |
| poly_fox | 524 ms | **1023 ms** | 1370 ms | 96 ms | 3015 ms | 56,779 | 2.39 GB |
| robot | 78 ms | **1005 ms** | 1338 ms | 78 ms | 2499 ms | 78,139 | 2.39 GB |
| stripes | 516 ms | **1086 ms** | 1323 ms | 64 ms | 2989 ms | 55,998 | 2.39 GB |
| teapot | 613 ms | **1074 ms** | 1316 ms | 33 ms | 3036 ms | 40,330 | 2.39 GB |
| tiger_girl | 649 ms | **1029 ms** | 1395 ms | 27 ms | 3100 ms | 22,772 | 2.39 GB |
| unicorn | 102 ms | **1005 ms** | 1296 ms | 89 ms | 2492 ms | 38,892 | 2.39 GB |

## Summary

- End-to-end: min 2340 ms, mean 2816 ms, max 3563 ms
- GPU inference: min 998 ms, mean 1051 ms, max 1389 ms
- Peak VRAM: mean 2.39 GB, max 2.39 GB of 48 GB (5.0% utilization)
- Throughput: 0.36 assets/sec sustained
