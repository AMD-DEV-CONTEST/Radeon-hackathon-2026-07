# Track 2 — AetherPro Technologies — OmniAgent

**A self-hosted, provider-agnostic AI agent runtime, with all language-model
inference executing on an AMD Radeon PRO W7900 under ROCm.**
No remote model API participates in any core function.

| Deliverable | Location |
|---|---|
| **Project Specification** | [`PROJECT_SPECIFICATION.md`](PROJECT_SPECIFICATION.md) |
| **Source code + README** | https://github.com/AetharaAI/omniagent-amd |
| **Demo video** | `<VIDEO_LINK>` |
| **Supplementary (diagram)** | [`architecture.html`](architecture.html) |
| Evidence bundle (hash-verified) | [`AMD_HACKATHON/evidence/`](https://github.com/AetharaAI/omniagent-amd/tree/main/AMD_HACKATHON/evidence) |
| Reproducible deployment runbook | [`AMD_HACKATHON/LAUNCH_RUNBOOK.md`](https://github.com/AetharaAI/omniagent-amd/blob/main/AMD_HACKATHON/LAUNCH_RUNBOOK.md) |

## Stack

`AMD Radeon PRO W7900` (gfx1100, RDNA3, 47.98 GiB) on Radeon Cloud ·
ROCm 7.2.1 · vLLM 0.25.1+rocm723 · PyTorch 2.11.0 (ROCm) ·
model `cyankiwi/GRM-2.6-Plus-AWQ-INT4` — Qwen3.5 hybrid, 16 full-attention +
48 linear-attention (Gated Delta Net) layers.

## Capabilities — 5 of 5 (2 required)

| Capability | Status |
|---|---|
| Tool invocation | 8 tool calls against a 45-tool registry in one task; `finish_reason: tool_calls` at the model layer |
| Multi-step task planning | five-field intake state machine, 0 retries |
| Local multi-turn memory | 10 caller / 11 agent turns over 198 s with continuous state |
| Local knowledge retrieval (RAG) | Qdrant + local CPU embedding service |
| Permission control & privacy | Agent Passports — cryptographic identities with capability scoping |

## Measured

| | |
|---|---|
| Weights resident | 19.05 GiB |
| KV cache | 20.44 GiB → **310,931 tokens** |
| Context window | **65,536** (native ceiling 262,144) |
| Max concurrency @ 64k | **4.74×** |
| Time to first token | **198 ms** |
| Decode — 1 stream / 4 concurrent | 6.2 tok/s / 6.1 tok/s each, **same wall clock** |
| Prefix cache hit rate | 64.5% |

### Optimizations applied

| | Before | After |
|---|---|---|
| `gpu_memory_utilization` | 0.80 | 0.90 |
| KV cache | 190,171 tok | **310,931 tok** |
| Context window | 8,192 | **65,536** |
| Serving path | blocking wrapper, non-incremental SSE | `AsyncLLM` — true streaming + continuous batching |
| Prefix caching | off | on |

### Finding for AMD — RDNA3 kernel coverage

Single-stream decode reaches roughly **15% of the card's memory-bandwidth
roofline**. The engine log identifies why — four hot paths fall back to
generic Triton because the optimized ROCm kernels target CDNA, not RDNA3:

```
WARNING [chunked_prefill_paged_decode.py:419]
    Cannot use ROCm custom paged attention kernel, falling back to Triton implementation.
INFO    [compressed_tensors_wNa16.py:137]  Using TritonW4A16LinearKernel
INFO    [qwen_gdn_linear_attn.py:228]      Using Triton/FLA GDN prefill kernel
WARNING [activation.py:783]  [ROCm] native GELU tanh approximation unstable
```

Results are numerically correct. **The gap is kernel coverage, not hardware
capability.** RDNA3 parity with CDNA would be the highest-impact improvement
for workstation-class Radeon inference.

Also surfaced: engine init took **2051 s, of which only 79.8 s was
`torch.compile`** — the remainder is memory profiling and warmup at 64k
context. A progress indicator during warmup would prevent misdiagnosing it
as a hung frontend.

## Validation — a live telephone call

```
PSTN carrier → VoiceOps → ASR → Aether Gateway → GRM on AMD W7900
             → Kokoro TTS (CPU) → caller
```

198.34 s · 10 caller turns · 11 agent turns · intake 5/5 fields ·
`final_disposition: success` · **all ten inference turns on
`grm2.6-plus-amd`** · `fallbacks: []` · `anomalies: []`.
Platform history: 129 calls, 98.45% containment, 43 s average handle time.

Per-stage latency (n=10): ASR **328 ms** · LLM **5339 ms** · TTS **3114 ms**.

## Stated limits

1. **No scheduling transaction.** The call completed intake and a follow-up was
   agreed *in conversation*; no booking record was created. The platform's own
   analytics confirm it — Booking Rate 0.00%.
2. **Agent Passports prove identity and capability scope, not enforced
   mandates.** Cryptographic mandate verification and tamper-evident receipts
   are designed but not enforced at execution time. Roadmap, not capability.
3. One node, single session, for the GPU measurements. No reliability or scale
   claim.
4. Throughput parity is not claimed — see the kernel finding above.

Every figure above comes from a log captured during a live run, packaged on
the GPU node, hashed, transferred off-host and re-verified before the instance
was destroyed. Nothing is estimated or reconstructed.
