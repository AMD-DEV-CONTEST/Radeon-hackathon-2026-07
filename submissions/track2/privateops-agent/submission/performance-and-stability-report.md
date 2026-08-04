# Radeon Performance and Stability Report

## Verified hardware run

The following facts were captured from Radeon Cloud instance `u-15477-db2e6f27` on 2026-08-03. PrivateOps and vLLM ran in the same instance and communicated through `127.0.0.1`.

| Item | Verified value |
| --- | --- |
| GPU | AMD Radeon Graphics (`gfx1100`) |
| Reported VRAM | 51,522,830,336 bytes (about 48 GiB) |
| ROCm | 7.2.1 |
| PyTorch / HIP | 2.9.1 / 7.2.53211 |
| vLLM | 0.16.1.dev0 ROCm build |
| Model | `Qwen/Qwen2.5-7B-Instruct` |
| Model endpoint | `http://127.0.0.1:8000/v1/chat/completions` |
| Direct model latency | 1,511.072 ms |
| Completion throughput | 32.427 tokens/s |
| Prompt / completion tokens | 45 / 49 |
| Complete Chinese Agent task | 18,384.639 ms |

The direct measurement includes the loopback chat-completions request. The complete Agent measurement also includes local retrieval, planning, tool execution, prompt assembly, model generation, audit persistence, and response assembly. They measure different scopes and are not presented as directly comparable model benchmarks.

## Implemented optimization decisions

- vLLM uses the ROCm build and keeps inference on the Radeon GPU.
- The model endpoint is loopback, removing public-network latency and keeping prompts inside the instance.
- Maximum model context is 8,192 tokens to bound KV-cache demand.
- GPU-memory utilization is 0.85 to leave operational headroom for the Agent and evidence collection.
- Generation temperature is zero during evidence collection for repeatability.
- RAG forwards only the highest-ranked local evidence.
- Workspace inventory excludes `.git`, virtual environments, dependencies, caches, build output, and generated state.
- Inventory returns a deterministic sample and file-type summary instead of the dependency tree.
- Each list-valued tool field is capped at 25 entries in the model-only context. The full bounded tool result remains visible in the response and audit ledger.

The final three changes were implemented after the captured run because the evidence exposed a 1,799-file inventory dominated by `.venv`. They reduce unnecessary context, but no Radeon speedup number is claimed without a new hardware measurement.

## Software stability coverage

Automated tests cover provider-mode separation, loopback enforcement, model failure without fallback, RAG ranking, tool confinement, output bounding, permission classification, one-use confirmation, local memory, audit ordering and redaction, benchmark provenance, HTTP errors, bilingual output, Markdown safety, and UI state. The final verification report records the fresh test count and deterministic repeated-workflow result.

## Measurement integrity and remaining optional capture

PrivateOps does not invent baseline speedups, P50/P95 latency, VRAM peaks, concurrency throughput, or long hardware soak results. Those values require a new Radeon instance. If the video session includes extra time, run at least five warm requests and record median/P95 values as a new immutable evidence file; do not edit the existing verified record.

Authoritative sources:

- `evidence/rocm-verified/radeon-benchmark-run.json`
- `evidence/rocm-verified/rocm-agent-live-latency-zh.txt`
- `evidence/rocm-verified/rocm-verified-diagnostics.txt`
- `benchmark-evidence.json` and `benchmark-evidence.csv`, generated from those sources

