# omima — Astral Metro Domain

> **Track**: Agentic AI (Track 2)  
> **Team**: kon (Luma registered name; no team name filled)  
> **Application**: omima — personal agent network on edge + constellation nodes  
> **Event**: 2026 AMD AI DevMaster Hackathon  
> **Submit**: PR → `AMD-DEV-CONTEST/Radeon-hackathon-2026-07`

**Order Made In Mayhem, Always.**

omima is a full **efficiency-engineering** stack—not another cloud chatbot. It starts from **six classes of application needs**, implements them as system algorithms, and converges on **three pillars**: (1) systematized protocols & algorithms, (2) internalized model settings (1B / 9B / 35B job roles), (3) an internalized multi-agent work method — **ideate → argue → plan → execute → review**, serial-stream with parallel steps. **Harness**, **loop engineering**, and **hardware staffing** are planned together so delivery is auditable, bounded, and high-satisfaction. All three job models were post-trained and validated on **AMD Instinct MI300X (ROCm)** using AMD's pre-contest compute grant — a lab setup, not the product's runtime configuration.

Canonical thesis (Chinese): **`core-thesis.md`**. Demo: **VOX explainer video** (3–5 min main / 90s short) per `demo-storyboard-vox.md` — infographic motion + voiceover, covering needs → three pillars → one task walkthrough → AMD numbers.

---

## What this is / is not

**Is:**

- Demand-driven design from six application classes (through a ~28-task spectrum)  
- Three-pillar convergence: protocol/algorithms · internalized LLMs · five-beat multi-agent method  
- Efficiency engineering across **harness · loop · hardware**  
- Edge memory sovereignty + constellation of **stateless** star-nodes  
- Job models (1B / 9B / 35B) trained so roles can go online on ROCm  

**Is not:**

- A single-GPU TPS trophy demo  
- Plugin pile without governance or work method  
- One 70B model for every job on every device  

**One line:** *Needs → algorithms → three pillars → satisfactory delivery; hardware and ROCm metrics are the staffing slice, not the whole product.*

---

## Architecture (short)

omima is a **distributed heterogeneous star-network** designed on an **AMD compute base**. Three layers, joined by the **Porphyrion protocol**:

```text
┌──────────────────────────────────────────────────────────────┐
│ Layer 3 · Model layer — on demand                             │
│   1B router (always-on: memory + routing)                     │
│   9B worker / 35B strategist (job models, spun up as needed:  │
│   9B resident on CPU ECS · 35B on GPU ECS on-demand)          │
│   all three post-trained on AMD MI300X (ROCm) —               │
│   pre-contest compute granted by AMD; not a product config    │
├──────────────────────────────────────────────────────────────┤
│ Layer 2 · Star-network POS layer — cheap compute              │
│   stateless ECS / cloud-PC nodes run Xagent workers           │
│   (register · execute · reply · forget)                       │
├──────────────────────────────────────────────────────────────┤
│ Layer 1 · Harness / orchestration layer — DEMO builds         │
│   Xagent (desktop) · omima APK (mobile)                       │
└──────────────────────────────────────────────────────────────┘
        ▲             Porphyrion protocol            ▲
        └─ stable long-lived connection + event callbacks ─┘
           works even on cloud PCs with no port 22
           and no public IP
```

| Role | Size | Job | Placement (mode) |
|------|------|-----|------------------|
| Polaris router | **1B** | Memory + route + task stripping | Always-on device (phone SoC; optional Ryzen AI) |
| Worker | **9B** | Tool loops, snappy local work | Laptop / CPU star-node (Ryzen AI product target) |
| Strategist | **35B-class MoE** | Hard reasoning, private inference | MAX-class unified-memory host (product design); **MI300X** = pre-contest training lab |
| Star-node POS | — | Register · execute · reply · forget | 1C1G+ ECS / cloud PCs + Xagent |

- **Layer 1 (harness)**: **Xagent** (desktop / headless star-node) and **omima APK** (mobile) — **both are DEMO builds**, not release-ready engineering. Tools pass IronLaw before execution; Gateway handles presence, events, replay.  
- **Layer 2 (POS)**: cheap stateless compute; nodes join/leave freely.  
- **Layer 3 (models)**: 1B routes, 9B/35B do the job — models are used **on demand**, not all resident. All three were post-trained on **AMD MI300X (ROCm)** during AMD's pre-contest compute grant; that lab setup is **not the product's runtime configuration**.  
- **Porphyrion**: stable long-lived connection + event callbacks — the network is reachable even on cloud PCs that expose **no port 22 and no public IP** (typical cloud-PC defect). Its six **sys-hooks** (register / invoke / memory / ironlaw.check / reply / handoff) are the protocol primitives covering all agent-to-agent collaboration patterns — evolved from the production-proven UnionAgents protocol, aligned with **A2A** (task delegation) and **MCP** (tool calling), so heterogeneous nodes (different models, hardware, hosts) interoperate in one protocol domain. Its protocol schemas double as training-data ground truth.

Full mode write-up (Chinese, judging-oriented): **`amd-rocm-technical.md`**.  
Full paper: **`main-paper.md`**.

---

## AMD GPU / ROCm — what we actually ran

Post-training and FPS tables are ordinary ROCm craft. We do them because the **mode requires three job sizes to ship**. Main measured chain: **MI300X Notebook (AMD × ModelScope)**.

| Item | Result | Stack |
|------|--------|--------|
| Tool-calling gate | **8/9** on 35B-A3B | vLLM ROCm |
| FP8 vs BF16 (C=3 agg.) | **~195 vs ~118 tok/s (+65%)**, tools OK | vLLM ROCm |
| omima-35B LoRA | Loss ~1.88→**0.96**, ~**1h11m** train; serve ~**59–65 tok/s** short | PEFT + vLLM on MI300X |
| omima-9B LoRA | Loss ~1.82→**0.79**, ~**57 min** | MI300X |
| 9B CPU path | GGUF Q8 ~**13 t/s**, tool-call OK | llama.cpp |
| Confidence gate idea | unified threshold ~**0.72** | logprobs on protocol set |

**Weights / data (ModelScope):**

- https://modelscope.cn/models/kooooon/omima-35B  
- https://modelscope.cn/models/kooooon/omima-9B  
- https://modelscope.cn/datasets/kooooon/omima-distilled  
- https://modelscope.cn/datasets/kooooon/omima-training-data  

**Evidence index:** `evidence/INDEX.md`

### Scoring-oriented map (≈40 pts AMD block)

| Focus | Where in this project |
|-------|------------------------|
| Local inference | MI300X serving 35B FP8 + LoRA jobs; 9B on CPU GGUF |
| Speed methods | FP8 vs BF16 quantified; MoE strategist choice; job LoRA still servable |
| ROCm toolchain | ROCm · vLLM · PEFT · llama.cpp · `rocm-smi` · ModelScope |

Product placement on Ryzen AI / MAX-class boxes is **mode design** for the constellation; this contest’s **measured** GPU story is MI300X (training/validation, pre-contest compute from AMD) — not an omima product configuration. We do not substitute cloud API latency for ROCm throughput.

---

## Application value (Agentic track)

- **Privacy**: cloud/large models receive stripped tasks; memory stays at Polaris (`I(memory; outbound) → 0` design).  
- **Cost structure**: cache-hit path in real usage — **5.63B tokens / ¥444.55** (application ledger, not a GPU score).  
- **Scale-out**: more star-nodes = more capabilities without rebuilding a monolith.  
- **Safety**: IronLaw at harness layer (deny before execute), not “model please behave”.

---

## Demo (3–5 min)

**Form: VOX explainer video** per `demo-storyboard-vox.md` — six needs → three pillars → harness·loop·hardware → one task through five beats → AMD measured numbers (FP8 +65%, tool-call 8/9). Infographic motion + Chinese voiceover, 3–5 min main cut (90s short available).

Pitch outline: **`pitch-deck.md`**. Thesis: **`core-thesis.md`**.

---

## Reproduce (skeleton)

```bash
# On ROCm MI300X Notebook
rocm-smi
# Serve FP8 strategist base or LoRA (paths on Notebook)
# Train job adapters
bash scripts/finetune_35b_lora.sh --fp8
# CPU worker
./llama-server -m omima-9B-v2.Q8_0.gguf --port 18090
```

Logs and construction notes live under the project `logs/` / `DOCS/references/` trees (see evidence index).

---

## Current boundaries

- Consumer AMD SKUs (Ryzen AI laptop / MAX 395+): **design targets**, not fully instrumented contest benches.  
- MTP / FP8 KV-cache / AITER on–off ablation: **not claimed complete**.  
- Multi-10k-sample second-round LoRA: **datasets prepared**; shipped weights prove **first-round job LoRA**.  
- 1B product features roll out by stage; routing/memory firewall is the role definition.

---

## Team

**kon** — omima / Xagent / Porphyrion author.

## License

See repository license files for each component. Third-party models keep their original licenses (e.g. Apache-2.0 / MIT bases).

---

## Document set

| File | Role |
|------|------|
| `00-PACKAGE.md` | Chinese package index (canonical checklist) |
| `README.en.md` | This file |
| `main-paper.en.md` | Full technical paper (**English**) |
| `main-paper.md` | Full technical paper (Chinese original) |
| `amd-rocm-technical.md` | AMD/ROCm technical chapter |
| `pitch-deck.md` | Slides |
| `demo-script.md` | Demo script (VOX narration) |
| `demo-storyboard-vox.md` | **VOX storyboard (production storyboard)** |
| `PR-DESCRIPTION.md` | PR title/body |
| `evidence/INDEX.md` | Evidence map |
