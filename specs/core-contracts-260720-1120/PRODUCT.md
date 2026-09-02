# Core Contracts and Project API

## Goal

Provide the stable backend contracts that the application developer needs for
document ingestion, retrieval, task evaluation, and report generation without
granting access to arbitrary file-system paths or model-server internals.

## User-visible behavior

- A client can create a project with a safe lowercase project ID and retrieve
  its metadata and import status through the API.
- Each project receives only `source/`, `derived/`, and `outputs/` directories.
- Invalid project IDs, duplicate project creation, path traversal, and missing
  projects return controlled API errors.
- Application modules share typed `Project`, `Task`, `Evidence`,
  `TaskEvaluation`, `RunState`, and `ReportDraft` contracts.
- The backend can make ordinary and JSON-validated OpenAI-compatible calls to
  the configured llama-server. Invalid structured output is retried once.

## Acceptance criteria

1. `POST /api/projects` creates an isolated project directory and returns 201.
2. `GET /api/projects/{project_id}` returns stored metadata and never exposes
   absolute host paths.
3. Traversal-like IDs and requests for unknown projects return 422 and 404.
4. Unit tests cover contracts, project isolation, HTTP error behavior, normal
   model generation, and structured-response retry behavior.
5. Cloud verification calls the deployed model through `LLMClient` and creates
   then reads a test project through the API.
