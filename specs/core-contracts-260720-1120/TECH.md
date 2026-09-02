# Core Contracts and Project API — Technical Record

- Level: S2
- Status: verified

## Components

- `app/schemas/`: public Pydantic data contracts shared across backend and
  application modules.
- `app/llm/client.py`: OpenAI-compatible `/chat/completions` client with a
  normal text method and one-retry JSON-to-Pydantic method.
- `app/security/paths.py`: project-ID validation and resolved-path containment
  checks that reject absolute paths, traversal, and symlink escapes.
- `app/services/projects.py`: creates and reads JSON project metadata under the
  configured project root.
- `app/api/projects.py`: read-only metadata retrieval and controlled project
  creation routes.

## Boundaries

- The project API accepts a project ID, never a client-provided host path.
- `source/` is created but no upload or parsing route is added in this change.
- The model client has no shell/tool execution capability.
- JSON metadata is intentionally used for the bootstrap; SQLite persistence is
  deferred until project lifecycle requirements need querying or concurrency.

## Risks and rollback

- A llama-server that does not honor JSON mode may cause structured generation
  to fail after its single retry; callers receive a controlled error.
- Filesystem persistence has no multi-process locking in this bootstrap.
- Rollback is to revert this spec's implementation commit; project directories
  are inert data and can remain without affecting startup.
