# AMD Radeon and ROCm Deployment and Optimization

## Compliance objective

The team has run two private Radeon inference paths: a trained Qwen3 32B SFT path and a Qwen3-Next 80B single-GPU serving path. Both use participant-controlled `gfx1100` hosts and have archived, auditable measurements. A separate `rdk-agent` client configuration routes to a private OpenAI-compatible vLLM endpoint; that endpoint's server provenance is not used for the published 80B performance figures.

## Current client configuration

The private development environment currently selects:

| Field | Value |
| --- | --- |
| Pi provider | `amd` |
| Model | `Qwen3-Next-80B-A3B-Instruct` |
| API shape | OpenAI-compatible Chat Completions |
| Declared context window | 131,072 tokens |
| Declared maximum output | 8,192 tokens |

The endpoint and API key are intentionally excluded. The public example uses an environment variable: [pi-models.amd-rocm.example.json](config/pi-models.amd-rocm.example.json).

This client configuration proves only model routing. It does not prove GPU type, ROCm version, serving backend, or quantization.

## Current evidence scope

Archived evidence includes:

1. **32B SFT:** `gfx1100`, ROCm 7.2.1/HIP identity, pinned base revision and adapter hash, NF4 4-bit configuration, `/v1/models`, 88-trial-per-arm A/B, and a five-node live `rdk-agent` screenshot.
2. **80B:** `gfx1100`, Q4_K_M GGUF identity and hash, single-card VRAM evidence, ten saved baseline/tuned records, aggregate verification script, and three API compatibility canaries.
3. **Private vLLM client route:** provider `amd` and model selection are verified, but its separate server GPU, ROCm/vLLM version, launch command, revision, and precision are not independently archived here.

See [MODEL_TRACK.md](MODEL_TRACK.md), [`model/AGENT_E2E.en.md`](../../model/AGENT_E2E.en.md), and the root README Section 9.5.

## Implemented software-level inference controls

- Deterministic greeting/acknowledgement bypass.
- A small, no-tool, no-Skill, no-context intent-classification session.
- Focused per-stage sessions instead of one unbounded conversation.
- Strict Skill loading and explicit selection evidence.
- Text handoffs bounded to 6,000 characters.
- Deterministic structural/safety checks outside the model.
- Files as the durable source of truth between stages.

These features reduce unnecessary tokens and context growth. They are not substitutes for measured GPU optimization.

## Controlled optimization matrix

Hold prompts, output limits, software revision, and correctness criteria constant. Change one variable at a time.

| Experiment | Baseline | Candidate | Required evidence |
| --- | --- | --- | --- |
| Precision/quantization | Server default | Hardware-supported lower precision or quantized model | Exact launch flags, VRAM, correctness, TTFT, tokens/s |
| Context limit | Maximum supported | Bounded to measured workflow needs | Input tokens, truncation checks, latency, VRAM |
| Warm model | Cold process | Warm process with documented warm-up | Cold/warm samples, p50/p95 |
| Memory utilization | Server default | Tuned vLLM utilization | OOM-free repeated runs, peak VRAM |
| Concurrency | One request | Measured low concurrency | Per-request latency and throughput |
| Prompt workload | Full generic context | Scoped agent + selected Skill | Token counts, stage correctness, end-to-end time |

## Metrics

- Client time to first token (TTFT), p50 and p95.
- Decode output tokens per second.
- Total request latency.
- End-to-end workflow time.
- Peak VRAM and GPU utilization.
- Power or energy only where the target exposes reliable counters.
- Correct-response and acceptance rate under the same prompts.

## Benchmark command

```sh
node submission/en/scripts/benchmark-openai-compatible.mjs \
  --provider amd \
  --runs 10 \
  --output submission/en/evidence/amd-endpoint-benchmark.json
```

The report contains the endpoint host for traceability but no scheme, path, or key. Remove or hash the host as well if it reveals private infrastructure.

## Evidence table

| Item | 32B SFT path | 80B serving path |
| --- | --- | --- |
| Client/API identity | `/v1/models` and `/health` archived | three API compatibility canaries archived |
| AMD Radeon GPU | `gfx1100`, 51.5 GB | `gfx1100`, 51.5 GB |
| ROCm/runtime | ROCm 7.2.1, torch 2.9.1+rocm7.2.0 | `llama.cpp` HIP binary archived; exact ROCm version not captured |
| Precision/quantization | NF4 4-bit base + LoRA, bf16 compute | Q4_K_M GGUF |
| Baseline -> optimized TTFT | p50 17.41 -> 8.26 s; p95 83.97 -> 12.89 s | archived medians 2,021.26 -> 1,808.76 ms |
| Baseline -> optimized decode | 6.54 -> 6.72 tok/s | 37.19 -> 49.82 tok/s |
| Peak VRAM | 27.99 -> 28.06 GB | 48.84 -> 49.52 GB |
| Agent workflow | 5/5 nodes in 4 min 04 s | no separately archived five-node trace |

The separate private vLLM server remains a client-routing claim only. No unmeasured value is presented as measured.
