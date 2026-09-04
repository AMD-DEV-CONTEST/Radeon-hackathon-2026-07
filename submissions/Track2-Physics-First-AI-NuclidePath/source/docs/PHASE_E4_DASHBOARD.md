# Phase E4 dashboard integration

The localhost-only dashboard exposes versioned, read-only JSON views:

- `GET /api/v1/models/gcs/primary` — primary GCS model version and parameter metadata.
- `GET /api/v1/paper-rocks` — Bradbury paper-input rock reconstructions and predicted Kd envelopes.
- `GET /api/v1/source-terms` — source-term contract/model catalog.
- `POST /api/v1/model-selection` — deterministic eligibility, selection, and rejection reasons. The body contains `request` and `candidates`.
- `POST /api/v1/replay/verify` — verifies a replay bundle given `{ "path": "..." }`.

Replay verification is intentionally path-only: the resolved path must be an existing directory below the explicitly configured dashboard results root (`--output`). No upload endpoint, remote binding, or arbitrary filesystem browsing is provided. The server rejects paths outside that root with HTTP 403. The dashboard remains loopback-only; `validate_host` rejects non-loopback addresses.
