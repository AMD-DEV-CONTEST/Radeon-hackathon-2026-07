# API Bootstrap and Model Health

## Background

ProjectPack Office Agent needs a reliable application boundary before document import, retrieval, and report generation can be added. Operators must be able to tell whether the API process is alive and whether its required local Qwen llama-server endpoint is reachable.

## Scope

This change creates the first application bootstrap, environment configuration, and a read-only health endpoint. It does not add project import, RAG, task evaluation, report generation, authentication, or UI features.

## User-visible behaviors

### B1: Start with documented configuration

An operator can create a local `.env` from `.env.example` and start the FastAPI application with the documented model endpoint, paths, port, and agent-step defaults.

### B2: Reject invalid critical configuration

The application rejects invalid API ports, empty model names, invalid model URLs, and model URLs that do not end in `/v1` before serving requests.

### B3: Expose API and model health separately

`GET /health` always reports the API response structure. It reports `status: ok` only when the configured llama-server `/health` endpoint is reachable; otherwise it reports `status: degraded` with a non-sensitive failure reason.

### B4: Keep runtime artifacts out of source control

Local `.env`, virtual environments, model files, project data, indexes, logs, and generated output are ignored by Git.

## Non-goals

- Model inference/chat endpoint.
- Document upload, parsing, indexing, or task logic.
- Persistent project records.
- External authentication or public exposure.
