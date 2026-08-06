# System design

```mermaid
flowchart LR
  V[YouTube URL] --> S[Source adapters]
  S --> E[Evidence: transcript, frames, OCR]
  E --> M[Local vector memory]
  M --> O[Agent orchestrator]
  O --> A[Artifacts]
  A --> Z[Downloadable repository ZIP]
  G[ROCm / HIP local runtime] --> O
```

The FastAPI service owns job state and artifact packaging. The Next.js client polls one explicit project resource, rendering its agent, timeline, generated-file, GPU, and benchmark state. Model integrations are adapter boundaries: `vLLM ROCm` or `llama.cpp HIP` for code planning, Qwen2.5-VL for frames, BGE for embeddings, and PaddleOCR for text evidence.
