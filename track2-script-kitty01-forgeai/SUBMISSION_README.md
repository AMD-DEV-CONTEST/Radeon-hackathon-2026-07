# ForgeAI 🔥 — Track 2 Submission

**Team:** Script-Kitty01  
**Track:** 2 — Development & Local Deployment of Private AI Agents  
**Date:** August 6, 2026

---

## Deliverables

| # | Item | Link |
|---|---|---|
| 1 | **Project Spec (PDF)** | [`PROJECT_SPEC.pdf`](./PROJECT_SPEC.pdf) |
| 2 | **Source Code** | https://github.com/Script-Kitty01/devMaster_amd |
| 3 | **Demo Video** | https://drive.google.com/drive/folders/1PHfQT8CkQi6C3Jq6fY6C_3cnXVxyGfLl |
| 4 | **PPT** | [`ForgeAI_PPT.pptx`](./ForgeAI_PPT.pptx) |

---

## About ForgeAI

ForgeAI is a conversational multi-agent AI engineering assistant that analyzes codebases using a team of 6 specialized agents — all running locally on AMD Radeon GPUs via ROCm/HIP. Upload a repository, ask questions in natural language, and get a comprehensive analysis with cross-reviewed findings.

### Agent Team

| Agent | Role | Tools |
|---|---|---|
| 🧠 Planner | Orchestrates analysis, decomposes queries | — |
| 🔒 Security | Finds vulnerabilities (OWASP, CWE, secrets) | Bandit, Semgrep |
| ⚡ Performance | Spots bottlenecks & optimization | Code search |
| 🏗️ Architecture | Evaluates design patterns & modularity | Git analyzer |
| 🚀 DevOps | Checks containerization & deployment | Dockerfile validator |
| ⚖️ Consensus | Cross-review debate & final verdict | — |

### Tech Stack

- **LLM:** Llama 3.2 3B Instruct (Q4_K_M GGUF) via llama-cpp-python
- **Agent Framework:** LangGraph (StateGraph with parallel dispatch)
- **RAG:** ChromaDB + sentence-transformers on ROCm GPU
- **UI:** Streamlit
- **GPU:** AMD ROCm 7.2.1 / HIP on Radeon gfx1100 — 124 tok/s

### GPU Performance

| Metric | Value |
|---|---|
| Token Generation | 124 tok/s |
| Prompt Evaluation | 17.4 tok/s |
| Model Load Time | 575 ms |
| VRAM Usage | 2.57 GB / 51 GB |

---

## Quick Start

```bash
git clone https://github.com/Script-Kitty01/devMaster_amd
cd devMaster_amd
python -m venv .venv && source .venv/bin/activate
pip install -e .
pip install llama-cpp-python
streamlit run src/ui/chat_app.py
```

Full instructions in the [source repo README](https://github.com/Script-Kitty01/devMaster_amd).
