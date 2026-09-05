# E1-A local runtime foundation

This document is the operator handoff for Issue #5. The authority order remains
`AGENTS.md` -> `spec/README.md` -> approved L1/L2/L3 documents.

## What exists

- `app/experience_asset/domain/`: strict `ExperienceAssetV1`, progress, terminal,
  evidence-status, route, privacy, approval, export, `AgentRunStateV1`,
  `WorkPlanV1`, policy/execution/verification, and public-adapter contracts.
- `app/experience_asset/application/`: bounded durable fake Agent loop proving
  plan -> proposal -> policy -> execution record -> verification -> terminal
  state without implementing M1 product behavior.
- `app/experience_asset/retrieval/`: phase-scoped local repository interface and
  deterministic fake. Current-source, cross-asset summary and confirmed-detail
  scopes remain separate.
- `app/experience_asset/tools/` and `policy/`: reviewed model-visible tool
  boundary, per-tool strict argument schemas, deterministic allow/deny
  decisions and bounded fake effects. E1-A dispatches the three retrieval
  operations; later P0 tools remain visible as typed contracts but fail closed.
- `app/experience_asset/persistence/`: SQLite migration and immutable complete
  canonical snapshots with an optimistic current-version pointer plus durable,
  restartable run checkpoints.
- `app/experience_asset/inference/`: a loopback-only OpenAI-compatible vLLM
  adapter and deterministic fake. Parsed tool calls remain proposals with
  `permission_granted=false`.
- `app/experience_asset/observability/`: metadata allowlist and sanitized JSONL
  sink. Raw prompt, response, source, and generated content keys are dropped.
- `app/experience_asset/api/`: health and frozen terminal-state query endpoints.
- `contracts/`: generated JSON Schema and OpenAPI files for Lane B review.

The public progress contract uses
`percent_basis=milestones_done/milestones_total` with the matching counts.
Indeterminate operations omit percentage fields. Internal work-unit counters
do not replace the public milestone basis.

E1-A does not implement M1 ingestion, production milestone workflows,
cross-asset indexing, public export, deletion, React UI, model optimization, or
remote fallback.

## Local commands

Use Python 3.12 and the Agent environment:

```bash
uv venv --python 3.12
uv pip install --python .venv/bin/python -e '.[dev]'
.venv/bin/python scripts/export_contracts.py --check
.venv/bin/pytest
.venv/bin/ruff check .
```

Run the API locally:

```bash
EXPERIENCE_ASSET_DB=/tmp/experience-asset.sqlite3 \
OPENAI_BASE_URL=http://127.0.0.1:8000/v1 \
.venv/bin/uvicorn app.experience_asset.api.main:app --host 127.0.0.1 --port 8080
```

The health endpoint is `GET /api/v1/health`. `gpu_viability=NOT_VERIFIED` is
expected off Radeon Cloud and must not be promoted without the Issue #5
W7900/ROCm evidence packet.

## Radeon Cloud viability gate

After the repository and vLLM server are ready on the W7900, retain the exact
environment commands and run:

```bash
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
python scripts/verify_e1_model_contract.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model-id Qwen2.5-14B-Instruct
python scripts/verify_e1_runtime_gate.py \
  --base-url http://127.0.0.1:8000/v1 \
  --model-id Qwen2.5-14B-Instruct
```

The final two commands print only bounded metadata and pass/fail fields. The
Runtime gate captures one immutable real-model proposal and evaluates both
allow and deny paths against exactly that input. Redirect
the complete stdout/stderr of environment and server operations to the
Issue #5 raw tier under `/workspace/amd-track2-agent/evidence/<run_id>/raw/`.
Copy only the reviewed, sanitized viability summary into Git.

## Contract changes

Run `scripts/export_contracts.py` after editing a public model. Lane B must
review the generated OpenAPI/progress/terminal contracts before they are
treated as frozen. Later changes require a small explicit contract change and
cross-lane review.
