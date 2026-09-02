# ADR-0001: AMD Inference Runtime Selection

> Date: 2026-08-03
> Status: superseded on 2026-08-04 by verified local vLLM deployment
> Context: AMD AI DevMaster Hackathon Track 2 submission

## Original Decision

The original validated runtime was the AMD Radeon GPU Cloud API for Qwen3.6-35B-A3B on gfx1100 with ROCm 7.2.1. At that point, local vLLM deployment for Qwen3-8B/14B was documented as a contingency rather than an asserted completed runtime.

## Why the Initial Decision Was Reasonable

- The GPU Cloud API was verified by `amd-provider.integration.test.ts` and a 20-case ablation using real inference.
- It runs on AMD Radeon gfx1100 with ROCm 7.2.1 and provides an OpenAI-compatible interface.
- Local installation initially carried operational risk because standard PyPI installation selects a CUDA build; the ROCm wheel source and deployment path required separate validation.

## Superseding Outcome

On 2026-08-04, the local vLLM path was installed and served successfully on the AMD instance: Qwen3-8B, gfx1100, ROCm 7.2.1, and Hermes tool calling. The current submission therefore treats both runtimes as verified, reports their results separately, and does not merge cloud-35B and local-8B metrics.

The authoritative current deployment record is [`docs/AMD-ROCM-DEPLOYMENT-EN.md`](../AMD-ROCM-DEPLOYMENT-EN.md). This ADR remains as historical context only.
