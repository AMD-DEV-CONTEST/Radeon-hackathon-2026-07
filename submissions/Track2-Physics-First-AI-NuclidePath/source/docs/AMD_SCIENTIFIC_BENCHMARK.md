# AMD ROCm scientific transport benchmark

**Scope note:** this is the dated 28 July 2026 core-platform snapshot. It predates the multicomponent PHREEQC bridge merge; the **5 August 2026 post-merge rerun of `main` at head `b6d4c61e74`** (388 passed, 2 skipped) is archived under `artifacts/amd-2026-08-05/post-merge/`.

## Scope

This benchmark exercises NuclidePath's actual reactive Ogata–Banks transport equation, not a generic matrix multiplication. The scalar Python implementation remains the canonical reference. The optional PyTorch backend evaluates matching distance/time pairs on CPU or ROCm and returns the same result contract.

The benchmark parameters are a declared software-demonstration case embedded in `scripts/amd_transport_benchmark.py`; they are not site measurements or regulatory inputs.

## Environment

- Date: 28 July 2026 UTC
- GPU: AMD Radeon Graphics, `gfx1100`, 49,136 MiB reported by llama.cpp
- ROCm: 7.2.1
- PyTorch: `2.9.1+rocm7.2.1.gitff65f5bc`
- HIP runtime reported by PyTorch: `7.2.53211-e1a6bc5663`
- Python: 3.12.3
- Repetitions: 5; table reports median end-to-end rate
- Timing includes tensor creation and device-to-host conversion for PyTorch paths

Command:

```bash
python scripts/amd_transport_benchmark.py \
  --output artifacts/transport-benchmark.json \
  --sizes 1 128 4096 65536 --repeats 5
```

## Measured results

| Batch | Scalar Python FP64 | PyTorch CPU FP64 | ROCm FP64 | ROCm FP32 |
|---:|---:|---:|---:|---:|
| 1 | 227,801 eval/s | 6,325 eval/s | 1,632 eval/s | 1,482 eval/s |
| 128 | 625,709 eval/s | 593,367 eval/s | 194,236 eval/s | 199,874 eval/s |
| 4,096 | 627,356 eval/s | 2,540,997 eval/s | 2,300,006 eval/s | 2,313,738 eval/s |
| 65,536 | 627,607 eval/s | 2,518,891 eval/s | **3,474,050 eval/s** | **3,678,419 eval/s** |

At batch 65,536, measured end-to-end speedups relative to the scalar reference were:

- PyTorch CPU FP64: **4.01×**
- ROCm FP64: **5.54×**
- ROCm FP32: **5.86×**

The GPU is slower for very small batches because launch, allocation, transfer, and Python conversion overhead dominate. This backend is intended for large parameter sweeps and uncertainty ensembles, not single evaluations.

## Numerical parity

| Backend | Maximum absolute error | Maximum relative error |
|---|---:|---:|
| PyTorch CPU FP64 | `3.49e-10` | `6.01e-15` |
| ROCm FP64 | `3.49e-10` | `6.01e-15` |
| ROCm FP32 | `1.35e-1 Bq/m³` | `2.93e-5` |

The explicit FP64 acceptance tolerance is maximum relative error `≤ 1e-12`, enforced by `scripts/amd_transport_benchmark.py` and consistent with the `2e-12` per-case relative tolerance in `tests/test_gpu_analysis.py`. The measured FP64 error passes this gate. FP32 uses a reporting threshold of `1e-4`; it is faster but remains an explicitly lower-precision benchmark path and must not silently replace FP64 or the canonical scalar solver.

## Reproducibility evidence

- `artifacts/amd-2026-07-28/scientific/transport-benchmark.json`
- `artifacts/amd-2026-07-28/validation-current/transport-benchmark.json`
- `scripts/amd_transport_benchmark.py`
- `scripts/amd_validation_run.sh`

The one-command validation script also runs the recorded AMD test gate, one offline workflow, one real local-LLM-planned workflow, deterministic physical parity, the transport benchmark, and environment metadata. These measurements demonstrate software execution and performance on the tested AMD endpoint; they do not constitute site-specific transport validation.
