# PolicyCut — Radeon Benchmark Notes

This document only ever publishes **real measurements** produced by
`scripts/benchmark.py` on the target machine (AMD Radeon PRO W7900, ROCm PyTorch
build). Raw JSON for every run is committed under `artifacts/benchmarks/`. GPU
timings are bracketed by `torch.cuda.synchronize()`; peak VRAM is
`torch.cuda.max_memory_allocated()` reset per stage. Nothing in this file is
estimated or extrapolated — sections below stay marked "pending" until the
corresponding run has actually been executed on the Radeon hardware.

## How to reproduce

```bash
source venv/bin/activate
python scripts/preflight.py                # environment + GPU smoke test
python scripts/make_fixtures.py            # synthetic clips (all PII fake)
python scripts/benchmark.py tests/fixtures/interview.mp4 \
    --policy "Pixelate every face and screen. Beep phone numbers." \
    --precision fp16
python scripts/benchmark.py tests/fixtures/interview.mp4 --precision fp32
python scripts/benchmark.py tests/fixtures/interview.mp4 --interval 0.25
python scripts/benchmark.py tests/fixtures/interview.mp4 --interval 1.0
```

## Environment (from `scripts/preflight.py`)

<!-- BENCH:ENVIRONMENT -->
*(filled from the contest machine — see `artifacts/benchmarks/preflight.json`)*

## Headline results — measured on the W7900 (2026-08-06)

Real per-stage metrics from a full `--require-rocm` analysis run of the 10 s
`interview.mp4` fixture (640×360, 25 fps, with audio) on the AMD Radeon PRO
W7900, torch 2.10.0+rocm7.1, HIP 7.1.25424. Raw JSON:
`artifacts/benchmarks/w7900_analysis_metrics.json` (cold run — each stage
includes its model load from disk).

| Stage | Wall time | Peak VRAM |
|---|---:|---:|
| NORMALIZING (ffmpeg, CPU) | 0.71 s | — |
| TRANSCRIBING (Whisper large-v3-turbo, GPU) | 12.53 s | 4 620 MB |
| DETECTING_PII (regex/heuristics, CPU) | <0.01 s | — |
| DETECTING_VISUAL (Grounding DINO tiny + YuNet, GPU, fp16 autocast) | 10.25 s | 6 260 MB |
| TRACKING (association; SAM 2.1 not installed → box fallback, recorded) | 0.02 s | — |
| BUILDING_PREVIEW (overlay render, CPU) | 0.43 s | — |
| **End-to-end analysis (10 s clip, cold)** | **≈ 24 s** | **6 260 MB peak** |

The run produced 7 redaction events (1 face track, 2 ID-document, 1 screen,
2 license-plate candidates, 1 spoken phone number with word-level timestamps)
— all from real model inference on the GPU; `--require-rocm` was active, so a
CPU fallback in a core stage would have aborted the run.

A GPU sanity microbenchmark from `scripts/preflight.py` on the same machine:
fp16 4096³ matmul sustains ≈ 20 TFLOPS effective.

## Comparisons

### FP16 vs FP32

<!-- BENCH:PRECISION -->
*(same clip, same policy, `--precision fp16` vs `--precision fp32`)*

### Detection interval sweep (0.25 s / 0.5 s / 1.0 s)

<!-- BENCH:INTERVAL -->
*(recall-versus-cost trade-off for the keyframe strategy; 0.5 s is the shipped default)*

### Keyframe+SAM strategy vs per-frame detection

<!-- BENCH:STRATEGY -->
*(per-frame open-vocabulary detection cost extrapolates linearly from measured
keyframes/s; the shipped pipeline detects at keyframes and lets SAM 2.1 carry
masks between them)*

### Cold start vs warm run

<!-- BENCH:COLDWARM -->
*(first run includes model load from disk; warm numbers are steady-state)*

## Notes

- The YuNet small-face assist detector runs on CPU by design and is excluded from
  GPU throughput numbers.
- Video encoding uses libx264 (CPU); "render" time therefore mixes CPU encode with
  GPU-free OpenCV effects — it is reported for completeness, not as a GPU claim.
- `--require-rocm` was active for all contest runs: a silent CPU fallback in a core
  model stage would abort the run rather than pollute the numbers.
