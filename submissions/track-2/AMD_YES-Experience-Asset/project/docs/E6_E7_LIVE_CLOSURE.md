# E6→E7 live approval and delivery closure

## Purpose and Track 2 relevance

This is the local-only product path from M5 route/privacy evaluation to a
reviewable E7 export. It demonstrates the Track 2 capabilities that matter to
this project: a startup-compiled LangGraph workflow, deterministic tool/policy
boundaries, explicit human approval, persistent local state, and a complete
user-visible task loop. It does not make a W7900 or model-performance claim.

## Authority boundaries

- The canonical SQLite repository remains the source of truth for the current
  Experience Asset and immutable version lineage.
- `M5ProductionGraph` stores only IDs, hashes, counters, and safe outcomes in
  LangGraph checkpoints. It re-reads canonical state inside each operation.
- `M5Store` owns persisted route matrices, privacy reviews, and approvals.
- `E7DeliveryRepository` owns saved `RouteDraft` envelopes and export records.
- The browser may request an action, but it cannot submit a `RouteDraft` object
  or `ApprovalRecord` as authority. The backend loads both from local storage.

## Product sequence

1. `POST /api/v1/m5/assets/{asset_id}/evaluate` runs the startup-compiled M5
   graph and persists the current five-route matrix plus privacy review.
2. `POST /api/v1/delivery/assets/{asset_id}/drafts` saves one route/language
   draft bound to the exact canonical hash, relation projection, live route
   decision, privacy state, renderer input, and statement IDs. Live product
   claims are selected verbatim from canonical evidence; attaching a valid ID
   to browser-authored prose cannot turn that prose into supported evidence.
   Titles, section labels, and notices use fixed neutral local templates, so an
   unsupported claim cannot be moved into a field outside the claim validator.
3. `GET /api/v1/delivery/drafts/{draft_id}/preview` renders a private preview.
   Preview grants no external-share permission.
4. `POST /api/v1/m5/assets/{asset_id}/approvals` accepts only a stored
   `route_draft_id`, the explicit `APPROVE_SHAREABLE_EXPORT` action, and an
   idempotency key. The server derives every other binding, persists the
   sanitized command outside checkpoint state, and validates it through the
   startup-compiled M5 graph.
5. `POST /api/v1/delivery/drafts/{draft_id}/exports` accepts an `approval_id`.
   External export succeeds only when the persisted approval, current M5
   context, and saved E7 draft still match exactly.

Creating a successor draft supersedes the prior one. Re-evaluating an unchanged
immutable input is idempotent and preserves its exact approval; a changed policy
outcome, canonical version, route matrix, privacy review, renderer input, route,
language, or statement binding fails closed. Legacy approvals that predate exact
RouteDraft UUID binding remain readable for audit but cannot authorize export.

The relation projection is also exact: one confirmed relation binds its own ID,
both version identities, the related version's real content hash, and projection
identities. Multiple active confirmations are treated as ambiguous/stale rather
than silently choosing the first database row.

## Privacy content changes

`GENERALIZE` and `REMOVE` require the user to provide an explicit canonical
content edit. The M5 surface sends the user to M1 rather than calling a dead
resolution route. The resolution endpoint and graph still return
`CANONICAL_CHANGE_REQUIRED` and do not save a false resolved state when no such
edit exists. The existing M1 editing/versioning path creates the successor
canonical version before M2-M4 are rebuilt and M5 is evaluated again. Corrected,
rejected, and unresolved statements are excluded from subsequent privacy scans.

## Recovery semantics

On startup, an incomplete M5 checkpoint is resumed only if its workflow version,
topology hash, code commit, deterministic model identity/configuration, command,
asset/version/content hash, and relation projection still match durable truth.
Business writes use workflow effect keys so a restart never blindly repeats an
effect whose completion is uncertain. An evaluation with no final draft ends as
`NEEDS_USER_INPUT`, not as a misleading successful approval flow.

## Local reproduction

```bash
uv run pytest tests/integration/test_m5_api.py tests/integration/test_delivery_api.py -q
cd web
npm test -- --run src/features/m5/M5Workspace.test.tsx
npm run typecheck
```

The integration test closes save → preview → approval → export across an
application restart and separately proves that an approval for another draft
is rejected. W7900 execution remains a separate evidence step.
