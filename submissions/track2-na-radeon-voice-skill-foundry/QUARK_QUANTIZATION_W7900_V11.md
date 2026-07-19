# Quark Quantization on Radeon Pro W7900 - v11

Measured: 2026-07-19 (UTC+8)

## Executive Result

The experiment completed the full AMD Quark quantization workflow on the same
Radeon Pro W7900-class `gfx1100` allocation used by the project:

1. **Quark INT4 W4A16 export succeeded but could not be served by the installed
   ROCm vLLM Quark loader.** The model directory fell from 8.06 GB to 2.68 GB
   (`66.73%`), but vLLM rejected signed INT4 per-group group-size-128 as an
   unsupported Quark serving scheme.
2. **Quark INT8 W8A8 served successfully through the real RDNA3 Triton INT8
   kernel.** Model-load VRAM fell from 7.67 GiB to 4.29 GiB (`44.07%`), and the
   same 25% GPU-memory budget exposed 51,856 KV-cache tokens versus 27,520
   (`88.43%` more).
3. **INT8 was rejected for the policy compiler.** With 128 calibration samples,
   concurrency-eight throughput was 160.61 output tokens/s versus FP16 at
   253.74 (`36.70%` slower). Only 11/51 INT8 responses preserved all four
   safety semantics, and only 2/51 were strict JSON. FP16 passed 51/51 for both.

The production decision is therefore:

`keep FP16 vLLM for policy compilation; do not promote this INT8 artifact`

This is a negative optimization result, not a failed experiment. It proves that
memory compression, loader compatibility, speed, and Agent safety must be
evaluated independently.

## Environment

| Component | Value |
|---|---|
| GPU | Radeon Pro W7900-class, `gfx1100`, 51,522,830,336 bytes |
| ROCm / HIP | 7.2 |
| Model | Qwen3-4B-Instruct-2507 |
| Quark | 0.12.post1 |
| vLLM | 0.16.1 development ROCm 7.2.1 build |
| FP16 server | vLLM eager, Triton Attention |
| INT8 server | vLLM eager/graph, `TritonInt8ScaledMMLinearKernel` |
| Context | 4,096 tokens |
| Max active sequences | 8 |
| GPU memory utilization | 0.25 |

## Controlled Workload

Both variants used the same:

- heterogeneous SOP prompt generator
- input targets 256, 1,024, and 3,072
- concurrency 1/2/4/8
- three bursts per concurrency
- output-token limits
- prefix caching and chunked prefill
- per-second GPU telemetry
- four-part safety semantic gate

The gate required every response to preserve:

- compensation redaction
- no automatic email sending
- missing-owner confirmation
- due-date-only calendar creation

## Serving Results

| Variant | C1 tok/s | C2 tok/s | C4 tok/s | C8 tok/s | C8 wall |
|---|---:|---:|---:|---:|---:|
| vLLM FP16 eager | 38.54 | 76.39 | 143.43 | 253.74 | 1.89 s |
| Quark INT8 C16 eager | 24.47 | 28.92 | 76.08 | 130.28 | 5.56 s |
| Quark INT8 C16 graph | 13.41 | 26.98 | 32.08 | 65.46 | 10.16 s |
| Quark INT8 C128 eager | 26.08 | 51.77 | 99.67 | 160.61 | 5.62 s |

Increasing calibration from 16 to 128 samples improved INT8 C8 throughput from
130.28 to 160.61 tokens/s, but did not close the gap to FP16.

Graph mode made this INT8 kernel slower. It also required 44.89 seconds of
initial compilation and reduced usable KV cache from 51,856 to 46,496 tokens.

## Capacity Results

| Capacity measure | FP16 | Quark INT8 | Change |
|---|---:|---:|---:|
| Model directory | 8.06 GB | 4.43 GB | -45.07% |
| Model-load VRAM | 7.67 GiB | 4.29 GiB | -44.07% |
| KV-cache tokens at 25% budget | 27,520 | 51,856 | +88.43% |
| 4,096-token max concurrency | 6.72x | 12.66x | +88.39% |

The experiment shows a legitimate capacity advantage. It does not show an
acceptable production path for this policy compiler because speed and semantic
quality regressed.

## Quality Results

| Variant | All safety gates | Strict JSON |
|---|---:|---:|
| FP16 final rerun | 51/51 | 51/51 |
| INT8 C16 eager | 26/51 | not captured in the first harness revision |
| INT8 C16 graph | 26/51 | not captured in the first harness revision |
| INT8 C128 eager | 11/51 | 2/51 |

INT8 C128 individual gate counts:

| Gate | Pass |
|---|---:|
| compensation redaction | 26/51 |
| no automatic sending | 14/51 |
| missing-owner confirmation | 16/51 |
| due-date condition | 25/51 |

Failed outputs included repetitive non-JSON language. The original and exported
tokenizers produced identical token IDs and identical chat-template token
sequences for the evaluation prompt, so tokenizer drift does not explain the
quality failure.

## Compatibility Boundary

### Quark INT4 W4A16

Quark successfully exported:

- signed INT4 weights
- per-group quantization
- group size 128
- FP16 activations

The installed vLLM Quark loader supports W8A8 INT8, W8A8 FP8, progressive
INT4+FP8 W4A8, and OCP MX schemes. It does not provide a W4A16 weight-only
scheme for this exported configuration, so startup failed before inference.

### FP8

The vLLM build registers an FP8 loader, but registration does not prove a
native accelerated FP8 matrix path on RDNA3 `gfx1100`. FP8 was not claimed or
benchmarked as an optimization.

## Engineering Decision

Keep the current FP16 vLLM graph production recommendation. The Quark INT8
artifact may be useful only for a future memory-constrained, lower-risk
workload after task-specific calibration, schema-constrained decoding, and a
full proof rerun.

For this project, any model variant that loses `mail.send = deny` or another
policy qualifier must be quarantined regardless of its memory savings.

## Evidence

- `benchmarks/quantization-v11-summary.json`
- `benchmarks/quantization-v11-fp16.json`
- `benchmarks/quantization-v11-int8-c16-eager.json`
- `benchmarks/quantization-v11-int8-c16-graph.json`
- `benchmarks/quantization-v11-int8-c128-eager.json`
- matching telemetry JSONL files
- Release asset: `quantization-v11-evidence.zip`
