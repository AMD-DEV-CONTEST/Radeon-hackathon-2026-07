# AMD Cloud service acceptance record (2026-08-04)

The AMD instance was provisioned with the planned Qwen3.6 FP8 checkpoint and an
isolated vLLM environment. The model registry and text-only server path work,
but the SWE-bench benchmark is intentionally stopped at service acceptance.

## What passed

- GPU: AMD `gfx1100`, ROCm 7.2.1.
- Checkpoint: `Qwen3.6-35B-A3B-FP8`, ModelScope `master`.
- Checkpoint files: 56; SHA256 manifest is stored beside the checkpoint as
  `SHA256SUMS.txt` on the instance.
- vLLM: 0.25.1 ROCm wheel, with AMD Torch 2.11 ROCm 7.2.2 in the isolated
  environment (the preinstalled `/opt/venv` was not modified).
- vLLM resolved `Qwen3_5MoeForConditionalGeneration` and accepted the planned
  localhost, 32K context, tool parser, reasoning parser, xgrammar, and prefix
  caching flags.

## Blocking result

The checkpoint uses FP8 E4M3 MoE weights with static `128x128` weight scales
and dynamic `1x128` activation scales. vLLM 0.25.1 rejected this layout on
`gfx1100` for every available native FP8 MoE backend tested:

| backend | result |
|---|---|
| `auto` | no FP8 MoE backend supports deployment configuration |
| `triton` | kernel does not support the quantization scheme |
| `aiter` | AITer is restricted to supported gfx9 devices |
| `humming` | kernel does not support current ROCm device |
| `flashinfer_cutlass` | kernel does not support current ROCm device |
| `marlin` | kernel does not support current ROCm device |
| `emulation` | not accepted for serialized FP8 MoE by this vLLM release |

The source-build fallback was also attempted against the preinstalled Torch
2.9.1. It reached CMake but failed because that Torch lacks the stable headers
required by vLLM 0.25.1. The isolated environment was then aligned to the
official AMD Torch 2.11 wheel and passed vLLM import/registry checks; this did
not change the native FP8 MoE limitation.

The reproducible launcher was then corrected to pass the model through the
explicit `--model` option (the first positional invocation selected vLLM's
default draft-model path and is not used as evidence). The corrected run
resolved the local Qwen3.6 config and failed at model construction with the
same `No FP8 MoE backend supports the deployment configuration` exception.
Its complete log is retained locally as
`runs/amd-cloud-vllm-script2-20260804.log` and on the instance as
`/root/radeon-vllm-script2-20260804.log`.

## Decision

The benchmark is not run and no resolve rate is reported. This is an
infrastructure/backend incompatibility, not a model or harness score. The
following artifacts remain on the instance for a future image or vLLM release:

- `/root/radeon-vllm.log`
- `/root/radeon-code-agent-venv`
- `/root/.cache/huggingface/Qwen3.6-35B-A3B-FP8`
- `/root/.cache/huggingface/Qwen3.6-35B-A3B-FP8/SHA256SUMS.txt`

The launcher now performs this same check before starting the server via
`scripts/cloud_preflight.py`; there is no override that could accidentally
turn an unsupported device into a ranked run.

The next valid run must use an AMD image/vLLM build that advertises a native
FP8 MoE kernel for `gfx1100`, or an officially supported checkpoint/layout. A
BF16 conversion, a different model, or an external inference API would violate
the fixed Track 2 experiment and is therefore not substituted here.

## External support cross-check

This matches the published support boundary rather than an unexplained local
installation error. AMD's Qwen3.6 Day-0 deployment guide explicitly targets
Instinct MI300X, MI325X, MI350X, and MI355X, while this instance reports Radeon
`gfx1100`. The current vLLM ROCm release notes advertise RDNA-specific W4A16
work, but do not advertise this serialized block-scaled FP8 MoE layout for
`gfx1100`. The next valid run therefore requires either an AMD Instinct
instance or a future Radeon image that explicitly advertises a native FP8-MoE
backend for this checkpoint; simply upgrading the Python package is not
evidence of support.

References:

- AMD, [Day 0 Support for Qwen3.6 on AMD Instinct GPUs](https://www.amd.com/en/developer/resources/technical-articles/2026/day-0-support-for-qwen3-6-on-amd-instinct-gpus.html)
- vLLM, [release notes](https://github.com/vllm-project/vllm/releases)
- ROCm, [AITER supported hardware](https://github.com/ROCm/aiter)
