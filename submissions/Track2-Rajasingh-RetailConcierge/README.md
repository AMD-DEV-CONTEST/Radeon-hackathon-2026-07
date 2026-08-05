# RetailConcierge — Track 2 Submission

**AMD AI DevMaster 2026 · Track 2: Development & Local Deployment of Private AI Agents**

A conversational shopping agent that runs **100% on an AMD Instinct MI300X**: Gemma 4 12B W8A8 INT8 (AMD Quark) served through vLLM 0.26's ROCm wheel, grounded in an offline 145,615-product catalog with deterministic tool-based ranking and a tamper-evident audit trail.

## One-line pitch

**A privacy-first retail agent that retrieves with the LLM but decides with code** — every recommendation is screened and ranked by deterministic application logic (no hallucinated prices, no invented eligibility), served entirely by local inference on one AMD MI300X.

## Deliverables (official Track 2 requirements)

| # | Official requirement | Where |
|---|---------------------|-------|
| 1 | Project Specification Document | [PROJECT_SPEC.md](PROJECT_SPEC.md) — scenarios, agent architecture, core capabilities, model & local deployment, inference optimization |
| 2 | Project Source Code (complete repo, README with env config / startup guide / dependency list) | [github.com/rajasingh012/retail-concierge](https://github.com/rajasingh012/retail-concierge) — frozen release tag [`v1.0.0-amd-hackathon`](https://github.com/rajasingh012/retail-concierge/releases/tag/v1.0.0-amd-hackathon), SHA-256 inventory in [SHA256SUMS](SHA256SUMS) |
| 3 | Demo Video (3–5 min, actual execution on AMD Radeon GPU) | [demo/final_demo.mp4](demo/final_demo.mp4) — 2:27, real MI300X terminal + agent UI, all 8 cues |
| 4 | Supplementary: PPT/Poster | [RetailConcierge_Poster.pptx](RetailConcierge_Poster.pptx) / [RetailConcierge_Poster.png](RetailConcierge_Poster.png) |

## What the demo video shows (8 cues)

1. **GPU identity** — `rocm-smi`: AMD Instinct MI300X, gfx942, live chat completion on the quantized model
2. **Conversational search** — "wireless earbuds under 5k rupees" → ranked recommendations
3. **Clarification-first** — "I want something for my trip." → one precise clarifying question
4. **Multi-turn refinement** — refinement chips continue the same session with memory
5. **Serving stack** — vLLM 0.26.0+rocm723, torch hip 7.2.3, model served via `/v1/models`
6. **Measured speed** — vLLM bench: **49.8 tok/s**, **51.0 peak**, TTFT 55 ms, 1,280 tokens in 25.7 s
7. **Quantization** — Quark W8A8 INT8: 23.9 GB → **13 GB** (1.8×), `quant_method: quark`, served with vLLM's Quark loader
8. **Open source** — public repo (no Private badge) + Hugging Face model page

## Verification

- **Source**: public repo, tag `v1.0.0-amd-hackathon`, 57 passing tests
- **Model**: [rajasingh012/gemma-4-12b-it-quark-w8a8-int8](https://huggingface.co/rajasingh012/gemma-4-12b-it-quark-w8a8-int8) on Hugging Face — first AMD Quark W8A8 INT8 quantization of Gemma 4 12B
- **Artifact hashes**: [SHA256SUMS](SHA256SUMS) · commit pin: [submission.json](submission.json)

## Evidence boundaries (what we did NOT measure)

- Peak VRAM tracing and 24 h soak were not run (droplet cost-constrained).
- TTFT is median, single endpoint (55 ms); P50/P95 latency percentiles were not collected.
- The −0.08pp GSM8K figure from the recipe provenance is a 31B-class measurement; the 12B Unified checkpoint is validated via the tool-call accuracy gate, not GSM8K.
- The 26B A4B MoE quantization path was removed after 4 failed attempts (documented in DEPLOYMENT_JOURNAL.md) — the shipped path is 12B dense INT8.
