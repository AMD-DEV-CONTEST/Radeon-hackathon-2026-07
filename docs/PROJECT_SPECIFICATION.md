# ProjectPack Office Agent — Track 2 Project Specification

## 1. Project overview and application scenarios

ProjectPack Office Agent is a private, evidence-driven AI agent for small and
medium project teams. Teams upload project materials such as meeting notes,
plans, requirements, status reports, and a task CSV/XLSX. The agent retrieves
only project-scoped evidence, evaluates task progress, identifies risks, and
produces an auditable report bundle.

The intended scenarios are weekly project reporting, delivery-risk review,
meeting follow-up, and management review in environments where project data
must remain private and traceable. It is not a general-purpose autonomous
agent: it cannot execute shell commands, browse arbitrary paths, or directly
modify source documents and formal tasks.

## 2. Agent architecture

```text
Project materials + task list
          |
          v
Safe import, type validation, and project isolation
          |
          v
Parsing and chunking -> FAISS + BM25 project index
          |
          v
Evidence retrieval -> rule-based task evaluation -> local LLM explanation
          |
          v
Controlled run lifecycle and audit trail
          |
          +--> Markdown project report
          +--> risk CSV
          +--> next-week plan
          +--> structured JSON result with source evidence
```

The Web workbench communicates with a FastAPI API. The API invokes a fixed
runner sequence: scan, index, retrieve, evaluate, and draft. The local model
is accessed through llama.cpp OpenAI-compatible HTTP endpoints; it has no
direct shell or arbitrary filesystem access.

## 3. Core capabilities

1. **Private project ingestion** — accepts supported project files and task
   CSV/XLSX with file-type checks, project-scoped storage, and parsing.
2. **Hybrid retrieval** — combines FAISS vector search and BM25 lexical search
   for project evidence retrieval.
3. **Evidence-backed task evaluation** — produces status, explanation, risk
   level, recommendation, and source evidence for each evaluated task.
4. **Auditable reporting** — generates a Markdown report, risk register CSV,
   next-week plan, and structured JSON artifact for each run.
5. **Human-controlled collaboration** — project roles, risk/report workflows,
   and controlled integration previews preserve a human confirmation boundary
   for consequential writes.

## 4. Model and local deployment plan

The verified deployment uses the local GGUF model
`Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` served by ROCm-enabled llama.cpp.

Two local endpoints are used:

- Chat and report reasoning: `http://127.0.0.1:8000/v1`
- Embeddings for retrieval: `http://127.0.0.1:8080/v1`

The application starts separately from the model service:

```bash
python scripts/start_api.py
python scripts/start_workbench.py --host 0.0.0.0 --port 7860
```

The full environment setup, dependency list, model server commands, and
end-to-end cloud verification command are maintained in the repository
[`PROJECT_README.md`](../PROJECT_README.md).

## 5. AMD Radeon GPU / ROCm adaptation

Inference is deployed through llama.cpp compiled with ROCm/HIP support. The
server uses `--n-gpu-layers 999` to offload model layers to the AMD Radeon GPU.
The implementation also keeps chat and embedding endpoints separate so they
can be measured and tuned independently.

For the final demonstration, we record GPU model, ROCm version, llama.cpp
version, quantization, context size, VRAM use, GPU utilization, embedding
throughput, generation tokens/second, and end-to-end report duration. GPU
health can be observed with `rocm-smi`.

The current verification configuration intentionally prioritizes reproducible
functionality. It loads the same 35B GGUF for both chat and embeddings, which
is VRAM-intensive. The planned production optimization is a smaller dedicated
embedding model or a shared embedding service, reducing duplicate model memory
while preserving the project evidence boundary.

## 6. Demonstration flow

1. Create a project in the workbench.
2. Upload reference material and a task CSV/XLSX, or use managed project tasks.
3. Start **Generate project report** and observe the run status.
4. Inspect task status, explanation, risk level, and cited source evidence.
5. Download the Markdown report, risk CSV, and next-week plan.
6. Show Radeon GPU utilization and the model service health during execution.

## 7. Security and audit boundaries

- Data, vector indexes, reports, and downloads are isolated by `project_id`.
- Original uploaded task lists are never overwritten.
- The model is limited to the fixed runner and does not receive arbitrary tool
  access.
- External integration writes use an exact preview followed by a human
  confirmation token and an audit record.
- Credentials, tokens, private keys, and user filesystem paths are excluded
  from the repository and UI.

## 8. Submission checklist

- [x] Project specification: this document.
- [x] Source code and reproducible README: repository root.
- [x] 3–5 minute demonstration video on AMD Radeon GPU —
  <https://www.bilibili.com/video/BV14BMB6gEKu/>
- [x] PPT or poster describing value, architecture, and Radeon optimization —
  `showcase/PLASMA_ProjectPack_Poster.pdf`.
