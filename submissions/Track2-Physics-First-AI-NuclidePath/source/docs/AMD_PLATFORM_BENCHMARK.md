# AMD ROCm scientific platform benchmark

**Scope note:** this is the dated 28 July 2026 core-platform snapshot. It predates the multicomponent PHREEQC bridge merge; the **5 August 2026 post-merge rerun of `main` at head `b6d4c61e74`** (388 passed, 2 skipped; FP64 benchmark reproduced) is archived under `artifacts/amd-2026-08-05/post-merge/`.

## Verified environment

- Source physics revision: `5edb8ce24b690810efad703f7550650192598118`
- GPU: AMD Radeon Graphics, `gfx1100`, 96 reported compute units
- VRAM: 49,136 MB (`51,522,830,336` bytes in PyTorch)
- ROCm: `7.2.1`
- PyTorch: `2.9.1+rocm7.2.1.gitff65f5bc`
- HIP runtime reported by PyTorch: `7.2.53211-e1a6bc5663`
- Python: `3.12.3`
- Full GPU suite: **231 passed** on the final source snapshot (`b2f20aadad8559deeba738ff2273fe10c3b48e945615f8105540fdd3b7a9ebe5` SHA-256)

Raw evidence is under `artifacts/amd-2026-07-28/platform-current/` with `SHA256SUMS`.

## Exact primary GCS — end-to-end Python API

100,000 chemistry cases, seven repeats. This scope includes Python state/tensor construction and conversion of all Kd outputs back to host objects; the scalar reference also creates rich provenance-bearing result objects.

| dtype | Scalar median | ROCm batch median | Speedup | Max relative Kd error |
|---|---:|---:|---:|---:|
| FP64 | 0.60491 s | 0.12083 s | 5.01× | `4.44e-16` |
| FP32 | 0.60411 s | 0.12040 s | 5.02× | `4.09e-7` |

These timings are transfer/object dominated and are not kernel-only claims.

## Device-resident GCS kernel

2,048 chemistry scenarios, nine synchronized repetitions. Input and outputs remain GPU tensors; host construction and transfer are excluded.

| dtype | Median | Throughput | Max relative Kd error |
|---|---:|---:|---:|
| FP64 | 0.6008 ms | 3.41 million scenarios/s | `4.44e-16` |
| FP32 | 0.5757 ms | 3.56 million scenarios/s | `3.36e-7` |

## Device-resident GCS → transport → receptor pipeline

Workload: 2,048 chemistry scenarios × 6 receptors × 12 times = 147,456 concentration evaluations. The GPU path includes exact primary GCS, `L/kg → m³/kg`, retardation, reactive Ogata–Banks transport and decay. Input chemistry and outputs remain device resident. Scalar reference runs the same canonical GCS and transport formulas in Python.

| dtype | ROCm median | Throughput | Scalar reference | Speedup | Peak allocated GPU memory | Max relative concentration error |
|---|---:|---:|---:|---:|---:|---:|
| FP64 | 1.784 ms | 82.66 million eval/s | 0.2446 s | 137.09× | 13.73 MB | `7.94e-14` |
| FP32 | 1.466 ms | 100.61 million eval/s | 0.2447 s | 166.94× | 6.94 MB | `4.76e-5` |

FP64 is the canonical scientific parity path. FP32 is an explicitly lower-precision throughput mode; its measured error is reported rather than silently accepted as equivalent.

## Interpretation boundaries

- Kernel and device-resident pipeline timings exclude application-level JSON/report generation.
- End-to-end GCS API timings include host conversion and therefore show a lower speedup.
- The scalar and GPU paths were compared on identical deterministic scenario rows.
- These measurements apply to this GPU, software revision, dtype and workload; they are not vendor peak specifications.
- No HMC/NUTS performance claim is made because a validated Bayesian calibration workload and priors are not yet available.
