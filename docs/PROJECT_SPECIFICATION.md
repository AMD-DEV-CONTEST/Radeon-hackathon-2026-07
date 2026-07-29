# Project Specification — PrivateLocalAgent

## 1. Application Scenario

PrivateLocalAgent targets **private office productivity**:

- Internal policy / FAQ question answering
- Local document understanding (PDF/Markdown/Text)
- Lightweight personal assistant with memory
- Tool-augmented workflow automation without sending confidential text to public SaaS chatbots

Primary users: individuals and small teams that need **local / private** AI agents on AMD Radeon GPUs.

## 2. Agent Architecture

```text
User (Gradio UI)
   │
   ▼
Task Planner (heuristic + LLM loop)
   │
   ▼
Private Agent Loop (max N steps)
   ├─ LLM Backend
   │    ├─ OpenAI-compatible (Radeon Cloud Model API)
   │    └─ Local Transformers (ROCm / CUDA)
   ├─ Tools
   │    ├─ kb_search
   │    ├─ list_files / read_file
   │    ├─ write_note / save_fact / recall_memory
   │    └─ kb_stats
   ├─ RAG Vector Store (Chroma + local embeddings)
   └─ Session Memory (JSON on disk)
```

## 3. Core Capabilities

1. **Private RAG**: ingest local docs, retrieve top-k evidence, answer with grounding
2. **Tool Calling**: structured JSON tool protocol in a multi-step loop
3. **Memory Management**: notes/facts persisted locally
4. **Task Planning**: automatic plan preview + stepwise execution trace
5. **Dual Backend**: cloud API for fast iteration, local ROCm for private inference

## 4. Model & Local Deployment Plan

### Phase A — Development (API mode)
- Backend: `openai_compatible`
- Endpoint: Radeon Cloud Model API (`developer.amd.com.cn/radeon`)
- Purpose: validate agent loop / RAG / tools quickly while GPU credits are limited

### Phase B — Private Deployment (Local mode)
- Backend: `local_transformers`
- Model: `Qwen/Qwen2.5-7B-Instruct` (or smaller for speed)
- Runtime: AMD Radeon GPU + ROCm PyTorch on Radeon Cloud notebook
- Artifacts stay on local disk (`data/`)

## 5. Inference Speed Optimization on AMD Radeon GPU

See `AMD_ROCM_OPTIMIZATION.md` for details. Summary:

- Prefer FP16 inference
- Keep retrieval local (MiniLM embeddings) to reduce LLM context size
- Bound agent steps (`max_steps`)
- Use Persistent PVC on Radeon Cloud so model/cache are reused
- Optional: serve local model via vLLM OpenAI-compatible endpoint on Radeon Cloud

## 6. Privacy Design

- Uploaded documents remain under `data/uploads`
- Memory is local JSON only
- Tool sandbox prevents path traversal outside upload directory
- Local backend avoids sending prompts to external services

## 7. Deliverables Checklist

- [x] Source code + README
- [x] Project specification (this document)
- [x] Architecture notes
- [x] AMD/ROCm optimization notes
- [x] Sample docs + ingest script
- [x] Gradio demo app
- [x] CLI smoke demo (`scripts/demo_cli.py`) verified on Radeon Cloud GPU
- [ ] Demo video (record CLI + verify_rocm on Radeon Cloud)
- [ ] Final PR to official contest repository
