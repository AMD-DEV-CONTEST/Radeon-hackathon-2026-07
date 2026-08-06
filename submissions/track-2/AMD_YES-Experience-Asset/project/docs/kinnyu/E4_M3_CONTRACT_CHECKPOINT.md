# E4 / M3 Contract, Schema and Fixture Preparation

Status: `CHECKPOINT_2_IMPLEMENTED_W7900_EXECUTION_PREPARED`

Scope state: `MATERIAL_VERTICAL_SLICE_INTEGRATED`

Owner: `Eas000n`

Reviewer and promotion authority: `kinnyuww`

Tracking Issue: [#21](https://github.com/kinnyuww/amd-devmaster-track2-agent/issues/21)

Upstream observed: E3 PR #20 merged at
`5c5c84f5209b2f91745924e69d55ea5290880153`.

## Completed integration audit

The post-E3 audit and Checkpoint 2 integration are implemented locally. The
application uses migration `0006_m3_artifacts.sql`, atomic canonical/M2/M3 CAS,
a startup-compiled production graph, a separate workflow SQLite database, live
FastAPI routes, and the wired React workspace. Promotion remains a separate
quality-owner decision.

## Observable outcome

After E3 is accepted, a user can turn the current accepted Critical Moment Map
into an editable `Decision and Evidence Ledger v0.1`. Every decision entry
shows alternatives, reasons, the decision, actions and observed results. Every
material statement carries its source/derivation, evidence disposition and
confirmation state. Missing results remain visibly unresolved and conflicting
evidence remains conflicting.

Checkpoint 2 now integrates migration `0006_m3_artifacts.sql`, SQLite CAS,
canonical M3 projection, strict local inference DTOs, a startup-compiled M3
LangGraph, FastAPI routes, OpenAPI export, and the live React workspace. The
application database remains canonical truth; the separately configured
workflow database contains only bounded cursor state.

Deep-audit correction migration `0007_m3_policy_decisions.sql` persists each
sanitized Runtime policy decision outside the LangGraph cursor. The public
failure adapter maps internal Runtime reason codes to the stable M3 failure
contract while retaining sanitized reasons for diagnosis.

The same migration retains bounded model identity, token counts and elapsed
time for each successfully validated M3 proposal. It never stores raw prompts
or responses. M3 nodes now emit sanitized durable LangGraph traces and bind
them to workflow checkpoints, matching the evidence discipline already used by
M1 and M2.

JSON Schema enforces the structural constraints emitted by Pydantic. Python
validation remains authoritative for conditional and cross-object
referential integrity (canonical statement existence, M2 projection identity,
moment-to-statement evidence membership, dependency membership, and durable
old/new correction comparison); JSON Schema
cannot query SQLite or compare immutable snapshots and is not claimed to do so.

## Upstream binding

M2 changes its `artifact_id` on create, edit and confirmation, and each accepted
transition also advances the canonical asset version. M3 therefore binds to
both:

- `base_m2_artifact_id`; and
- `base_canonical_version_id`.

An M2 correction invalidates M3 only when it changes a declared moment or
statement dependency. An invalidated ledger remains visible as history and
must not be presented as current.

## Contract and public examples

- Python contract:
  `app/experience_asset/domain/m3.py`
- Artifact JSON Schema:
  `contracts/json-schema/decision-evidence-ledger-v0.1.schema.json`
- Workspace JSON Schema:
  `contracts/json-schema/m3-workspace-v1.schema.json`
- Truthful progress and stable failure JSON Schemas:
  `contracts/json-schema/m3-progress-v1.schema.json` and
  `contracts/json-schema/m3-failure-v1.schema.json`
- Machine-readable checkpoint:
  `contracts/checkpoints/e4-m3-preparation-v1.json`
- Public examples:
  `contracts/examples/m3-ledger-*.json` and
  `contracts/examples/m3-workspace-*.json`
- Failure/recovery scenarios:
  `contracts/examples/m3-negative-scenarios-v1.json`
- Isolated React preparation:
  `web/src/features/m3/`
- Append-only evidence templates:
  `evidence/templates/e4-m3/`

Regenerate or check only these isolated files:

```bash
python3 scripts/export_m3_preparation_contracts.py
python3 scripts/export_m3_preparation_contracts.py --check
```

## Proposed evidence semantics

Each ledger statement has two distinct labels:

1. `status` records whether the content is a source fact, user judgment, Agent
   inference or unresolved;
2. `evidence_disposition` records whether its evidence is supported,
   conflicting or unresolved.

A supported statement without explicit evidence is rejected before
persistence. A missing alternative, reason, decision, action or observed
result is represented by an explicit `UNRESOLVED` statement for that role; the
Agent may not fill it with a plausible invention. A `USER_JUDGMENT` requires a
trusted user-confirmation transition and timestamp.

## Proposed bounded workflow

The machine-readable topology is in
`contracts/checkpoints/e4-m3-preparation-v1.json`. The proposed budgets are:

- structured-output repairs: `2`;
- per-node retry: `1`;
- re-plan: `1`;
- total model calls: `4`.

These values are reviewable E4 contract choices, not accepted historical facts.
Exhaustion reaches an explicit safe terminal. No whole-run unbounded retry is
allowed.

The LangGraph checkpoint allowlist contains only identifiers, counters, hashes,
selected edges, sanitized finding codes and safe user messages. Raw source
text, canonical payloads, prompts/responses, tool arguments/observations and
rendered output are forbidden. SQLite remains canonical truth.

`app/experience_asset/application/m3/recovery.py` makes the proposed recovery
order executable without integrating the production graph: prefer a bounded
structured repair, use the single re-plan only after repair exhaustion, then
safe-stop without persisting a ledger. The helper is pure and cannot call the
model, dispatch a tool or write canonical state.

## Tool and permission boundary

Model tool-call output is always an inert proposal. The Runtime must validate
the tool allowlist, arguments, asset/version identity, scope, permission,
privacy and any required human approval before dispatch. A model-supplied
`permission_granted=true` is invalid. Permission denial is a visible
`POLICY_BLOCKED` terminal and produces no tool effect.

## Error and progress contract

`M3ProgressV1` reports only the actual workflow stage and consumed/frozen
repair, re-plan and model-call budgets. It intentionally has no public
percentage or ETA. Terminal stage, progress state and terminal result must
agree.

`M3FailureV1` maps stable public error codes to safe terminal states. Permission
and tool-policy failures map to `POLICY_BLOCKED`; invalid structured output and
budget exhaustion map to `INVALID_MODEL_OUTPUT`; upstream drift maps to
`NEEDS_USER_INPUT`. Raw prompts, rejected arguments and private observations
are never part of this public error contract.

## Checkpoint 2 integrated files

- `app/experience_asset/workflow/m3_graph.py` and `m3_state.py`;
- `app/experience_asset/application/m3/` and `domain/m3.py`;
- `app/experience_asset/persistence/migrations/0006_m3_artifacts.sql`,
  `0007_m3_policy_decisions.sql`, and repository atomic transition methods;
- `app/experience_asset/api/routes/m3.py` and generated OpenAPI;
- `tests/integration/test_m3_langgraph.py` and `test_m3_api.py`;
- `web/src/features/m3/`, including API and workspace interaction tests;
- `scripts/run_e4_m3_local_evidence_server.py` and `web/e2e/m3.spec.ts` for
  reproducible non-GPU live-browser evidence.
- `scripts/run_e4_w7900_gate.py`,
  `scripts/capture_e4_m3_evidence.py`,
  `scripts/capture_e4_m3_negative_evidence.py`, and
  `scripts/finalize_e4_w7900_packet.py` for exact-commit W7900 execution and
  sanitized packet generation.
- `docs/E4_M3_W7900_HANDOFF.md` is the complete execution-only handoff for
  `kinnyuww`; no W7900-side implementation is delegated.

## Verification and evidence plan

Preparation checks:

```bash
python3 scripts/export_m3_preparation_contracts.py --check
pytest -q tests/unit/test_m3_contracts.py
ruff check app/experience_asset/domain/m3.py \
  app/experience_asset/application/m3 \
  app/experience_asset/workflow/m3_state.py \
  scripts/export_m3_preparation_contracts.py \
  tests/unit/test_m3_contracts.py
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
cd web
npm run test
npm run typecheck
npm run lint
npm run build
```

The non-GPU live browser journey uses only the public fixture worker and real
loopback FastAPI/SQLite/React:

```bash
python scripts/run_e4_m3_local_evidence_server.py \
  --database /tmp/e4-m3.sqlite3 \
  --workflow-database /tmp/e4-m3.workflow.sqlite3 \
  --port 8080
cd web
E2E_LIVE_BASE_URL=http://127.0.0.1:8080 \
VITE_PROXY_TARGET=http://127.0.0.1:8080 npm run e2e -- m3.spec.ts
```

This proves browser/API/persistence wiring only. It does not claim local-model,
ROCm, W7900, quality-owner, or performance verification.

The exact-commit W7900 command is frozen in
`docs/E4_M3_W7900_HANDOFF.md`. It generates a candidate for
`evidence/milestones/e4-m3-w7900/<run_id>/` covering the real localhost model
create/regeneration path, bounded repair, unsupported-claim rejection, forged
permission rejection, zero-effect permission denial, restart/idempotency and
correction invalidation. The browser journey remains separately proven by the
local loopback evidence packet.

Only physical W7900 execution and independent quality-owner promotion remain
externally pending. No W7900 or performance result is claimed before that run.

## Rollback

Before production integration, remove only the isolated E4 preparation files.
After integration, revert the reviewed E4 commits and preserve prior evidence
packets append-only. Never rewrite shared history.
