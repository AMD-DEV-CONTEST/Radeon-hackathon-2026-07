# AMD Radeon GPU / ROCm Optimization Notes — Knowledge Garden

This document explains *why* Knowledge Garden is shaped the way it is,
from the perspective of running on a single AMD **gfx1100** (RDNA3) GPU
under **ROCm 7.2.x**.

## Hardware context (verified on the submission instance)

| Resource | Detected by `rocm-smi` / `rocminfo` |
|---|---|
| GPU | 1× AMD Radeon Graphics, ISA gfx1100 (RDNA3) |
| VRAM | ~48 GB GDDR (51,522,830,336 bytes reported) |
| ROCm | 7.2.x (rock module) |
| vLLM | 0.16.1 (ROCm build) |
| Host CPU | 2× AMD EPYC (128 logical threads) |

**Important quirk**: although the host may expose multiple gfx1100 cards,
the container sees only **1** through HSA (`rocm-smi` returns one row). The
whole agent therefore targets **single-GPU operation**. The architecture
scales to multi-GPU via vLLM tensor parallel, but a 14B + 32B pair fits
comfortably on one 48 GB card.

## Choice of inference engine: vLLM on ROCm

| Factor | Reason |
|---|---|
| AMD officially supports it | Radeon Cloud's model-serving template uses `vllm serve` |
| PagedAttention | High concurrency / long-context agent loops inside fixed 48 GB |
| OpenAI SDK compatible | Agent/backend code speaks the standard OpenAI protocol |

## The key optimization: AWQ 4-bit quantization

Measured on the real card with the real extraction prompt (~223 input
tokens, warmup 1 + 3 runs median, batch=1, temperature 0.2):

| Model | Format | Solo tok/s | Co-resident tok/s | VRAM |
|---|---|---|---|---|
| Qwen2.5-14B | bf16 | 12.3 | — (can't co-reside) | 44 GB (util 0.85) |
| Qwen2.5-14B | **AWQ 4-bit** | 26.4 | **26.5** | ~12 GB (util 0.3) |
| Qwen2.5-32B | **AWQ 4-bit** | 12.5 | **12.5** | ~24 GB (util 0.5) |

**Findings:**

1. **AWQ 4-bit is 2.1× faster than bf16** on gfx1100 (26.4 vs 12.3 tok/s
   for 14B) — because decode bandwidth halves, which is the bottleneck for
   autoregressive generation. It also halves VRAM.
   *Measurement caveat*: an early "AWQ is slower" reading was wrong — it was
   first-graph compilation overhead. **Always warm up before measuring.**
2. **Dual-model co-residency has zero throughput cost**: 14B + 32B share
   42 GB and each runs at exactly its solo speed (26.5 / 12.5 tok/s).
3. **One 48 GB card hosts the whole agent**: 12 + 24 + 6 GB headroom.

## Dual-model architecture rationale

Why two models instead of one?

| Layer | Model | Why |
|---|---|---|
| Dialogue | 14B AWQ | Interactive latency matters (learning/review); 14B is fast and sufficient |
| Batch | 32B AWQ | Extraction quality matters (capability); no latency requirement |

The 32B does extraction because it produces higher-quality knowledge units;
the 14B handles chat because it is 2× faster. The split lets both win on
their own metric while sharing one card.

## Context budgeting (VRAM + KV cache)

| Layer | max_model_len | Why |
|---|---|---|
| 14B dialogue | 8192 | Learning/review conversations can be long |
| 32B batch | 4096 | Extraction input is budgeted to ~2500 chars (≈3000 tokens) + 700 output |

The worker truncates material to a token budget that fits the 32B context,
so no request ever exceeds the KV cache and OOM is avoided.

## Sequential startup requirement

The two vLLM instances **must start in order** (14B → wait → 32B).
Concurrent startup can rarely cause the 14B to be mis-loaded as fp16
(27.7 GB), which OOMs the shared card. Sequential startup with a readiness
check (`curl :8000/v1/models`) is enforced in the reproduce guide.

## SQLite concurrency tuning (supporting the GPU workload)

- **WAL mode** for crash safety + concurrent reads.
- `PRAGMA journal_mode=WAL` is executed **once per process** (module-level
  guard). Running it per-connection took an exclusive lock and deadlocked
  under concurrent request load (10 concurrent requests: 20 s timeouts →
  0.2 s after the fix).
- `PRAGMA busy_timeout=5000` on every connection.
- DB on fast local storage (NFS stalls previously froze the worker thread
  in uninterruptible I/O); a periodic backup copies it to persistent
  storage.

## End-to-end latency (measured on the real card)

| Operation | Model | Measured |
|---|---|---|
| Knowledge extraction (Raft notes, ~3000 tok input) | 32B AWQ | ~21-23 s |
| Dialogue turn (Feynman feedback) | 14B AWQ | 26.5 tok/s decode |
| Garden / skill detail API | — | 1-30 ms |

## What we deliberately did NOT do

- No tensor parallelism — a 14B + 32B pair fits one card; TP would waste
  the second GPU if one existed.
- No flash-attention tuning beyond vLLM defaults — PagedAttention already
  manages the KV cache for our context sizes.
- No speculative decoding — the workload is batch extraction + short
  dialogue turns, where the added complexity is not justified.
