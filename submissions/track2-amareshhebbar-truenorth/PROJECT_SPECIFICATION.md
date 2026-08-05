# TrueNorth — Project Specification
## AMD AI DevMaster Hackathon — Track 2: Development & Local Deployment of Private AI Agents

**Team:** Solo Developer — Amaresh Hebbar
**Repository:** https://github.com/onenot8/TrueNorth
**License:** as per repository

---

## 1. Application Scenario

**KisanSathi** — an AI farm advisor built on the TrueNorth agent framework. A farmer describes their crop, land, and problem in natural conversation (Hindi, Kannada, English, or mixed); the agent extracts 13 structured fields across multiple turns and generates a JSON crop advisory aligned to ICAR (Indian Council of Agricultural Research) guidance — likely cause, treatment plan, cost estimate, and urgency level.

This targets a real, large-scale problem: 120M+ smallholder farmers in India lack affordable access to expert agronomist advice, but already use WhatsApp daily. KisanSathi is one of ~14 example applications shipped with TrueNorth, all built on the same underlying agent engine.

Track 2 relevance: multi-step planning (structured field-by-field extraction across a 13-field conversation), tool use (YAML-defined goal schema, structured JSON output generation), local knowledge processing, and — the focus of this submission — local, cost-free inference on an AMD Radeon GPU via ROCm.

---

## 2. System / Agent Architecture

TrueNorth is a general-purpose conversational agent framework (not built for this hackathon — an existing, actively developed open-source project) with:

- A core conversation engine (`TrueNorthEngine`) that manages multi-turn state, field extraction, confidence scoring, and completion detection against a YAML-defined "goal" schema
- A hallucination firewall (3-stage: factual consistency check, source tracing per claim, confidence gating) — not used in this specific demo run, but present in the framework and demonstrated in other bundled samples
- A multi-model LLM router (`LLMRouter`) with per-task routing (`extract` / `converse` / `output` / `classify` / `verify`), automatic fallback chains, retry with backoff, circuit breakers, and per-model cost/latency tracking
- 1,282 passing automated tests (Python) plus TypeScript, Go, and Rust SDK test suites, all green on the reference environment

```
Farmer (text) → TrueNorthEngine → LLMRouter → [task-specific model]
                                       ├─ extract   → local Qwen2.5-7B (this submission)
                                       ├─ converse  → local Qwen2.5-7B (this submission)
                                       ├─ output    → local Qwen2.5-7B (this submission)
                                       └─ verify    → Claude (cloud, by design — safety-critical
                                                       verification path intentionally stays cloud)
              → structured JSON advisory (ICAR-aligned)
```

---

## 3. Model & Local Deployment Plan

- **Model:** Qwen2.5-7B-Instruct, served via vLLM 0.16.1 (ROCm 7.2.1 build)
- **Serving command:**
  ```
  vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port 8000 \
    --gpu-memory-utilization 0.6 --enforce-eager
  ```
- **Integration:** TrueNorth's `LLMRouter` already ships a `LocalLLMClient` supporting Ollama, llama.cpp, LM Studio, and any OpenAI-compatible endpoint out of the box. No new provider code was required — only a goal-level YAML config change:

  ```yaml
  llm:
    routing:
      extract:  qwen-local
      converse: qwen-local
      output:   qwen-local
    fallbacks:
      extract:  []
      converse: []
      output:   []
    provider_config:
      local:
        provider: openai_compat
        base_url: http://127.0.0.1:8000/v1
        model: Qwen/Qwen2.5-7B-Instruct
  ```

  The routing "model name" (`qwen-local`) only needs to match a known provider-detection prefix (`qwen`, `local`, `ollama`, etc.) in TrueNorth's router; the actual endpoint and real model identifier are supplied separately via `provider_config`. This is a genuine, unmodified integration point in the framework, not a patch to make it work.

- **Application-side bug fixes (not framework changes):** two small, unrelated compatibility fixes to the bundled `kisansathi/app.py` sample were required to run end-to-end on this TrueNorth version — a stale `resp.detected_language` attribute reference, and a `resp.final_output` dict-vs-object mismatch in the print path. Neither affects the framework or the routing logic itself; both are one-line fixes noted for upstream.

---

## 4. AMD Radeon GPU / ROCm Adaptation

- **GPU:** AMD Instinct-class ROCm device (`gfx1100`), 47.98 GiB VRAM, ROCm 7.2.1, confirmed via `rocminfo`/`rocm-smi` on AMD's Radeon Cloud platform
- **Inference backend:** vLLM 0.16.1 (ROCm-compiled build, `rocm721` tag), Triton attention backend, eager execution mode
- **Memory footprint:** model load 14.37 GiB; KV cache 12.69 GiB (237,632 tokens, 7.25x concurrency headroom at 32K context) — well within the 0.6 GPU-memory-utilization cap used
- **Verified inference call:**
  ```
  curl http://127.0.0.1:8000/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{"model":"Qwen/Qwen2.5-7B-Instruct","messages":[{"role":"user","content":"Say OK"}]}'
  ```
  → `200 OK`, `"content":"OK!"`

---

## 5. Benchmark: Cloud-Routed vs. Local-ROCm-Routed

Same TrueNorth engine, same goal config, same conversation flow (`kisansathi` — crop advisory) — only the `llm.routing` target changed between runs. Both timings are taken directly from the application's own structured latency logging (`engine: turn=1 ... latency=Nms`), not estimated.

| Routing | Turn 1 latency | Cost per call | Notes |
|---|---|---|---|
| Cloud (default chain: Gemini → GPT-4o-mini → Claude Haiku, first two unauthenticated on this box, third rate-limited) | **85,406 ms** | API-metered | 9 failed attempts across 3 providers before a usable response |
| Local ROCm (Qwen2.5-7B via vLLM on Radeon, `gfx1100`) | **2,020–2,073 ms** | **$0.0000** | Single call, first attempt, `200 OK` |

**~41x latency reduction**, and marginal inference cost drops to zero. The cloud-routed number is not an artificially bad control — it is what TrueNorth's own default routing table does in an environment (this Radeon Cloud instance) without pre-configured cloud API keys, which is a realistic deployment scenario for a self-hosted, privacy-sensitive agent (the stated design goal of TrueNorth's local-routing feature).

Subsequent local-routed turns in the same session ranged 1,945–15,132 ms depending on extraction complexity (multi-field turns took longer), all still an order of magnitude faster than the cloud baseline and all at $0 marginal cost.

---

## 6. Observed Model Quality (reported honestly)

Qwen2.5-7B occasionally returns JSON wrapped in markdown code fences with trailing commentary rather than clean JSON (e.g. `` ```json\n{...}\n```\n\nNote: ...``). TrueNorth's field extractor has a fallback parser that recovers the intended value in these cases without failing the conversation turn — this is a real, working resilience feature of the framework, not something added for this submission. This is a known and expected accuracy/consistency tradeoff of a small local 7B model versus a frontier cloud model, and is reported here rather than omitted.

---

## 7. Reproduction

```
git clone https://github.com/onenot8/TrueNorth.git
cd TrueNorth/packages/core
poetry env use python3.11
poetry install

# On a ROCm-capable GPU host:
vllm serve Qwen/Qwen2.5-7B-Instruct --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.6 --enforce-eager

# Add the llm: routing block above to samples/python/kisansathi/goal.yaml, then:
export ANTHROPIC_API_KEY=sk-ant-...   # required only for the 'verify' task
GOAL_YAML=../../samples/python/kisansathi/goal.yaml poetry run python \
  ../../samples/python/kisansathi/app.py
```

Full environment: ROCm 7.2.1, Python 3.11.15, vLLM 0.16.1.dev0 (rocm721 build), TrueNorth framework v0.1.8.
