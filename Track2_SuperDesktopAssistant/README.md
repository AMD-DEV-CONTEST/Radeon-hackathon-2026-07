# Super Desktop Assistant

> **AMD AI DevMaster Hackathon · Track 2: Development & Local Deployment of Private AI Agents**
> Fully local, multimodal AI agent on an AMD Radeon PRO W7900 (ROCm)

A local-first multi-model intelligent scheduling desktop assistant. Through a single chat interface (CLI / Web / Desktop), the user issues commands by **text or voice**, and the system automatically:

**understands intent → generates a task DAG → routes to domain foremen → parallel-schedules multimodal LLMs / TTS / STT / image generation → returns results.**

All core inference runs **locally on AMD Radeon GPUs (ROCm)** — no cloud APIs for core functions.

---

## 📦 Submission Materials (Track 2)

| # | Required deliverable | File |
|---|---|---|
| 1 | **Project Specification Document** (application scenarios, architecture diagram, core capabilities, model & local deployment plan, ROCm inference-speed optimization) | [`docs/Project_Specification.md`](docs/Project_Specification.md) |
| — | ROCm / vLLM optimization report with benchmarks (bonus: inference-speed optimization) | [`docs/ROCm_Optimization.md`](docs/ROCm_Optimization.md) |
| 2 | **Project Source Code** (complete repo; README with environment config, startup guide, dependency list) | [`source/super-desktop-assistant/`](source/super-desktop-assistant/) |
| 3 | **Demo Video** (3–5 min, actual on-GPU operation) | [`demo/demo_video.mp4`](demo/demo_video.mp4) |
| 4 | **Supplementary: PPT** | [`Super_Desktop_Assistant__Project_Achievement_Report.pptx`](Super_Desktop_Assistant__Project_Achievement_Report.pptx) |

---

## 📁 Repository Layout

| Path | Description |
|---|---|
| `docs/Project_Specification.md` | Track 2 project specification (scenarios, architecture, capabilities, models, GPU optimization) |
| `docs/ROCm_Optimization.md` | Detailed ROCm/vLLM optimization report with measured benchmarks |
| `source/super-desktop-assistant/` | Complete source code of the agent framework |
| `demo/demo_video.mp4` | 3–5 min demo video (actual on-GPU run) |
| `presentation/` | PPT design notes |
| `Super_Desktop_Assistant__Project_Achievement_Report.pptx` | Final PPT (supplementary material) |

---

## 🏗 System Overview

![Four-layer architecture](docs/architecture.png)

```
User input (text / image / audio)
  → [L1] UserAgent        (truncation, entity extraction, config-intent intercept)
  → [L2] Supervisor       (Planner generates DAG → Executor topo-sort → Router)
  → [L3] Foremen          (LLM / Vision / Speech / Image foremen with tool chain)
  → [L4] MCP contract     (multi-backend APIs, unified error handling)
  → [Memory] public/task memory
```

- **Planner** (LLM) decomposes intent into a structured JSON task DAG.
- **Executor** runs DAG with topo-order, parallelism, timeout, retry, deadlock detection.
- **Foremen** execute nodes: LLM/Vision via vLLM, Speech via local TTS/STT, Image via ComfyUI.
- **8 agent tools**: `get_shared_memory`, `read_file` (PDF-aware), `write_file`, `search_code`, `list_files`, `generate_image`, `add_note`, `add_discovery`.

**Covered Track-2 capabilities** (≥2 required): ✅ Tool invocation · ✅ Multi-step task planning (DAG) · ✅ Local multi-turn memory · ✅ Local deployment on Radeon GPU.

---

## ⚡ Design Philosophy — *Rewrite → Activate → Maximize*

1. **⚡ Real-time prompt rewriting** — before every node executes, the system **rewrites the user's plain request into a domain-optimized prompt**. A simple *"draw a silver-haired girl"* becomes `anime girl, silver long hair, very awa, masterpiece, best quality…`, and long-context prompts are dynamically adjusted from upstream results. This is what unlocks far more from each local model.
2. **🧠 Expert activation** — each task **activates the best-fitting local expert** (LLM / Vision / Speech / Image foremen). The right model handles the right job, running in parallel where the DAG allows.
3. **🚀 Maximize local AI utilization** — local-first routing + DAG parallelism + ROCm optimizations keep the AMD GPU fully busy and the pipeline responsive, minimizing cloud dependency and latency.

---

## 🏆 Key Highlights

- **⚡ Real-time prompt rewriting** — plain commands are rewritten into expert-grade prompts at runtime, maximizing each local model's output quality.
- **🧠 Expert activation** — every task activates the right local expert (LLM / Vision / Speech / Image), orchestrated as a parallel task DAG.
- **🚀 Maximize local AI utilization** — local-first scheduling keeps the AMD GPU fully busy; **ROCm-optimized vLLM: +11% generation (13.7 tok/s) and +109% long-context prefill**.
- **Fully local & private** on AMD Radeon PRO W7900 (ROCm 7.2.3) — no cloud APIs for core functions; data never leaves the machine.
- One command schedules **multiple models in parallel** — text, vision, speech, and image in a single chat.

---

## 🚀 Quick Start (source)

See [`source/super-desktop-assistant/README.md`](source/super-desktop-assistant/README.md) for the full guide.

```bash
# 1. Start vLLM (Qwen2.5-VL-32B-AWQ, local multimodal LLM + vision)
/opt/start_vllm.sh

# 2. Start audio server (Kokoro TTS + faster-whisper STT)
cd /opt/audio && python3 server.py &

# 3. Start ComfyUI (Qwen-Image image generation)
cd /opt/ComfyUI && python3 main.py --listen 0.0.0.0 --port 8188 --gpu-only &

# 4. Run the assistant
cd source/super-desktop-assistant
pip install -r requirements.txt
python app.py --web        # Web UI at :7860
python app.py --cli        # or CLI
```

---

## 🚩 How to Submit (to the official repo)

1. **Fork** [`AMD-DEV-CONTEST/Radeon-hackathon-2026-07`](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07).
2. Add this submission folder into the fork (e.g. as `submissions/super-desktop-assistant/` or a top-level folder named after the app).
3. Open a **Pull Request** to `AMD-DEV-CONTEST/Radeon-hackathon-2026-07:main`.
4. **PR title format**: `Track 2, <Team name or your name>, Super Desktop Assistant`.
5. All materials and the PR description in **English**.

---

## 👥 Team

> **Participant**: 张元昊 (Yuanhao Zhang) — individual
> **GitHub**: [zhuimeng1233](https://github.com/zhuimeng1233)

---

> Application name: **Super Desktop Assistant**
> PR title: `Track 2, Yuanhao Zhang, Super Desktop Assistant`
