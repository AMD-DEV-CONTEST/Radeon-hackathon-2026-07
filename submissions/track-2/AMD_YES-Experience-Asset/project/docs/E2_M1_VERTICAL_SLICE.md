# E2 / M1 Experience Brief Vertical Slice

Status: **CHECKPOINT 1 CONFIRMED / CHECKPOINT 2 LOCAL CANDIDATE COMPLETE WITH
COMMIT BINDING PENDING / CHECKPOINT 3 W7900 EVIDENCE PENDING on Issue #15**.
The frozen Contract / Schema + Fixture inventory is recorded in
[`docs/kinnyu/E2_M1_CONTRACT_CHECKPOINT.md`](kinnyu/E2_M1_CONTRACT_CHECKPOINT.md).
The local backend, typed client, UI, compiled graph and bounded evidence
artifacts are present on `codex/e2-m1-experience-brief`, but are not promoted
until the implementation is commit-bound and the quality owner accepts the
remaining Issue checkpoints.

## Product result

The user can start with conversation-style text, pasted text, `.txt`, or `.md`
and immediately receive a persisted, editable `Experience Brief v0.1`.
The workspace:

- shows source boundary and provenance;
- stores imported statements as source facts rather than system instructions;
- classifies subsequent user edits and answers as user judgments;
- asks at most three explained questions and supports answer, skip, defer,
  pause, resume and confirm-with-visible-gaps;
- autosaves each accepted change as a new immutable canonical version;
- restores the current version after an application or page restart;
- derives progress from the saved version, unresolved questions and milestone
  state, with no fabricated ETA; and
- exposes a bounded local Agent run through one startup-compiled LangGraph:
  `load -> plan -> local-model proposal -> Runtime policy -> current-source
  retrieval effect -> verification -> persist -> durable terminal state`.

The initial Brief is deliberately deterministic and marked
`model_inference_used=false`. This provides a fast, source-faithful first
artifact. The separate Agent action uses the configured loopback vLLM endpoint
and records the real model identity and terminal state. If vLLM is unavailable,
the UI shows `MODEL_UNAVAILABLE` and the last durable asset version remains
unchanged.

## Local run

Use ignored local data for a workstation smoke test:

```bash
EXPERIENCE_ASSET_DB=/tmp/experience-asset.sqlite3 \
EXPERIENCE_WORKFLOW_DB=/tmp/experience-asset.workflow.sqlite3 \
CODE_COMMIT=UNCOMMITTED \
GPU_VIABILITY=NOT_VERIFIED \
.venv/bin/uvicorn app.experience_asset.api.main:app \
  --host 127.0.0.1 --port 8080
```

In a second terminal:

```bash
cd web
npm install
npm run dev -- --host 127.0.0.1 --port 5173
```

Open:

```text
http://127.0.0.1:5173/?view=m1&source=live
```

On Radeon Cloud, use the persistent Agent environment and database:

```bash
source /workspace/amd-track2-agent/venvs/agent/bin/activate
export EXPERIENCE_ASSET_DB=/workspace/amd-track2-agent/data/experience_asset.sqlite3
export EXPERIENCE_WORKFLOW_DB=/workspace/amd-track2-agent/data/experience_asset.workflow.sqlite3
export CODE_COMMIT="$(git rev-parse HEAD)"
export OPENAI_BASE_URL=http://127.0.0.1:8000/v1
export SERVED_MODEL_NAME=Qwen/Qwen2.5-14B-Instruct
uvicorn app.experience_asset.api.main:app --host 127.0.0.1 --port 8080
```

Do not publish either service or run `rc-tunnel expose` without the user's
explicit authorization after authentication is verified.

`UNCOMMITTED` is acceptable only for local development. Any checkpoint evidence,
W7900 run or promotion packet must set `CODE_COMMIT` to the exact 40-character
Git commit under test.

## API surface

| Method and path | Durable effect |
|---|---|
| `POST /api/v1/m1/assets` | Create the initial asset and Brief |
| `GET /api/v1/m1/assets/{asset_id}` | Restore current M1 workspace |
| `PATCH /api/v1/m1/assets/{asset_id}/brief` | Autosave an edited Brief version |
| `POST /api/v1/m1/assets/{asset_id}/questions/{question_id}` | Answer, skip, or defer |
| `POST /api/v1/m1/assets/{asset_id}/pause` | Save and pause |
| `POST /api/v1/m1/assets/{asset_id}/resume` | Resume from the durable version |
| `POST /api/v1/m1/assets/{asset_id}/confirm` | Confirm or complete with visible gaps |
| `POST /api/v1/m1/assets/{asset_id}/agent-runs` | Run the bounded local production graph |

All write/action requests bind to `expected_version_id`. A stale browser receives
HTTP `409` instead of overwriting a newer version.

## Agent and hallucination controls

- The model endpoint must be HTTP loopback.
- The production graph is compiled once during application startup with a
  separate SQLite checkpointer. SQLite Asset Repository remains canonical
  truth; LangGraph owns only the resumable graph cursor.
- Graph state contains typed IDs, workflow/topology identity, cursor metadata,
  projection sequence and terminal candidate—not source text, raw prompts,
  raw model responses or the complete Experience Asset.
- Imported content is placed in `source_excerpts` and explicitly marked
  untrusted by the system policy.
- The model's Tool Call always has `permission_granted=false`.
- Runtime validates the allowlist, explicit user permission, asset ID, exact
  version ID, `CURRENT_SOURCE` scope, arguments and stale bindings.
- The real retrieval adapter reads only source-linked statements in the exact
  current asset version and stores sanitized provenance references and hashes.
- Resume requires the same workflow, topology, base version, model, loopback
  service, model-config hash and code commit; identity drift stops safely.
- A started-but-indeterminate node effect is never dispatched again after a
  restart.
- Unknown, publishing, network, shell, export, approval and cross-asset tools
  fail closed with a visible terminal state.
- Unsupported details remain questions or user edits; they are not silently
  promoted to facts.

## Verification

Repository and backend:

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
.venv/bin/python -m pytest
.venv/bin/ruff check .
bash qa/gates/pr_gate.sh --mode contract
.venv/bin/python scripts/capture_e2_m1_local_evidence.py \
  --output-dir evidence/milestones/e2-m1-langgraph-local/20260728T102918Z/artifacts \
  --code-commit UNCOMMITTED \
  --fixture-id chair_incomplete \
  --ui-screenshot web/e2e-results/screenshots/17-m1-live.png
bash qa/gates/pr_gate.sh --mode artifact \
  --asset evidence/milestones/e2-m1-langgraph-local/20260728T102918Z/artifacts/experience-asset.public.json \
  --fixture-id chair_incomplete \
  --progress evidence/milestones/e2-m1-langgraph-local/20260728T102918Z/artifacts/m1-progress.json \
  --retrieval-trace evidence/milestones/e2-m1-langgraph-local/20260728T102918Z/artifacts/retrieval-phase-trace.json
```

Frontend:

```bash
cd web
npm run verify:contracts
npm run test
npm run typecheck
npm run lint
npm run build
```

Public E2 tests cover complete, incomplete, conflicting and resume fixtures,
autosave conflicts, restart recovery, direct and indirect imported-instruction
denial, Runtime allow/deny, real current-version retrieval references, all
three model/format failure classes, LangGraph restart without effect replay,
indeterminate-effect refusal, stale/missing/incompatible/runtime-mismatched
checkpoint safe-stop, sanitized node Trace, public artifact conformance and
visible UI states.

## Track 2 and submission impact

This work is directly relevant to Track 2: it adds private local inference,
durable task planning, Tool Calling, scoped local retrieval, multi-step task
closure and permission enforcement. It is intended to produce the first
reviewable `Vertical Slice V1` and the workload for `Serving Reference S1`.

Not yet proven:

- a successful real-model M1 run on the current W7900/vLLM service;
- the repeated `Serving Reference S1` manifest and measurements;
- the frozen, commit-bound `Vertical Slice V1` evidence packet;
- quality-owner blind evaluation and E2 promotion.

Those items belong to Issue #15's Evidence / Promotion checkpoint. This E2
slice is not the E8 complete-product Baseline and makes no optimization claim.
Under the current team handoff, `kinnyuww` owns the W7900/ROCm/real-vLLM
execution, Serving Reference S1 and checkpoint-3 promotion evidence; `Eas000n`
owns the implementation and non-W7900 local checkpoint-2 candidate.
