# W7900 Quark Quantization Experiment

## Goal

Compare the existing Qwen3-4B-Instruct-2507 vLLM FP16 service against Quark
INT4 and INT8 exports on the same Radeon Pro W7900-class `gfx1100` allocation.

The first candidate is:

- weights: signed INT4, per-group, group size 128
- activations: FP16
- shorthand: W4A16
- Quark scheme: `int4_wo_128`
- vLLM loader: `quark`

If that scheme is not supported by the installed loader, test the
loader-compatible Quark INT8 W8A8 path rather than modifying model metadata or
claiming emulated serving.

## Why Not Claim FP8

The ROCm vLLM build exposes an FP8 loader, but a registered loader is not proof
that the W7900 has a native accelerated FP8 matrix path. The W7900 is RDNA3
`gfx1100`; AMD's headline FP8 LLM path targets CDNA accelerators such as MI300
and MI350.

The experiment therefore treats FP8 as a compatibility observation, not an
optimization result, unless a real W7900 run passes.

## Controlled Variables

- hardware allocation
- ROCm version
- Qwen3-4B-Instruct-2507 source model
- vLLM build
- context limit
- output limit
- heterogeneous SOP prompt matrix
- concurrency 1/2/4/8
- three bursts per concurrency
- semantic safety gate
- telemetry sampling

## Quality Gate

Every response must preserve:

- compensation redaction
- no automatic email sending
- missing-owner confirmation
- due-date-only calendar creation

No quantized variant is accepted as an optimization if any semantic safety
gate fails.

## Outputs

- FP16 raw benchmark JSON
- INT8 C16 eager and graph benchmark JSON
- INT8 C128 eager benchmark JSON
- per-second telemetry for every served variant
- Quark/vLLM/RDNA3 compatibility JSON
- machine-readable comparison summary
- report with model-size, latency, throughput, VRAM, power, and semantic results
