# 1bit Jarvis — Private AI Agent
## AMD AI DevMaster Hackathon 2026 · Track 2

---

### 🎯 What It Is
A fully **local, private AI agent server** — part of the open-source 1bit.systems project.
Runs entirely on your hardware. Zero data leaves the device.

### 🔧 Core Capabilities

| Capability | Implementation |
|-----------|---------------|
| **🧠 Multi-turn Memory** | Server-side per-session persistence — recalls context across requests |
| **📚 RAG (Knowledge Base)** | Full-text search over local markdown documents, upload/search over HTTP |
| **🔧 Tool Invocation** | `search_knowledge`, `get_time`, `add_note`, `list_models` — permission-gated with local audit log |
| **🗺️ Multi-step Planning** | Decomposes complex requests into subtasks, routes to best-fit model, synthesizes grounded answers |
| **🔒 Privacy** | Tools classed `safe`/`sensitive`; all actions logged locally; no external API calls |

### 🏗️ Architecture
```
Client (curl / Mobile app / Web UI)
        │ HTTP — OpenAI-compatible /v1/chat/completions
        ▼
jarvis/server.py ── session memory ── knowledge base (RAG)
        │                            ▲
        ├─ tool-call loop ───────────┘
        │     permission gate + audit log
        ├─ multi-step planner
        │     decompose → route → synthesize
        └─ routing layer
              ├─ NPU backend (AMD XDNA 2, local)
              └─ GPU backend (ROCm/Ollama, works with AMD Radeon Cloud)
```

### 🚀 AMD Radeon GPU / ROCm Deployment

Deployed and validated on **AMD DevCloud** (DigitalOcean-powered):

| Component | Spec |
|-----------|------|
| **GPU** | AMD Instinct MI300X VF — **192 GB HBM3 VRAM** |
| **Throughput** | Qwen3-4B LoRA training: **3.18 it/s** |
| **Software** | ROCm 6.2 + PyTorch 2.5.1 — full `device_map="auto"` support |
| **Inference** | GPU backend speaks OpenAI-compatible API — works with Ollama, vLLM, or Radeon Cloud API |

### 📊 Benchmarks
- **12,900 training steps** completed on MI300X in 72 minutes
- **LoRA rank 16** adapter trained on Alpaca dataset
- **Native adapter size**: 132 MB (504 modules, 1BP format)
- Inference runs on any ROCm-capable AMD Radeon GPU

### 🔗 Links
- **Source**: [github.com/bong-water-water-bong/1bit-systems](https://github.com/bong-water-water-bong/1bit-systems)
- **Agent code**: `jarvis/` directory
- **Team**: Solo developer — bong-water-water-bong

---

*Made with ❤️ for the AMD AI DevMaster Hackathon 2026*
