# 🎬 Duanmai (断脉) · AI Screenplay Co-Creation Workbench

**[中文说明 →](README_zh.md)** ｜ *AMD Radeon Hackathon 2026 · Track 2 – Agentic AI · AMD Developer Cloud*

Duanmai is a **stateful agentic AI co-writing studio** that walks an author from a one-line idea all the way to a shootable screenplay — **Idea → Story → Outline → Script → Storyboard → Panels** — while running **100% locally** on an AMD Radeon™ PRO W7900 (ROCm/HIP) with **Qwen3.6-35B-A3B (Q8_0)** via llama.cpp at **≈70 tokens/s**.

Unlike stateless chatbots, Duanmai keeps a **structured creative brain**, so the AI never forgets your settings even in very long sessions.

## ✨ Key Features

- **Six-stage agentic workflow** with automatic *stage sealing*: each finished stage is locked and becomes immutable context for the next one.
- **The AI Brain (left panel)**: Permanent Memory Pool, Plot-hole ("Pit") Tracker, Inspiration Wall, Character Profiles, Foreshadowing Tracker, and a 6-act Emotion Curve — all auto-injected into every LLM call.
- **Strict-mentor co-writing protocol**: ≤3 diagnoses / ≤3 questions / ≤3 options per turn; the model returns a `<state_update>` XML block that the UI parses to update memories/pits/inspirations automatically.
- **Anti-"AI-flavor" suite** (to pass AI-text detectors): generation-time writing iron-rules + high-entropy sampling (temp 1.15), an LLM "deep humanizer" rewrite, a pure-Python "physical washing" pass, and an offline AI-flavor scorer with high-risk sentence locator.
- **Beginner-friendly UX**: seed card with ❌/✅ examples, tooltip hints on ~40 controls, Enter = newline / Ctrl+Enter = send, three layout modes, one-click memory tidy.
- **AMD performance dashboard**: live VRAM (torch.hip with rocm-smi/sysfs fallback) + decode speed in the header.

## 🏗️ Architecture

```
Browser ──HTTP──▶ Streamlit WebUI (:8501, single-file app.py)
                     │ OpenAI-compatible API
                     ▼
            llama.cpp server (:8000, HIP / gfx1100)
                     ▼
       Qwen3.6-35B-A3B-Q8_0.gguf (~35 GB, fully offloaded)
```

## 💻 Environment & Performance

| Item | Value |
|---|---|
| GPU | AMD Radeon PRO W7900, 48 GB (gfx1100) |
| CPU | AMD EPYC 9334 (16 vCPU, cgroup) |
| ROCm / HIP | 7.2.1 |
| Model | Qwen3.6-35B-A3B-Q8_0 (llama.cpp) |
| Decode speed | ≈70 tok/s |
| VRAM footprint | ≈36 / 48 GB |

## ⚡ AMD-specific Optimizations

- llama.cpp built with `GGML_HIP=ON -DAMDGPU_TARGETS=gfx1100`
- `-ngl 999` (full GPU offload), `--flash-attn on`
- `--cache-type-k/v q8_0` → full **32K context** inside 48 GB
- `--threads 16 -b 1024 -ub 512 --parallel 1 --no-mmap`
- `--reasoning-format deepseek` → chain-of-thought surfaced in the UI
- VRAM read via `torch.cuda.mem_get_info()` on HIP, multi-layer fallback

## 🚀 Quick Start

```bash
bash setup.sh   # deps + model download + llama.cpp build (ROCm)
bash start.sh   # llama-server + Streamlit + cloudflared tunnel
```

## 📁 Files

`app.py` (full WebUI) · `setup.sh` (one-click deploy) · `start.sh` (one-click launch) · `README_zh.md` (Chinese docs)



## Acknowledgements

AMD Developer Cloud, llama.cpp, Streamlit, Qwen.
