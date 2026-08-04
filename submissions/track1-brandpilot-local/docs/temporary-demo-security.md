# Temporary demo security

This control is for a short Radeon Cloud validation session, not permanent
hosting.

Set:

```text
ENABLE_EXPERIMENTAL_ROCM=true
DEMO_AUTH_ENABLED=true
EXPERIMENTAL_MAX_ACTIVE_JOBS=1
```

Generate a fresh token from at least 32 random bytes for every session. Keep it
only in process memory and the operator browser's `sessionStorage`. Never place
it in a command history, persistent log, source file, screenshot, URL query,
frontend build variable, cookie, analytics event, or documentation.

When demo authentication is enabled, project, upload, system status,
generation, job, output, and review routes require
`Authorization: Bearer <token>`. Comparison uses a constant-time function and
failures return a generic HTTP 401. FastAPI documentation and its OpenAPI route
are disabled when authentication is enabled before startup.

The official temporary tunnel must forward only the backend bound at
`127.0.0.1:8000`. It must not expose JupyterLab, SSH, a shell, file browser,
database, storage directory, or unauthenticated administration surface.
Possession of the temporary URL is not authentication.

Shutdown order:

1. stop frontend polling
2. stop the temporary tunnel
3. stop FastAPI and wait for the worker
4. unset the token
5. destroy the Radeon instance
6. verify no active instance
7. clear the browser session

Tunnel confidentiality, provider availability, and bearer-token sharing remain
demo risks. Use no private client content and perform human review on every
experimental output.
