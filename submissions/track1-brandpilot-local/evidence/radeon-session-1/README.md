# Radeon session 1 evidence

This directory contains the reviewed evidence from the first controlled Radeon
Cloud generation on 2026-07-25. The result was a real SDXL image-to-image run
through PyTorch/HIP on one AMD Radeon GPU.

Core artifacts:

- `generated-output.png` and the rights-safe repository input
- `generation-metadata.json` and sanitized `generation.log`
- `environment.json`, package versions, and PyTorch GPU summary
- sanitized `rocm-smi` and `rocminfo` summaries
- `session-summary.json` with cloud timing, credits, and template facts
- cropped screenshots proving readiness, HIP device detection, live GPU
  activity, generated output display, and zero active instances

Sanitization removed account details, instance IDs, authenticated URLs, internal
registry/host information, raw environment values, private paths, and hardware
identifiers. Model weights and the 14 GiB persistent Hugging Face cache are not
included.
