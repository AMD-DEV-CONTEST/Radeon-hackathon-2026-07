# AI Drama Factory

`drama_factory` is the file-backed short-drama production subsystem for
`douyi_mcp`. Project JSON and media remain the source of truth; the existing
PostgreSQL job queue owns only top-level scheduling, leases, cancellation,
retry, checkpoints, and redacted result summaries.

## Runtime layout

Production data is outside Git:

```text
F:\douyi_mcp\runtime\drama\
├── projects\              # project JSON, assets, clips, and final videos
├── anchors\               # migrated gpt_anchors
├── config\                # runtime configuration overrides
└── migration-manifests\   # file hashes and JSON normalization audit trail
```

New JSON stores project-relative paths. Legacy Windows absolute paths are
accepted only when they resolve inside the selected project. Traversal through
symlinks or Windows reparse points is rejected. Project state is written with
temporary-file replacement and each project has an exclusive run/rework lock.

## Local development

The package requires Python 3.11 and uses its own virtual environment:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
.\.venv\Scripts\python.exe -m pytest -q
```

Run a dry pipeline directly:

```powershell
drama-run --project-key demo --authorized-root-id novels --input novel.txt --dry-run
```

In deployment, create and control runs through the unified `/v1/drama/*` API.
Confirmed knowledge imports use `POST /v1/drama/imports`; the factory creates a
content-addressed revision and `run_from_import()` skips novel splitting, Bible
generation and storyboard regeneration.
The Flask studio never accepts a shell command, arbitrary working directory, or
arbitrary output path.

## Services

- `drama-worker` claims only `drama_run`, `drama_shot_rework`, `drama_qc`, and
  `drama_asset_regen` jobs.
- Creative Hub is the only browser UI. The retired Flask and Streamlit
  consoles are no longer packaged or exposed.

## Video providers and GPU leases

`VideoProvider` defines `submit`, `poll`, `cancel`, and `fetch` with normalized
queued/running/succeeded/failed/cancelled states.

- `ComfyWanProvider` is the production implementation. Every model run first
  acquires an exclusive, model-sized lease from the existing GPU Broker, routes
  to ComfyUI 8188 or 8189 by the leased GPU index, heartbeats the lease, and
  releases it on success, failure, cancellation, or lease loss.
- `SeedanceProvider` contains the injectable asynchronous client contract and
  status mapping. Without configured credentials and a client it reports
  “not configured” and performs no network request.

## Secrets

Secrets are mounted as individual files (for example,
`ZHIPU_API_KEY_FILE=/run/secrets/drama-zhipu-key`). The studio only reports
configured/unconfigured state and cannot write `.env`.

The legacy source contained a plaintext credential in `.mcp.json`. That value
was not copied or logged. It must be rotated before production cutover.

## Historical migration

Use the idempotent Windows migration command:

```powershell
.\ops\windows\migrate-ai-drama-factory.ps1 -DryRun
.\ops\windows\migrate-ai-drama-factory.ps1
```

It copies into `.incoming/<migration-id>`, hashes every file, normalizes only
JSON path fields, probes production MP4 files, and atomically publishes verified
trees. The original `E:\yanchh\AI创作\ai_drama_factory` tree is never deleted or
overwritten.
