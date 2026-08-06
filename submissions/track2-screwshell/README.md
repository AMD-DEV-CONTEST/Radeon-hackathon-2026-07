# ScrewShell — Track 2 Submission

**Track 2 — Development & Local Deployment of Private AI Agents** · AMD AI DevMaster Hackathon 2026

**Hardware**: AMD Radeon PRO W7900 (48 GB) · **Runtime**: ROCm 7.2.4 · **Core inference**: 100% local, zero remote API

---

## What is ScrewShell?

ScrewShell is a **private, fully local knowledge-investigation agent** for AMD Radeon. Point it at a workspace folder and ask multi-step questions — *"What are the risks in our ROCm migration plan, and which paragraph says so?"* — and it plans the investigation, retrieves evidence with local RAG, calls read-only local tools, and returns **evidence-based answers with line-level citations** (`file.md#L42-L58`). Nothing ever leaves the machine.

Its distinctive idea is a **Mixture-of-LoRA (MoL) inference core**: one frozen 27B base model stays resident in VRAM while small, community-trained LoRA experts are hot-swapped per investigation step — giving a multi-skill agent in the VRAM budget of a single GPU.

## Where is the source code?

The complete, runnable source repository lives at:

> **https://github.com/1105s110martin-art/screwshell**

This directory (`submissions/track2-screwshell/`) is the submission entry point. It links the four required deliverables and summarizes the project.

## Submission deliverables

| Deliverable | Location | Status |
|---|---|---|
| **1. Project Specification Document** | [`docs/PROJECT_SPECIFICATION.md`](docs/PROJECT_SPECIFICATION.md) (copy of the authoritative `docs/SPEC.md`) | ✅ |
| **2. Project Source Code + README** | [`screwshell`](https://github.com/1105s110martin-art/screwshell) (full repo with English README, env config, startup guide, dependencies) | ✅ |
| **3. Demo Video (3–5 min)** | [`presentation/ScrewShell_demo.7z`](presentation/ScrewShell_demo.7z) (7z archive of the demo MP4, which exceeds GitHub's 100 MB per-file limit; extract to view) | 📹 |
| **4. PPT / Poster** | [`presentation/ScrewShell_pitch_deck.pptx`](presentation/ScrewShell_pitch_deck.pptx) | 📊 |

## Quick architecture

```
User ── Web UI (Gradio) / CLI            opencode / pi (OpenAI /v1)
          │                                      │
          ▼                                      ▼
   Orchestrator (self-built ReAct loop)     Relay Gateway (:18090)
   ├─ Task Planner → Task Card              (MoL routing + observability)
   ├─ Skill Router → activate LoRA expert
   ├─ Local RAG     → embed → retrieve → cite
   ├─ Tool Layer    → 6 read-only sandboxed tools
   ├─ Evidence Store→ claim + citations + confidence
   ├─ Safety Layer  → permission gate + audit log
   └─ MoL Inference Core (Qwen3.6-27B Q4_K_M + LoRA experts, hot-swapped)
```

## Key numbers (measured on W7900, ROCm 7.2.4)

- **MoL hot-swap**: 3 skills fit in **18.9 GB** VRAM vs ~50 GB for 3 full models (which do not fit a 48 GB card).
- **Skill switch**: control-plane toggle **~0.65 ms**; global switch **1–2.5 ms** end-to-end.
- **KV cache**: global `POST /lora-adapters` toggle preserves **99.8%** of the prefix KV cache vs a per-request `lora` override that destroys it 100% (**415×**).
- **Throughput**: base **31.0 tok/s** decode; **23.4–26 tok/s** with an active adapter.
- **P1 tuning** (`--flash-attn on --cache-type-k q8_0 --cache-type-v q8_0`): long-tail first-token latency **30–172 s → 6.3 s**.
- **Tests**: **385 passed / 3 skipped** (6 pre-existing env/order failures, not regressions).

## Contact

1105s110martin-art / ScrewShell — submitted for AMD AI DevMaster Hackathon 2026, Track 2.
