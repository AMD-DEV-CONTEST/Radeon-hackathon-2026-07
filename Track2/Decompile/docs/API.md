# API specification

## `POST /api/projects`

Starts local project generation. Body: `{ "url": "https://youtube.com/..." }`. Returns `202` and a complete project object with stages, agents, artifacts, and logs.

## `GET /api/projects/{id}`

Returns live project state for polling.

## `GET /api/projects/{id}/download`

Returns the generated ZIP once the job is complete. Returns `409` while it is processing.

## `GET /api/memory/search?q=...`

Searches local project memory. No project content leaves the machine.

## `GET /api/gpu` and `GET /api/benchmarks`

Return the telemetry contract and repeatable benchmark baseline used by the judge-facing dashboard.
