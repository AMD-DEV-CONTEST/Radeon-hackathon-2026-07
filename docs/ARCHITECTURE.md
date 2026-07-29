# Architecture — PrivateLocalAgent

## Components

| Module | Responsibility |
|--------|----------------|
| `src/app/gradio_app.py` | Demo UI, upload/ingest, chat, traces |
| `src/agent/agent.py` | Multi-step tool-using agent loop |
| `src/agent/planner.py` | Heuristic task plan generation |
| `src/agent/tools.py` | Tool registry + JSON action parsing |
| `src/rag/ingest.py` | File loaders + chunking |
| `src/rag/store.py` | Chroma persistent vector store |
| `src/memory/memory.py` | Local notes/facts/history |
| `src/llm/backend.py` | API / local transformers backends |
| `src/config.py` | YAML + env configuration |

## Control Flow

1. User submits query in Gradio
2. Planner produces a readable plan
3. Agent asks LLM for either a tool call JSON or final JSON
4. Tools execute locally and return observations
5. Loop continues until `{"final": ...}` or max steps
6. UI shows answer + tool trace + memory snapshot

## Data Flow (RAG)

```text
Document → chunk_text → embedding → Chroma upsert
Query → embedding → top-k retrieve → tool observation → LLM final answer
```

## Why this fits Track 2 scoring

- Functional completeness / practical value (60): end-to-end private office agent
- AMD platform optimization (40): ROCm local backend path + Radeon Cloud API/GPU workflow
