# Caprigo — Track 2 Project Specification

**AMD AI DevMaster Hackathon · Track 2: Agentic AI**  
**Team:** Vibes-Coded (solo) · **Credit:** b_Radford (Brad Armstrong)  
**Source:** https://github.com/doteyeso-ops/caprigo (MIT)

---

## 1. Application scenarios

- **Local private coding / ops agents** on AMD hardware without shipping prompts to a third-party cloud by default.
- **Operator UX:** Overview (runtime health), Session (agent chat + tools), HUD Board (missions / status).
- **Scrap → modern AMD story:** prove agents already run on unsupported Polaris (RX 580 / Vulkan), then measure uplift on supported Radeon + ROCm (hackathon GPU) and/or Lemonade Halo.

Primary user: solo builders and small teams who want an on-prem agent runtime that already has tools, MCP, and mission boards — not a bench-only demo.

---

## 2. Agent architecture

```mermaid
flowchart TD
  UI[Overview / Session / Board]
  GW[Caprigo Gateway]
  AG[Agent runtime]
  LT[Lean tool filter]
  LLM[OpenAI-compatible backend]
  UI --> GW --> AG
  AG --> LT
  AG --> LLM
  LLM --> Ollama[Ollama + Vulkan scrap RX580]
  LLM --> VLLM[vLLM + ROCm gfx1100]
```

- Agents call tools (filesystem, shell, web, MCP, skills).
- **`CAPRIGO_LEAN_TOOLS=1`:** unrestricted agents see ~17 core tools instead of ~170 duplicate schemas — reduces context blowups on 8GB cards. Upstream: `packages/agent/src/lean-skills.ts`.
- Full catalog remains available via skill assignment when needed.

---

## 3. Core capabilities

| Capability | Notes |
|------------|--------|
| Multi-surface UI | Overview, Session, Board |
| Tool use | Native tools + MCP |
| Missions / scripts | Offline + online agent jobs |
| Backend-agnostic LLM | Any OpenAI-compatible endpoint |
| Lean tools | Context-safe local inference on 8GB |
| Measured delta harness | Same Session prompt before/after AMD GPU |

---

## 4. Model & local deployment

| Role | Model / path |
|------|----------------|
| Scrap default | `b_Radford-coder-3b-128k` (Qwen2.5-Coder-3B 128k Q4) via Ollama Vulkan |
| Optional thinker | `b_Radford-qwen3-4b-thinking` @ 32k ctx on RX 580 |
| Hybrid demo path | Caprigo UI local + OpenRouter when needed for clean VO demo |
| ROCm target | Same Caprigo gateway → ROCm Ollama / vLLM on Radeon Cloud |

Env sketch:

```bash
CAPRIGO_LLM_PROVIDER=ollama
OLLAMA_URL=http://127.0.0.1:11434
DEFAULT_MODEL=<local-amd-model>
CAPRIGO_LEAN_TOOLS=1
```

Lived proof writeup + CSVs: https://github.com/doteyeso-ops/rx580-vulkan-agents

---

## 5. AMD Radeon GPU / inference-speed optimization (Track 2 · 40%)

### Measured (2026-08-04 · instance destroyed after capture)

| Workload | Hardware | Result |
|----------|----------|--------|
| TokMark / Ollama decode | RX 580 Vulkan | 3B–7B Q4 ~15–24 t/s; 7B@32k ~**19** t/s |
| Caprigo Session (lean) | RX 580 | ~**31 s** ok (`bench-agent-delta.csv`) |
| **vLLM chat decode** | **gfx1100 · ROCm 7.2.1 · Qwen2.5-7B-Instruct** | **29.21 tok/s** (128 tok / 4.382 s) · **~1.5×** vs scrap 7B |
| Path smoke | same instance · 0.5B Instruct | 215 tok/s |

Full table + CSV: [`AMD.md`](AMD.md) · [`../artifacts/delta.csv`](../artifacts/delta.csv)

### Optimization levers shipping with Caprigo

1. **Lean tool schemas** (`CAPRIGO_LEAN_TOOLS=1`) — ~170 → ~17 schemas on 8GB scrap.
2. **Backend swap** — OpenAI-compatible URL → Ollama or ROCm vLLM without rewriting agents.
3. **Repeatable harness** — scrap Session CSV + cloud timed `/v1/chat/completions`.

---

## 6. Demo video

- **URL:** https://github.com/doteyeso-ops/caprigo/blob/main/docs/demo/Caprigo_AMD_Demo.mp4  
- Caprigo operator surfaces + AMD/RX580 narrative (VO).  
- Length **~72s** (contest recommends 3–5 min; core path recorded).

---

## 7. Supplementary

See [POSTER.md](POSTER.md) · checklist [SUBMISSION_CHECKLIST.md](SUBMISSION_CHECKLIST.md).
