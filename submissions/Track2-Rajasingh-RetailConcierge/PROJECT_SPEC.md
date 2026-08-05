# AMD AI DevMaster Hackathon — Track 2 Submission
## Development & Local Deployment of Private AI Agents

**Team**: Rajasingh (Solo)
**Project**: RetailConcierge — Conversational Shopping Agent on AMD MI300X
**Date**: August 2026
**Hardware**: AMD Instinct MI300X (Radeon Cloud 1-Click, 192 GB HBM3, ROCm 7.2.3)
**Track**: Track 2 — Agentic AI (reasoning, planning, tool use, memory, RAG, multi-agent)

---

## 1. Application Scenarios

RetailConcierge is a conversational shopping agent over an **offline Amazon Berkeley Objects (ABO) catalog** — 145,615 products across 576 product types. It runs entirely on AMD hardware: every token is generated locally on the MI300X, no cloud inference API.

| Scenario | Description |
|----------|-------------|
| **Conversational product search** | "a pair of wireless earbuds under 5k rupees" → agent extracts the shopping brief, searches the offline catalog, screens for exact products, ranks deterministically |
| **Clarification-first behavior** | "I want something for my trip." → agent asks ONE precise clarifying question instead of guessing (reasoning + planning) |
| **Multi-turn refinement** | Recommendations carry refinement chips ("Vacuum Insulated", "Top Brand") — choosing one continues the same session with memory |
| **Offline / private catalog** | No live prices, no fake availability, no web calls. The agent only claims what the offline catalog contains — provenance is audited per recommendation |
| **Tamper-evident audit** | Every recommendation decision is written to a hash-chained audit log (verifiable without producer code) |

---

## 2. Agent Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Console app (main.py / app.py)                    │
│   user query → MAF Agent (Microsoft Agent Framework)                │
│      ├─ extract_brief        (structured shopping brief, Pydantic)  │
│      ├─ find_product_types   (canonical catalog types, FTS5)        │
│      ├─ find_brands          (canonical brand vocabulary)           │
│      ├─ search_catalog       (SQLite FTS5, dimension/price filter)  │
│      └─ finalize_recommendations (deterministic screen + rank)      │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ OpenAI-compatible API (vLLM)
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│               vLLM 0.26.0+rocm723 on AMD MI300X                     │
│   Gemma 4 12B it (Unified) — W8A8 INT8 via AMD Quark 0.12           │
│   --tool-call-parser gemma4 · --enable-prefix-caching               │
│   --enable-chunked-prefill · --kv-cache-dtype auto                  │
│   AITER attention (VLLM_USE_AITER=1)                                │
└─────────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────────┐
│         SQLite catalog (145,615 listings / 576 product types)       │
│         FTS5 full-text index · tamper-evident audit JSONL           │
└─────────────────────────────────────────────────────────────────────┘
```

Architecture boundary: the app, catalog, and source live on the developer laptop. The droplet runs **only** vLLM + the Quark quantizer. Nothing else is copied to the GPU host.

---

## 3. Core Capabilities

| Capability | Implementation |
|-----------|----------------|
| **Reasoning & planning** | Clarification gate: the agent asks one concise question when constraints conflict; otherwise extracts the brief and plans the tool sequence |
| **Tool use** | 5 tools (extract_brief, find_product_types, find_brands, search_catalog, finalize_recommendations) with Pydantic schemas |
| **Memory** | MAF `AgentSession` persists across turns; refinement chips continue the same session |
| **RAG** | SQLite FTS5 retrieval over 145K products; the agent grounds every claim in catalog evidence (provenance tracker) |
| **Deterministic finalization** | Application code — not the LLM — screens exact-vs-accessory and ranks (no hallucinated eligibility) |
| **Audit** | Hash-chained JSONL audit log; `scripts/audit_verify.py` verifies truncation/reorder/tampering without producer code |

---

## 4. Model Introduction & Local Deployment

| Model | Size | Quantization | Served via | Status |
|-------|------|-------------|-----------|--------|
| **Gemma 4 12B it (Unified)** | 23.9 GB BF16 → **13 GB INT8** | AMD Quark W8A8 (per-channel weight + per-token dynamic activation) | vLLM 0.26 `--quantization quark` | **Shipped** |
| Gemma 4 26B A4B MoE (BF16) | 51.6 GB | none (MoE INT8 rejected — see §7) | vLLM 0.26 | fallback |

The 12B INT8 checkpoint is **published publicly on Hugging Face** — [`rajasingh012/gemma-4-12b-it-quark-w8a8-int8`](https://huggingface.co/rajasingh012/gemma-4-12b-it-quark-w8a8-int8) — the first AMD Quark W8A8 INT8 quantization of Gemma 4 12B. Anyone can download and reproduce the inference story (base model: `google/gemma-4-12B-it`; 13 GB weights; model card documents the W8A8 scheme, compression, and accuracy caveats).

**Deployment plan (all repo scripts, reproducible):**

```
1. scripts/upgrade_vllm.sh     vLLM 0.23 → 0.26 (AMD ROCm wheel, one-time)
2. scripts/deploy_droplet.sh   download BF16 → launch vLLM on :8000
3. scripts/quantize_int8.sh    Quark W8A8 INT8 → /models/gemma-4-12b-it-int8
4. VLLM_FP8_MODEL=... deploy_droplet.sh   serve the INT8 checkpoint
5. uv run python main.py       console agent on the laptop, hits the droplet
```

Two post-quantize fixups are automated (`scripts/_quark_fix_vllm_keys.py`): Quark exports `embed_vision.multimodal_embedder.*` / `embed_vision.patch_*` key names that vLLM's `gemma4_unified` loader does not map — the fixup renames them to the expected layout and copies `chat_template.jinja` (Quark does not export it; vLLM 400s chat requests without it). This was debugged live on the droplet and is required for any Gemma 4 Unified checkpoint.

---

## 5. Inference Optimization for AMD Radeon GPU

| Technique | Impact | Details |
|-----------|--------|---------|
| **W8A8 INT8 quantization (AMD Quark 0.12)** | **1.8× smaller weights** (23.9 → 13 GB), ~12.1 GiB weight footprint on GPU | Per-channel INT8 weights (ch_axis=0, symmetric, static) + per-token INT8 activations (ch_axis=1, symmetric, dynamic). No calibration data needed. Recipe provenance: nameistoken/Gemma-4-31B-it-Quark-W8A8-INT8 (−0.08pp GSM8K). |
| **vLLM 0.23 → 0.26 ROCm upgrade** | Unlocks `--quantization quark` serving | AMD wheel index (`wheels.vllm.ai/rocm/0.26.0/rocm723`); fixed ABI breaks (flash-attn, torchaudio, torch_c_dlpack_ext) live in `upgrade_vllm.sh` |
| **AITER attention** | AMD-tuned attention/linear paths | `VLLM_USE_AITER=1` + `VLLM_ROCM_USE_AITER_FA=1` (flash attention), pinned in deploy |
| **Prefix caching** | ~35 ms median TTFT server-side | `--enable-prefix-caching` — multi-turn sessions reuse cached prefixes (64% hit rate measured on 26B) |
| **Chunked prefill** | Latency stability under concurrency | `--enable-chunked-prefill` |
| **KV cache dtype auto-tune** | No uncalibrated fp8 KV warning | `KV_CACHE_DTYPE` env: `auto` for Quark INT8 (checkpoint has no KV scale factors), `fp8` for BF16 serving |
| **Quark→vLLM key fixup** | Makes INT8 checkpoint vLLM-loadable | Debugged live: Quark's export naming ≠ vLLM gemma4_unified loader; fixup is automated in the pipeline |

**Comparative performance (measured on MI300X, vLLM 0.26 ROCm, ROCm 7.2.3 — 12B W8A8 INT8):**

| Metric | Value |
|--------|------:|
| Output throughput (single stream) | **49.8 tok/s** |
| Peak output throughput | **51.0 tok/s** |
| Median TTFT | ~55 ms |
| TPOT | ~19.8 ms |
| Benchmark | 10,240 input → 1,280 generated tokens in 25.7 s |

---

## 6. Project Source Code

- **Repository**: https://github.com/rajasingh012/retail-concierge (AGPL-3.0)
- **Language**: Python 3.12, Microsoft Agent Framework (MAF core 1.13.0 / openai 1.12.0), SQLite FTS5
- **Droplet scripts**: `scripts/` — upgrade_vllm.sh, deploy_droplet.sh, quantize_int8.sh, benchmark_concurrency.sh, catalog import/audit utilities
- **Startup guide**: README.md (quick start), scripts/README.md (droplet lifecycle), DEPLOYMENT_JOURNAL.md (live issues + fixes)
- **Tests**: 57 passing (pytest)

---

## 7. Innovation Summary

1. **Full AMD-native quantization pipeline that actually ships**: Quark W8A8 INT8 on Gemma 4 12B Unified, served via vLLM 0.26 `--quantization quark` — with the two post-quantize incompatibilities (key naming, chat template) debugged live and automated in the repo. Most teams stop at "load model in vLLM"; we engineered the AMD quantizer → ROCm vLLM path end-to-end.

2. **Deterministic trust in an LLM agent**: the agent *retrieves* with the LLM but *decides* with application code — exact-product screening and ranking are deterministic, provenance-tracked, and hash-chained into an audit log. No hallucinated prices, no invented eligibility.

3. **Honest failure documentation**: the 26B MoE quantization path (4 attempts, garbage output) is documented in DEPLOYMENT_JOURNAL.md and the code removed — the journal is a live record of what AMD tooling does and does not support (vLLM gemma4 parser open bugs #48678/#47909; Quark MoE loader limits).

---

## 8. Team

Rajasingh — solo developer. All architecture, agent design, catalog pipeline, AMD deployment scripts, and live GPU debugging.
