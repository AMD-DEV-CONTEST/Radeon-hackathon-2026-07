# NexusAI Technical Requirements Document

**Version:** 1.0  
**Scope:** Hackathon MVP

## 1. Architecture Goals

- Shared core with domain adapters.
- Clear separation between frontend, API, processing, AI runtime, and persistence.
- Vercel-deployable web/control plane.
- AMD Radeon Cloud compute plane for heavy GPU inference.
- Replaceable model adapters.
- Asynchronous processing model.
- Provenance-first knowledge representation.

## 2. Recommended Stack

### Web
- Next.js
- TypeScript
- Tailwind CSS
- Framer Motion
- React Three Fiber / Three.js
- React Flow or Cytoscape.js

### API / Control Plane
- FastAPI
- Python
- Pydantic
- SQLAlchemy
- Alembic

### Data
- PostgreSQL for durable relational metadata
- Kuzu for local/embedded graph workloads where useful
- FAISS for local vector indexing in the GPU worker/demo environment

### AI / Processing
- Qwen-family local instruct model, final size chosen after Radeon benchmark
- BGE-family embeddings
- Whisper for speech-to-text
- Florence-family vision model
- PaddleOCR/Tesseract fallback for OCR
- YOLO for selected object-detection workflows
- Tree-sitter for source-code parsing

Models are adapters, not hard-coded platform dependencies.

## 3. Deployment Model

### Vercel: Web and lightweight API
Vercel hosts:
- Next.js frontend
- lightweight FastAPI/control-plane endpoints if desired
- request validation
- job submission
- job-status queries
- streaming lightweight responses
- public demo experience

### Radeon Cloud: GPU Worker
Radeon Cloud hosts:
- LLM inference
- embeddings
- speech transcription
- vision inference
- compute-heavy ingestion stages
- model cache

### Important Constraint
The full GPU inference stack should not be packaged into Vercel Functions. Heavy ML dependencies, persistent model memory, long-running processing, FAISS/Kuzu local state, and ROCm workloads belong on the Radeon Cloud worker.

## 4. Logical Components

### apps/web
User interface and visualization.

### apps/api
Control-plane API.

### nexus/ingestion
Normalizes incoming sources.

### nexus/world
Canonical World Model.

### nexus/graph
Graph construction and traversal abstractions.

### nexus/timeline
Temporal normalization and event ordering.

### nexus/retrieval
Structured, graph, and vector retrieval.

### nexus/reasoning
Builds grounded context and calls the AI runtime.

### ai/runtime
Provider-independent model interfaces.

### worlds/*
Domain adapters and domain-specific visualization semantics.

## 5. API Requirements

Initial endpoints:

- `GET /api/health`
- `GET /api/worlds`
- `POST /api/worlds`
- `GET /api/worlds/{world_id}`
- `POST /api/worlds/{world_id}/sources`
- `POST /api/worlds/{world_id}/ingest`
- `GET /api/jobs/{job_id}`
- `GET /api/worlds/{world_id}/graph`
- `GET /api/worlds/{world_id}/timeline`
- `POST /api/worlds/{world_id}/query`

Exact routes may evolve while preserving the resource model.

## 6. Processing Requirements

Processing jobs should expose states:

- queued
- running
- completed
- failed

Where practical, stages should expose progress:

- upload
- parsing
- extraction
- embeddings
- graph construction
- indexing
- ready

## 7. Security and Privacy

- Never commit secrets.
- Use environment variables.
- Validate uploads.
- Enforce file-size/type limits.
- Sanitize filenames and paths.
- Treat uploaded content as untrusted.
- Avoid executing uploaded repository code during MVP analysis.
- Use synthetic/fictional datasets for Detective demos.
- Clearly label AI-generated observations.

## 8. Observability

Track:
- request latency
- ingestion duration
- model inference duration
- GPU job duration
- errors
- model name/version
- observation confidence where applicable

A demo-facing Engine Monitor may display selected non-sensitive metrics.

## 9. Testing

Required:
- unit tests for World Model
- parser tests
- API health tests
- graph construction tests
- retrieval tests
- domain-adapter tests
- one end-to-end happy path per flagship demo

## 10. Definition of Done for Foundation

- Web app starts locally.
- API starts locally.
- Web can call `/api/health`.
- World Selector renders.
- Four World metadata entries are returned.
- Deployment configuration supports the Vercel web/control plane.
- GPU-worker interface is defined independently from Vercel deployment.
