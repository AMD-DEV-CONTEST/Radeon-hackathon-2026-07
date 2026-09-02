# Reproducible MVP Demonstration

- Level: S2
- Status: implemented

## Design

- Keep model deployment separate from the application: llama-server exposes a
  chat endpoint on port 8000 and an embeddings endpoint on port 8080.
- `scripts/start_api.py` and `scripts/start_workbench.py` provide stable
  application entry points driven only by `.env` settings.
- The cloud verifier creates a timestamped project and asserts the report,
  risk CSV, next-week plan, and structured evaluation artifact.

## Risks and rollback

- The Qwen GGUF is intentionally not committed; operators provide its local
  cloud path through the documented llama-server command.
- Rollback removes documentation and helper scripts without affecting runtime
  APIs or report generation.

## Verification

- Local unit suite and specification validation.
- Cloud run against the live chat and embedding endpoints.
