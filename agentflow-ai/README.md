# AgentFlow AI

**AgentFlow AI** is a complete offline-first autonomous multi-agent task automation platform built for the **AMD AI DevMaster Hackathon – Track 2: Agentic AI**.

It is intentionally **not** a simple chatbot.

Instead, AgentFlow AI runs a visible multi-agent workflow:

**User Request → Planner → Research → Memory → Tool Execution → Reviewer → Final Response**

## Why this project stands out
- **Autonomous multi-agent orchestration** instead of a single chat loop
- **Fully local LLM runtime** with **Ollama only**
- **Automatic model detection + fallback**
- **Offline RAG** over uploaded PDFs and notes using **ChromaDB**
- **SQLite long-term memory** for conversations and benchmark telemetry
- **Execution timeline** so judges can see every agent step
- **Agent status panel** and **benchmark dashboard** for observability
- **GPU / CPU information** surfaced in the UI
- **Dark modern UI** inspired by ChatGPT + GitHub Copilot

## Core features
- Local LLM via Ollama
- Preferred model order:
  1. `qwen2.5:7b`
  2. `llama3.2:3b`
  3. `mistral:7b`
- Safe fallback when a model is missing
- Helpful warning when Ollama is offline
- Chat interface
- File upload
- PDF chat
- RAG with ChromaDB
- SQLite memory
- Tool calling
- Conversation history
- Task planning
- Execution timeline
- Agent status panel
- Benchmark dashboard
- GPU/CPU information

## Tech stack
### Backend
- FastAPI
- SQLite
- ChromaDB
- Ollama

### Frontend
- React
- Vite
- TailwindCSS

## Project structure
```text
agentflow-ai/
├── app/
│   ├── api/
│   │   ├── chat.py
│   │   ├── conversations.py
│   │   ├── documents.py
│   │   └── system.py
│   ├── agents/
│   │   ├── memory.py
│   │   ├── orchestrator.py
│   │   ├── planner.py
│   │   ├── research.py
│   │   ├── reviewer.py
│   │   └── tool.py
│   ├── services/
│   │   ├── embeddings.py
│   │   ├── ollama_client.py
│   │   ├── rag.py
│   │   ├── sample_data.py
│   │   ├── storage.py
│   │   └── system_info.py
│   ├── config.py
│   ├── dependencies.py
│   ├── main.py
│   └── schemas.py
├── docs/
│   ├── API.md
│   ├── ARCHITECTURE.md
│   ├── DEMO_SCRIPT.md
│   ├── INSTALLATION.md
│   └── VALIDATION_REPORT.md
├── sample_data/
├── src/
│   ├── components/
│   ├── lib/
│   ├── App.jsx
│   ├── main.jsx
│   └── styles.css
├── tests/
├── package.json
├── requirements.txt
├── vite.config.js
└── README.md
```

## Quick start
### Backend
```bash
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Frontend
```bash
npm install
npm run dev
```

## Dependency policy
This project was generated to stay aligned with the constraints in your prompt:
- Python **3.13.x** compatible
- Windows 11 compatible
- Ubuntu 22.04+ compatible
- No Docker, Conda, Poetry, WSL, Rust, Meson, or CMake required
- No cloud APIs, API keys, or online LLM services
- Only stable packages from PyPI and npm
- Only dependencies actually used by the project

## Python dependencies used
```text
fastapi==0.141.1
uvicorn==0.52.1
python-multipart==0.0.32
pypdf==6.14.2
chromadb==1.5.9
```

## Frontend dependencies used
```text
react==19.2.8
react-dom==19.2.8
vite==8.2.0
@vitejs/plugin-react==6.0.5
tailwindcss==4.3.3
@tailwindcss/vite==4.3.3
```

## Documentation
- [Installation Guide](docs/INSTALLATION.md)
- [Architecture Diagram](docs/ARCHITECTURE.md)
- [API Documentation](docs/API.md)
- [Demo Script](docs/DEMO_SCRIPT.md)
- [Validation Report](docs/VALIDATION_REPORT.md)

## Testing
Run backend tests with:
```bash
python -m unittest discover -s tests -v
```

## Demo assets
Use files inside `sample_data/` for quick local demos.

## Notes about Ollama
If Ollama is not running, AgentFlow AI:
- does **not** crash
- shows a helpful error banner
- still preserves the multi-agent workflow shape with deterministic fallback behavior where possible
