# AGENT.md — Bunker Project Guide

> **Token-saving guide for AI agents maintaining the Bunker codebase.**
> Read THIS file first. Read module AGENT.md files only when touching that module.

---

## What is Bunker?

Private AI agent hackathon project (AMD AI DevMaster 2026, Track 2). Fully local inference on AMD Radeon GPU via ROCm. Zero data exfiltration.

**Key constraint: All inference must run locally. Radeon Cloud API is BONUS fallback only.**

---

## Architecture (one glance)

```
Gradio UI  -->  ReAct Agent  -->  vLLM-ROCm (primary) / Radeon API (bonus fallback)
                    |
    +---------------+---------------+---------------+
    |               |               |               |
  ChromaDB      SQLite        Tool Registry     Audit Log
  (RAG)       (Memory)       (MCP-style)      (Privacy)
```

---

## File Map: Where to Find What

| If you need to... | Look at |
|---|---|
| Change models, inference, quantization, fallback chain | `src/inference/` + its `AGENT.md` |
| Change agent reasoning, ReAct loop, task planning, permissions | `src/agent/` + its `AGENT.md` |
| Change RAG (embeddings, vector search, doc ingestion) | `src/rag/` + its `AGENT.md` |
| Change memory (sessions, context windows) | `src/memory/` + its `AGENT.md` |
| Change tools (file, email, calendar, web) or add new tools | `src/tools/` + its `AGENT.md` |
| Change privacy dashboard, audit logs, encryption | `src/privacy/` + its `AGENT.md` |
| Change UI layout, components, Gradio app | `src/ui/` + its `AGENT.md` |
| Change config, env vars, startup | `src/config.py`, `src/main.py`, `.env.example` |
| Change Docker, deployment | `Dockerfile`, `docker-compose.yml`, `docker-entrypoint.sh` |
| Add tests | `tests/test_*.py` |
| Update docs for submission | `docs/` |

---

## Critical Design Decisions (DO NOT BREAK)

1. **Local-first inference**: `ModelManager` tries local vLLM first, secondary local model second, Radeon Cloud API LAST. Track `fallback_stats` for dashboard evidence.
2. **Permission gating**: `ToolRegistry.execute()` checks `requires_permission`. `file_read`/`file_search`/`file_list` = auto-approve. `file_write`/`email_draft`/`calendar_create_event`/`web_search` = requires approval.
3. **Privacy telemetry OFF**: `anonymized_telemetry=False` on ChromaDB. Audit log EVERY inference and tool call.
4. **ROCm device mapping**: PyTorch `cuda` resolves to HIP. Use `torch.version.hip` to verify ROCm.
5. **ReAct max iterations**: 10. Graceful timeout. Every tool call is audited.

---

## Common Tasks (copy-paste paths)

### Add a new tool
1. Edit `src/tools/TOOL_NAME_tools.py` (follow existing pattern)
2. Register in `src/tools/registry.py` `ToolRegistry.__init__()`
3. Add test in `tests/test_tools.py`
4. Update `src/agent/react_loop.py` SYSTEM_PROMPT tool descriptions

### Add a new inference backend
1. Add class in `src/inference/` (follow `vllm_server.py` or `radeon_api.py`)
2. Wire into `src/inference/model_manager.py` fallback chain
3. Update `src/config.py` `InferenceConfig`

### Change the Gradio layout
1. Edit `src/ui/gradio_app.py` `BunkerGradioApp.build_ui()`
2. Custom components live in `src/ui/components/`

### Update demo benchmarks
1. Edit `docs/BENCHMARKS.md`
2. Edit `scripts/benchmark.sh`
3. Update README benchmark table

---

## Project Structure Tree

```
bunker/
├── AGENT.md                  <-- YOU ARE HERE
├── README.md
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── docs/
│   ├── PROJECT_SPEC.md
│   ├── ARCHITECTURE.md
│   ├── AMD_OPTIMIZATION.md
│   └── BENCHMARKS.md
├── src/
│   ├── main.py               # FastAPI entry, mounts Gradio
│   ├── config.py             # Pydantic settings, env-driven
│   ├── agent/                # ReAct loop + planner + permissions
│   ├── inference/            # vLLM-ROCm + Radeon API + quantizer
│   ├── rag/                  # Embeddings + ChromaDB + doc loader
│   ├── memory/               # SQLite session store + context mgr
│   ├── tools/                # MCP registry + tool implementations
│   ├── privacy/              # Audit logger + data flow monitor + dashboard + encryption
│   └── ui/                   # Gradio app + components
├── tests/
│   └── test_*.py
├── scripts/
│   ├── setup_rocm.sh
│   ├── download_models.sh
│   ├── benchmark.sh
│   └── demo_data.sh
└── data/
    ├── documents/
    ├── vector_db/
    ├── memory/
    └── audit/
```

---

## External Dependencies You Should Know

| Package | Purpose | ROCm-specific? |
|---|---|---|
| `torch==2.3.0+rocm6.2` | PyTorch backend | YES |
| `vllm==0.5.0` | Inference server | YES |
| `auto-gptq==0.7.1` | INT4 quantization | YES |
| `sentence-transformers` | Embeddings | No |
| `chromadb` | Vector DB | No |
| `gradio` | Web UI | No |
| `fastapi`/`uvicorn` | API server | No |

**Never upgrade PyTorch or vLLM without verifying ROCm compatibility.**

---

## Environment Variables (see `.env.example` for all)

```bash
BUNKER_PRIMARY_MODEL=Qwen/Qwen3-30B-A3B
BUNKER_SECONDARY_MODEL=meta-llama/Llama-3.1-8B-Instruct
BUNKER_QUANTIZATION=gptq
BUNKER_RADEON_API_KEY=          # Only for bonus fallback
BUNKER_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
```

---

## Testing

```bash
pytest tests/ -v
```

Add tests for any new tool or module. Maintain >80% coverage for hackathon judging.

---

## Last Updated
2026-07-20 — Initial build
