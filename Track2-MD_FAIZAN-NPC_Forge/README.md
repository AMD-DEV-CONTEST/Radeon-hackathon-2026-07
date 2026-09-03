# ⚒️ NPC Forge — Track 2 Submission

> **AMD AI DevMaster Hackathon 2026 — Track 2: Development & Local Deployment of Private AI Agents**  
> **Author:** MD FAIZAN  
> **GitHub:** [@faizangit123](https://github.com/faizangit123)

---

## 🎬 Demo Video

▶️ **[https://youtu.be/6mcwPZwesng](https://youtu.be/6mcwPZwesng)**

---

## 📦 Project Source Code

🔗 **[https://github.com/faizangit123/npc-forge](https://github.com/faizangit123/npc-forge)**

---

## 💡 What is NPC Forge?

**NPC Forge** is a 100% offline, local-first AI co-developer for indie game developers. It processes sensitive game assets — lore bibles, crash logs, and balance spreadsheets — entirely on the developer's local machine using **Ollama** (`llama3.1:8b` + `nomic-embed-text`) running on **AMD Radeon™ GPUs via ROCm**.

**Zero data leaves your workstation. No cloud calls. No subscription fees.**

---

## 🎯 Application Scenarios

- **Lore-Grounded NPC Dialogue Generation** — Write in-character dialogue using RAG over canonical lore documents.
- **Lore Consistency Checking** — Audit dialogue drafts for canon contradictions with exact source citations.
- **Crash Log Analysis** — Parse Unity/Godot stack traces with automated root-cause diagnosis.
- **Game Balance Outlier Detection** — Flag overpowered/underpowered items using z-score statistical analysis.

---

## 🏗️ Agent Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                     React 18 + Vite Frontend                          │
│            (Glass-morphism Dark UI, SSE Streaming)                    │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ HTTP / SSE (/api)
┌───────────────────────────────────▼────────────────────────────────────┐
│                     Express / Node.js Backend                          │
│                                                                        │
│  ┌──────────────────────┐   ┌──────────────────┐   ┌────────────────┐  │
│  │ 4-Stage Agent Router │   │ 4-Level Embedder │   │ VectorStore    │  │
│  │ (Deterministic Rules)│   │(GPU/CPU/JS/TF-IDF)│  │ (In-Memory RAG)│  │
│  └──────────────────────┘   └──────────────────┘   └────────────────┘  │
│                                                                        │
│  ┌─────────────┐ ┌──────────────┐ ┌──────────────┐ ┌────────────────┐  │
│  │Lore Dialogue│ │ Lore Checker │ │Crash Analyzer│ │Balance Flagger │  │
│  │  Generator  │ │(Contradiction│ │(Unity/Godot) │ │ (Z-Score Stats)│  │
│  │    (RAG)    │ │   Auditor)   │ │              │ │                │  │
│  └─────────────┘ └──────────────┘ └──────────────┘ └────────────────┘  │
└──────────────┬────────────────────────┬─────────────────────┬──────────┘
               │                        │                     │
┌──────────────▼──────┐   ┌─────────────▼──────┐   ┌──────────▼──────────┐
│   Local Ollama API  │   │  Local MongoDB DB  │   │ Local Sample Corpus │
│ (llama3.1:8b /      │   │ (LoreDoc, Chunks,  │   │ (MD, JSON, Crash    │
│  nomic-embed-text)  │   │  Conversations)    │   │  Log Files)         │
└─────────────────────┘   └────────────────────┘   └─────────────────────┘
```

---

## 🔥 Core Capabilities

| Feature | Description |
|:---|:---|
| **Lore Dialogue Generator** | RAG-powered NPC dialogue grounded in canonical lore passages |
| **Lore Consistency Checker** | Flags contradictions with Claim vs. Actual Lore citations |
| **Crash Log Analyzer** | Parses Unity/Godot stack traces with root-cause diagnosis |
| **Balance Outlier Flagger** | Z-score statistical analysis on weapon/item CSV/JSON data |
| **Retrieval Confidence Telemetry** | Transparent similarity scores, chunk counts, and confidence ratings |
| **4-Stage Deterministic Router** | Zero LLM token waste for tool selection (~1ms execution) |
| **4-Level Embedding Fallback** | GPU Ollama → CPU Ollama → ONNX JS → TF-IDF (100% uptime) |

---

## 🔴 AMD Radeon™ GPU & ROCm Optimization

```bash
# Enable ROCm acceleration for AMD Radeon GPUs (RDNA 3 / RDNA 2)
export HSA_OVERRIDE_GFX_VERSION=11.0.0
export OLLAMA_NUM_PARALLEL=4
export OLLAMA_MAX_LOADED_MODELS=2
```

| Optimization | Impact |
|:---|:---|
| VRAM Model Pinning (`keep_alive: "10m"`) | Eliminates cold-start model loading latency |
| Concurrent Model Residency | Zero model swap overhead during RAG queries |
| Deterministic Router (~1ms) | Zero LLM token waste for tool selection |
| Streaming SSE | Sub-second time-to-first-token |

### Performance (AMD Radeon RX 7900 XTX)
- **TTFT**: < 800ms
- **Generation**: ~45-60 tokens/sec
- **VRAM**: ~5.8 GB total

---

## 🛠️ Models Used

| Model | Purpose | Size |
|:---|:---|:---:|
| `llama3.1:8b` | Text generation | 4.7 GB |
| `nomic-embed-text` | Text embedding (768-dim) | 274 MB |

---

## 🚀 Local Deployment & Setup

### Prerequisites
- Node.js v18+
- MongoDB running locally
- Ollama installed locally

### Quick Start
```bash
# Pull models
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# Install & launch
cd npc-forge
npm install
npm run seed-demo
npm run dev
# Open http://localhost:5173
```

---

## 📂 Project Structure

```
npc-forge/
├── client/                  # React 18 + Vite frontend
│   ├── src/components/      # ChatWindow, Sidebar, MessageBubble, StatusBar, etc.
│   ├── src/hooks/           # useChat (SSE), useOllamaStatus
│   ├── src/services/        # API client
│   └── src/styles/          # Custom dark glassmorphism CSS
├── server/                  # Express + Node.js backend
│   ├── src/routes/          # chat, lore, conversations, health
│   ├── src/services/        # ollamaClient, embeddingService, vectorStore, agentRouter
│   ├── src/tools/           # loreDialogue, loreChecker, crashAnalyzer, balanceFlagger
│   └── src/models/          # Mongoose schemas
├── sample-data/             # Demo lore files, crash logs, weapon stats
├── PROJECT_SPECIFICATION.md # Full project specification document
└── README.md                # Setup guide & feature documentation
```

---

## 📄 Supplementary Materials

- **Full Project Specification Document**: [`PROJECT_SPECIFICATION.md`](https://github.com/faizangit123/npc-forge/blob/main/PROJECT_SPECIFICATION.md)
- **Complete README with Setup Guide**: [`README.md`](https://github.com/faizangit123/npc-forge/blob/main/README.md)

---

*Built with ❤️ for the AMD AI DevMaster Hackathon 2026 by MD FAIZAN*
