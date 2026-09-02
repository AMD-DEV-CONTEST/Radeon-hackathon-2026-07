# ProjectPack Office Agent

ProjectPack Office Agent is a private, evidence-driven office assistant for
project teams. It imports project reference files and a task list, retrieves
project-scoped evidence, evaluates task progress with rules plus a local LLM,
and generates an auditable report bundle.

> **Track 2 · Team PLASMA · AMD Radeon (ROCm) Hackathon 2026-07**

## Demo video

A 3–5 minute end-to-end demonstration running on an AMD Radeon GPU (ROCm) is
available here:

- **Bilibili:** <https://www.bilibili.com/video/BV14BMB6gEKu/>

The video walks through the full workflow: create project, upload reference
files and task list, generate the report on the Radeon GPU, and download the
Markdown report, risk CSV, and next-week plan, with live GPU utilisation shown.

For the official Track 2 submission document, see
[Project Specification](docs/PROJECT_SPECIFICATION.md).

## MVP capabilities

```text
Reference files + task CSV/XLSX
        -> safe import and parsing
        -> FAISS + BM25 retrieval
        -> evidence-backed task evaluation
        -> Markdown report + risk CSV + next-week plan
```

The fixed runner permits only this sequence: scan, index, retrieve, evaluate,
and draft. The model does not receive shell or arbitrary filesystem access.

## Architecture

```text
Gradio workbench --HTTP--> FastAPI API --controlled runner--> RAG / Phase C
       |                         |                                  |
       |                         +--> project-scoped uploads          +--> local llama-server
       |                                                                  chat :8000/v1
       +--> report downloads                                               embeddings :8080/v1
```

## Prerequisites

- Python 3.12 or newer.
- A llama.cpp build with ROCm/HIP support for AMD Radeon GPUs.
- A local GGUF chat model. This project was verified with
  `Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`.

Create an environment and install the project:

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
cp .env.example .env       # Windows PowerShell: Copy-Item .env.example .env
```

Edit `.env` only when your paths or endpoint ports differ. Never commit it.

## Start local model services

Run the chat endpoint and embeddings endpoint in separate terminals. Replace
the binary and model paths with those on your cloud instance.

```bash
# Chat endpoint
/workspace/runtime/llama.cpp/build/bin/llama-server \
  --model /workspace/models/qwen3.6/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  --alias qwen3.6-office-agent --host 127.0.0.1 --port 8000 \
  --n-gpu-layers 999 --ctx-size 16384 --jinja
```

```bash
# Embeddings endpoint (MVP verification configuration)
/workspace/runtime/llama.cpp/build/bin/llama-server \
  --model /workspace/models/qwen3.6/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  --host 127.0.0.1 --port 8080 --n-gpu-layers 999 \
  --ctx-size 4096 --embeddings --pooling mean
```

Verify both endpoints:

```bash
curl http://127.0.0.1:8000/health
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8000/v1/models
```

> The MVP verification configuration loads the same model twice, so it is
> GPU-memory intensive. Production should use a smaller dedicated embedding
> model or a shared-service deployment.

> The recommended 35B performance profile uses a 16K chat context. Project
> reports retrieve concise evidence excerpts and normally do not require 32K.
> Raise it to 32K only for genuinely long single-document work.

## Start the application

Terminal 1 starts the API:

```bash
python scripts/start_api.py
```

Terminal 2 starts the workbench:

```bash
python scripts/start_workbench.py --host 0.0.0.0 --port 7860
```

Open `http://127.0.0.1:7860` locally. When using SSH port forwarding, forward
port 7860 and open that same local address in the browser.

## MVP demo flow

1. Open the workbench and create project ID `demo-project`.
2. Upload [demo/status.md](demo/status.md) as the reference file.
3. Upload [demo/tasks.csv](demo/tasks.csv) as the task list.
4. Select **Generate project report**.
5. Inspect the JSON task result. It includes task status, explanation, and the
   `status.md` evidence citation.
6. Download the generated Markdown report, risk CSV, and next-week plan.

Outputs are scoped to one project and run:

```text
outputs/<project_id>/reports/<run_id>.md
outputs/<project_id>/risks/<run_id>.csv
outputs/<project_id>/plans/<run_id>.md
outputs/<project_id>/results/<run_id>.json
```

The original task list is never modified.

## Tests and cloud verification

Run local checks:

```bash
python -m pytest -q
python scripts/validate_specs.py
```

With both local model services running on the cloud instance, run the real
end-to-end verifier:

```bash
python scripts/verify_end_to_end_rag_report_cloud.py
```

It creates a timestamped smoke-test project and verifies the live chat model,
embedding retrieval, source citation, report, risk CSV, next-week plan, and
structured result artifact. It does not overwrite an existing project.

## AMD Radeon / ROCm notes

- Inference uses `llama.cpp` with ROCm/HIP and `--n-gpu-layers 999`.
- Monitor utilisation and VRAM percentage with `rocm-smi`.
- Keep chat and embedding endpoint URLs separate in `.env`.
- Record GPU model, ROCm version, context size, VRAM use, and token throughput
  during the final demonstration.

## Development and governance

- Create a feature branch from current `main`; do not push directly to `main`.
- Add an S1/S2/S3 specification under `specs/` before implementation as
  required by the repository workflow.
- Run tests and specification validation before opening a PR.
- The official PR title is exactly:

  ```text
  Track 2, PLASMA, ProjectPack Office Agent
  ```

## Track 2 submission checklist

This repository fulfils every required Track 2 deliverable:

- [x] **Project specification document** — [docs/PROJECT_SPECIFICATION.md](docs/PROJECT_SPECIFICATION.md)
  (application scenarios, agent architecture, core capabilities, model &
  local-deployment plan, AMD Radeon / ROCm inference-optimisation notes).
- [x] **Project source code** — `app/`, `scripts/`, `web/` with this README
  covering environment setup, startup, and dependencies.
- [x] **Demo video (3–5 min, on AMD Radeon GPU)** —
  <https://www.bilibili.com/video/BV14BMB6gEKu/>
- [x] **Supplementary material (PPT / poster)** —
  [showcase/PLASMA_ProjectPack_Poster.pdf](showcase/PLASMA_ProjectPack_Poster.pdf)
  and the static [showcase/index.html](showcase/index.html) landing page.
