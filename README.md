# 🎬 Duanmai (断脉) · The Stateful AI Screenplay Studio

**[🇨🇳 中文完整文档 →](README_zh.md)** ｜ *AMD Radeon Hackathon 2026 · Track 2 (Agentic AI) · AMD Developer Cloud*

> **"We didn't build another chatbot. We built a digital showrunner's brain — and it runs entirely on AMD silicon."**

Duanmai is the first **stateful, agentic co-writing workbench** that walks an author from a single spark of an idea all the way to a shoot-ready screenplay: **Idea → Story → Outline → Script → Storyboard → Panels**. No cloud APIs. No data leaving the machine. **100% local inference** on an AMD Radeon™ PRO W7900 (48 GB, ROCm/HIP) with Qwen3.6-35B-A3B (Q8_0) at ≈70 tokens/s.

![ROCm](https://img.shields.io/badge/ROCm-7.2.1-ED1C24) ![GPU](https://img.shields.io/badge/GPU-Radeon_PRO_W7900_48GB-ED1C24) ![llama.cpp](https://img.shields.io/badge/Inference-llama.cpp_(HIP)-blue) ![UI](https://img.shields.io/badge/UI-Streamlit-FF4B4B) ![Context](https://img.shields.io/badge/Context-32K-green)

---

## 🌌 The Paradigm Shift: Amnesiac Chatbots vs. A Studio That Remembers

Every AI writing tool on the market is a **stateless dialog box**: after ten turns it forgets your protagonist's flaw, your world's rules, your ending. Duanmai shatters this with a **Persistent Creative Matrix** — a structured "AI Brain" whose contents are **injected into every single inference call**:

| Brain Module | What it does |
|---|---|
| 🧱 **Core Pillars** | 8 immutable story DNA fields (Theme / Want / Need / Core Fear / Stakes / Tones) |
| 🧠 **Permanent Memory Pool** | Iron-clad rules the model can *never* violate; auto-tidy, auto-dedup, length-guarded |
| 🕳️ **Plot-hole ("Pit") Tracker** | Unresolved threads on a Kanban board; one-click **🪄 "AI, fix this pit"** |
| ✨ **Inspiration Wall** | Captures your best ideas mid-chat and immortalizes them in context |
| 🎭 **Character Profiles** | Name / role / personality / visual signature / arc — anti-OOC enforcement |
| 🧵 **Foreshadowing Tracker** | Plant ↔ payoff table with recovered/unrecovered status |
| 📊 **Emotion Curve** | Per-act audience-reaction word + intensity slider, rendered as a live chart |

The model answers through a proprietary **`<state_update>` XML protocol**: memories added, pits opened/closed, inspirations captured — the UI updates itself *silently* while you write.

---

## 🚀 Feature Tour, Block by Block

### 🎛️ Top Bar — The Mission-Control HUD
* **Seal banner** (project identity) + **live W7900 KPI**: real VRAM usage (torch.hip → rocm-smi → sysfs multi-layer fallback) and live decode speed (tok/s).
* **Three layout modes**: ⛶ Full-Window (writing long scripts), 🖥 Full-Screen (pure focus), ↩ Default (three-pane studio).

### 📋 Sidebar — Global Control Deck
* **Six-stage pipeline radio** with **smart progress detection**: on launch the studio auto-locates you to the first unsealed stage; switching stages **auto-seals** the current document.
* **🧠 Brain toggle** (collapse left pane), **🧼 De-AI-Flavor master switch**.
* **🎯 Attention Anchors**: compresses pillars + memories into a "talisman" injected every call — our weapon against long-context attention dilution.
* **📦 Project Export/Import**: download/restore the *entire* studio state as one JSON (distinct from cloud-side 💾 Save / 📂 Load).
* **🏆 Contest-Material Generator**: one click produces README outline, 3-min demo narration script, and an AMD/ROCm optimization highlight list.
* **🩺 llama.cpp health probe**.

### 🧠 Left Pane — The AI Brain (six tabs, see matrix above)
Every field ships with **❌ bad-example / ✅ good-example tooltips** — ~40 controls are self-teaching for first-time users.

### 💬 Middle Pane — The Co-Creation Floor
* **Idea Seed Card** (Idea stage): six guided questions with example bubbles; the AI then enters **Strict-Mentor Mode** (≤3 diagnoses, ≤3 questions, ≤3 options) with a **hard convergence rule** — max 2 Q&A rounds, then it must output the Finalization Card and point you to the green "Lock & Advance" button. No infinite questioning. Ever.
* **Writing Toolbox** (one click, acts on the canvas): ✨ Polish · 🎈 Expand · ️ Condense · 🏮 Tang-Dynasty Dialogize · 🎬 Shot-Listify · 🔍 Logic Self-Check (cross-audits against memories/characters/foreshadowing).
* **🧠 Chain-of-Thought viewer**: every reply carries an expandable "deep thinking" panel (`--reasoning-format deepseek`).
* **Writer-grade input**: Enter = newline, **Ctrl+Enter = send** (global JS binding), with an on-screen hint for beginners.

### 📝 Right Pane — The Canvas
Editable stage document with word count, **📤 .md export**, **📥 adopt last AI reply**, **🔒 seal-as-final** (sealed stages become immutable context for the next stage), plus the sealed archive.

---

## 🕵️ Anti-"AI-Flavor" Engine (Bypass Zhuque / GPTZero-class Detectors)

Detectors read three signals: **perplexity, burstiness, and model fingerprints**. We attack all three, in four layers:

1. **Prevent** — 🧼 mode injects a "gritty human screenwriter" iron-law prompt (wasted details, subtext-only dialog, banned AI-fingerprint words) **plus** high-entropy sampling (temp 1.15 / top_p 0.98 / presence 0.6 / frequency 0.3) to roughen the logits distribution.
2. **Treat (LLM)** — 🧼 Deep-Humanize rewrite: a 20-year editor persona rewrites *style only*, plot untouched.
3. **Treat (code)** — 🧨 **Physical Washing**: pure-Python punctuation destruction, filler injection, boilerplate beheading. No LLM, no fingerprints.
4. **Measure** — 🧪 offline AI-flavor scorer (burstiness + blacklist + connective-openers + direct-emotion density) with a **🔍 high-risk sentence locator** — fix 10–20% of sentences and flip the verdict.

---

## ⚙️ The Two Scripts — Engineering Notes

### 📜 `setup.sh` — Zero-Touch AMD Cloud Provisioner
> ⚠️ **This script is purpose-built for the AMD Developer Cloud (Radeon PRO W7900 / ROCm 7.2.1) instance. It is provided as a reference; for any other GPU or environment, adapt the CMAKE targets, model paths and mirrors yourself.**

What it does, step by step: activates `/opt/venv` → repairs cloud DNS + installs tmux/aria2 → installs `modelscope/streamlit/requests` → wires the `/persistent` SFS volume → downloads the 35 GB Q8_0 GGUF via ModelScope → **compiles llama.cpp with `GGML_HIP=ON -DAMDGPU_TARGETS=gfx1100`**, with npmmirror + hf-mirror fixes and a pre-seeded `index.html` to kill the infamous npm hang → deploys the WebUI.

### 🎬 `start.sh` — The Cinematic Inference Launcher
We made a deliberate, philosophical choice: **we did NOT tune for maximum TPS. Screenwriting needs room to think.** Raw speed was traded, on purpose, for **32K whole-story vision, deep chain-of-thought, and structural stability**:

| Parameter | Value | Why (creative-first philosophy) |
|---|---|---|
| `-ngl 999` | full offload | the whole 35B model lives in W7900 VRAM; zero CPU bottleneck |
| `-c 32768` | 32K context | the AI "sees" all six acts at once — no amnesia, no drift |
| `--parallel 1` | single slot | one author, one undivided 32K slot (no split-context truncation) |
| `--flash-attn on` | Flash Attention | makes 32K attention fit in 48 GB |
| `--cache-type-k/v q8_0` | quantized KV | the trick that buys us the 32K window |
| `--threads 16` | EPYC 9334 vCPUs | fast prompt ingestion |
| `-b 1024 -ub 512` | batching | stable long-prompt processing |
| `--jinja` + `--reasoning-format deepseek` | native template + CoT | surfaces the model's inner monologue in the UI |
| `--no-mmap` | no mmap | rock-solid on containerized SFS storage |

The script then: kills stale processes → launches `llama-server` in tmux with **smart health-polling** (up to 180 s) → launches Streamlit headless → spins a **Cloudflare tunnel** and prints a public demo URL → renders a full service-status report.

---

## 💻 Environment & Numbers

| | |
|---|---|
| GPU | AMD Radeon PRO W7900, 48 GB (gfx1100) |
| CPU | AMD EPYC 9334 (16 vCPU) |
| ROCm / HIP | 7.2.1 |
| Model | Qwen3.6-35B-A3B-Q8_0 (~35 GB, fully offloaded) |
| Decode | ≈70 tok/s · VRAM ≈36/48 GB |

## 🏁 Quick Start
```bash
bash setup.sh   # once: deps + model + ROCm build
bash start.sh   # every time: engine + WebUI + tunnel
```

## 📁 Repo
`app.py` (the entire studio, single file) · `setup.sh` · `start.sh` · `README.md` · `README_zh.md`

## 🎥 Demo

![Main UI](assets/01_main_ui.png)
*Left: the AI Brain matrix · Center: the Co-Creation Floor · Right: the Canvas. The top HUD shows live W7900 VRAM & decode speed.*


## 🙏 Acknowledgements
Forged with sweat and ROCm. Thanks to AMD Developer Cloud, llama.cpp, Streamlit and Qwen.
