# Weekend W7900 Experiment Report

Measured on July 18, 2026, using one Radeon Cloud `gfx1100` allocation with
51,522,830,336 bytes of VRAM and ROCm 7.2.1.

## Executive Result

The weekend experiment produced three competition-relevant results:

1. **vLLM continuous batching changed the serving ceiling.** At eight
   concurrent, heterogeneous SOP requests, Transformers FP16 delivered 20.66
   aggregate output tokens/s and required 22.85 seconds. vLLM graph mode
   delivered 257.65 aggregate output tokens/s in 1.86 seconds, a 12.47x
   throughput improvement and 91.85% wall-time reduction.
2. **Native ASR batching changed the audio throughput ceiling.** Eight
   20.39-second inputs were processed in 1.91 seconds at 85.35x aggregate
   real-time. Sequential processing required 12.73 seconds at 12.82x
   aggregate real-time. Native batching was 6.66x faster while peak allocated
   VRAM grew from 1.661 to 2.439 GiB.
3. **Stress testing found and closed a proof-admission blind spot.** Voice
   Evidence v0.2 passed a repeated 280 ms burst-loss sample at 100/100 even
   though its ASR text drifted 18.67% relative to the deterministic clean
   baseline. Voice Evidence v0.3 adds multi-scale burst-loss measurement. The
   same sample is now quarantined at 65/100 with a measured 20.59% burst-loss
   ratio.

All serving runs retained the four safety semantics used by the gate:
compensation redaction, no automatic email sending, missing-owner
confirmation, and due-date-only calendar creation.

## Environment

| Component | Measured configuration |
|---|---|
| GPU | AMD Radeon Graphics, `gfx1100` |
| VRAM | 51,522,830,336 bytes |
| ROCm / HIP | `7.2.53211-e1a6bc5663` |
| PyTorch | `2.9.1+gitff65f5b` |
| Transformers | `4.57.6` |
| vLLM | `0.16.1.dev0+g89a77b108.d20260317.rocm721` |
| Triton | `3.5.1` |
| FlashAttention | `2.8.3` |
| Agent model | `Qwen/Qwen3-4B-Instruct-2507`, FP16 |
| ASR model | `Qwen/Qwen3-ASR-0.6B`, FP16 |

## Agent Serving A/B

Concurrency results use different scenario variations to avoid treating prefix
cache hits as independent work. Each concurrency level contains three bursts
and reports the median.

| Serving mode | C1 tok/s | C2 tok/s | C4 tok/s | C8 tok/s | C8 wall |
|---|---:|---:|---:|---:|---:|
| Transformers FP16, generation lock | 20.64 | 20.63 | 20.65 | 20.66 | 22.85 s |
| vLLM FP16 eager | 38.38 | 76.54 | 143.51 | 253.81 | 1.89 s |
| vLLM FP16 graph | 39.27 | 78.14 | 146.13 | 257.65 | 1.86 s |

The Transformers server accepted concurrent HTTP requests but serialized GPU
generation. At concurrency eight, request completion followed a staircase and
aggregate throughput did not rise above the one-request baseline.

vLLM used Triton Attention on ROCm, chunked prefill, prefix caching,
asynchronous scheduling, continuous batching, a 4,096-token context limit, and
up to eight active sequences.

Graph mode added only 1.51% throughput over eager mode at concurrency eight.
Its first startup required 35.88 seconds of `torch.compile`, one second of graph
capture, and approximately 0.46 GiB of graph memory. The engineering decision
is:

- use vLLM eager when the service is short-lived or restarted often;
- use vLLM graph when the service is long-lived enough to amortize compilation;
- the large gain comes from continuous batching, not graph compilation alone.

## Context-Length Behavior

| Mode | Input target | Median TTFT | Median output tok/s |
|---|---:|---:|---:|
| Transformers | 256 | 109.77 ms | 21.77 |
| Transformers | 1,024 | 431.30 ms | 17.80 |
| Transformers | 3,072 | 2,510.99 ms | 9.53 |
| vLLM graph | 256 | 72.56 ms | 40.43 |
| vLLM graph | 1,024 | 112.71 ms | 39.10 |
| vLLM graph | 3,072 | 285.74 ms | 35.07 |

The second run at each vLLM length benefits from prefix caching, so these
length values describe steady-state service behavior. The heterogeneous
concurrency matrix is the primary serving comparison.

## ASR Robustness

The text metric is **relative character drift against the deterministic clean
Qwen3-ASR output**, not absolute CER against a human transcript.

| Condition | Median RTF | Relative drift | Voice Evidence v0.2 |
|---|---:|---:|---|
| Clean | 0.0724 | 0.00% | pass, 100 |
| 20 dB noise | 0.0743 | 1.33% | pass, 100 |
| 10 dB noise | 0.0789 | 4.00% | pass, 100 |
| 5 dB noise | 0.0752 | 5.33% | review, 88 |
| 250 ms synthetic reverb | 0.0754 | 1.33% | review, 82 |
| 550 ms synthetic reverb | 0.0737 | 1.33% | review, 82 |
| Far-field attenuation + noise + reverb | 0.0788 | 5.33% | quarantine, 45 |
| 8.51% clipped samples | 0.0736 | 0.00% | quarantine, 50 |
| Repeated 280 ms burst loss | 0.0696 | 18.67% | **incorrect pass, 100** |

The clipped case demonstrates why transcript correctness alone is not enough:
the transcript happened to remain stable, but severe clipping is unsafe for
names, numbers, and negation in another recording.

## Voice Evidence v0.3

Voice Evidence v0.3 adds `burstLossRatio`, measured with 20 ms frames. It only
counts runs of at least two near-digital-silence frames that are bounded by
active speech. This separates packet-loss-like interruption from natural
sentence-end silence.

| Condition | Burst loss | v0.3 decision |
|---|---:|---|
| Clean | 0.00% | pass, 100 |
| Repeated 40 ms | 1.57% | pass, 100 |
| Repeated 120 ms | 5.29% | review, 88 |
| Repeated 280 ms | 20.59% | quarantine, 65 |

Thresholds:

- above 4%: review
- above 12%: quarantine

The voice-evidence schema, proof schema, and verifier are upgraded to `0.3.0`.
Compatibility manifests invalidate older v0.2 proofs and require revalidation
before skill reuse.

## Native ASR Batching

| Batch | Batch wall | Sequential wall | Speedup | Aggregate audio xRT | Peak VRAM |
|---:|---:|---:|---:|---:|---:|
| 1 | 1.49 s | 1.58 s | 1.06x | 13.67x | 1.661 GiB |
| 2 | 1.65 s | 3.18 s | 1.93x | 24.71x | 1.769 GiB |
| 4 | 1.70 s | 6.35 s | 3.74x | 48.10x | 1.990 GiB |
| 8 | 1.91 s | 12.73 s | 6.66x | 85.35x | 2.439 GiB |

This makes batched offline evidence generation practical: a review queue can
measure and transcribe multiple SOP recordings together without changing the
interactive single-recording path.

## GPU Telemetry

| Workload | GPU median/max | VRAM median | Power median/max | Junction max |
|---|---:|---:|---:|---:|
| Transformers extended | 100% / 100% | 17.35 GB | 144 W / 273 W | 61 C |
| vLLM eager extended | 100% / 100% | 38.40 GB | 167 W / 231 W | 55 C |
| vLLM graph extended | 100% / 100% | 37.77 GB | 169.5 W / 242 W | 59 C |
| ASR robustness | 88% / 96% | 17.35 GB | 96.5 W / 138 W | 45 C |

The vLLM memory figure includes the already-running Transformers and ASR
services because the experiment intentionally did not destroy the validated
baseline. It must not be read as standalone vLLM allocation.

## Validation

- Local: 33/33 tests passed; production build passed.
- Clean Radeon clone of commit `20776d9`: `npm ci`, 33/33 tests, and production
  build passed.
- All Agent serving samples passed the four-part semantic safety gate.
- Voice Evidence v0.3 from commit `20776d9` was replayed through the real
  `/api/transcribe` product endpoint on the W7900 allocation.

## Reproduce

The experiment harnesses are:

- `scripts/jupyter_remote_exec.py`
- `scripts/radeon_weekend_experiments.py`
- `scripts/radeon_asr_batch_benchmark.py`
- `scripts/summarize_weekend_v10.py`

Machine-readable summary:

- `benchmarks/weekend-v10-summary.json`

Raw files are kept under `benchmarks/weekend-v10-*`.
