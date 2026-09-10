Document ID: RP-KB-001
Revision: 1.0
Classification: competition-public

# ROCm Environment Diagnostics Guide

This guide defines how RadeonPilot diagnoses a local AMD Radeon ROCm environment.
All facts are gathered by deterministic tools; agents never invent readings.

## Required checks

1. Identify the GPU and architecture target with `rocm-smi --showproductname`.
   RDNA3 workstation parts report `gfx1100` (for example Radeon PRO W7900 class).
2. Read VRAM with `rocm-smi --showmeminfo vram`. A 48 GB board reports roughly
   51522830336 bytes total. Model weights plus KV cache must stay below ~90% of
   this budget or the endpoint risks OOM.
3. Confirm the ROCm release with `cat /opt/rocm/.info/version` or the driver line
   from `rocm-smi --showdriverversion`.
4. Verify the endpoint process owns GPU memory with `amd-smi process --pid <pid>`.
   If the PID is missing from amd-smi output, the workload is not GPU-resident and
   no Radeon inference claim is allowed.

## Health interpretation

- VRAM used near zero with an endpoint "running" usually means the model failed to
  load to the device. Check the endpoint log for OOM or unsupported architecture.
- `rocm-smi --showpids` lists processes holding the device; an empty list while an
  endpoint claims to serve means attestation must fail closed.
- Temperatures above 95 C under sustained decode suggest insufficient cooling or a
  power cap; reduce concurrency before re-measuring.

## Radeon Cloud instance notes

The competition instance is a single Radeon GPU (gfx1100, 48 GB VRAM) with ROCm
7.2.1, Ubuntu 24.04, 128 CPU cores, and no Docker daemon. Deployment therefore
uses a Python virtual environment for vLLM or a source-built llama.cpp HIP binary
rather than container images.
