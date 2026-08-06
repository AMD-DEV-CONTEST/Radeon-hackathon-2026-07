> ⚠️ STALE：本文件已归档，唯一信源见 docs/TRUTH.md。
# ScrewShell — Presentation Outline (10 slides)

**Deliverable ④ (PPT/Poster)** · All English · Visual style: dark tech theme, AMD red accents.

---

### Slide 1 — Title
- **ScrewShell** — Private Local Knowledge Investigator on AMD Radeon
- Track 2 · AMD AI DevMaster Hackathon 2026
- One-liner: *"One Radeon GPU. One frozen base. Unlimited community skills."*
- Footer: Radeon PRO W7900 48 GB · ROCm 7.2.4 · zero remote API

### Slide 2 — The Problem
- Sensitive knowledge (contracts, code, design docs) can't go to cloud AI
- Real questions need an *agent* (plan → retrieve → read → cite), not one LLM call
- Multi-skill agents naively cost N× VRAM or N× reload time

### Slide 3 — The Product (demo screenshot)
- Full UI screenshot: chat + plan panel + expert badge + evidence citations
- Callouts: "skill-tagged plan", "LoRA expert per step", "file#L42-L58 citations", "audit log"

### Slide 4 — Architecture (diagram from SPEC §2)
- Orchestrator (self-built ReAct) → Router → MoL core
- RAG / Tools / Evidence / Memory / Safety layers
- Highlight box: MoL Inference Core = the 40-pt optimization

### Slide 5 — MoL: Mixture-of-LoRA (the key idea)
- Frozen Qwen3.6-27B-Q4_K_M GGUF resident in VRAM (served by llama.cpp) + hot-swappable GGUF LoRA experts
- btl3 (tool/code) · cybersec (security, NEW) · teichai (planning) · rag_n7 (doc/evidence) — all community, Apache-2.0
- "Drop in a GGUF adapter → gain a skill"

### Slide 6 — Radeon Benchmark (the money slide)
- Architecture win on W7900 / ROCm 7.2.4 (llama.cpp, HIP build):
  - VRAM: **~50 GB → ~17 GB** (3 skills, one frozen 27B base + MB-scale adapters)
  - Switch: full 27B reload = **seconds** → adapter swap on resident base (**sub-second**; path-D latency being benchmarked)
  - Throughput: ~14–18 tok/s base, comparable with an active adapter
- Small print: the 8.04 ms / 1,305× figure was the 9B-PEFT stack — **not** carried to the 27B llama.cpp stack; path-D numbers land in `bench/` (see `bench/BENCHMARK_STATUS.md`).

### Slide 7 — 5/5 Core Capabilities
- Table: Local RAG · Tool calling · Multi-step planning · Multi-turn memory · Permission control
- Each row: one-line implementation + how it's shown in the demo

### Slide 8 — Private & Auditable by Construction
- Workspace sandbox · tool/path allowlists · secrets blocklist
- Dangerous-command rejection · JSON audit log · zero telemetry
- Screenshot: blocked `~/.ssh` read + audit panel

### Slide 9 — ROCm Engineering Notes
- llama.cpp HIP build — ROCm-native bf16, no fp64 fallback on RDNA3 · Qwen3.6 GGUF (no GDN-Triton JIT needed)
- `enable_thinking=False` → 0.2 s agentic JSON acks
- Live `rocm_smi` observability inside the agent UI

### Slide 10 — Close / Roadmap
- Recap one-liner + repo URL + Apache-2.0
- Roadmap: learned router · self-trained LoRA-Doc expert · Verifier subagent
- "Community LoRA ecosystem × Radeon VRAM = practical local multi-skill agents"

---

**Poster alternative**: Slides 3+4+6 merged into one A1 layout (product shot top, architecture middle, benchmark numbers bottom-right in AMD red).
