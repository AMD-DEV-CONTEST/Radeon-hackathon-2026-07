# E2 / M1 LangGraph Commit-Bound Local Evidence

Result: `PASS_REVIEW_PENDING`

This packet binds the complete non-W7900 E2/M1 candidate to source commit
`0a306411f1468f4518db9ffdf4166fcd23cc7f51`.

## Proven locally

- FastAPI compiles one real eight-node production LangGraph at startup and
  injects that runner into the M1 route.
- The production path does not call the E1 `DurableFakeAgentLoop`.
- SQLite Asset Repository remains canonical truth; the separate LangGraph
  SQLite saver is the sole graph-cursor authority.
- The Agent closes allow, policy-deny, permission-deny and all three
  model/format-failure paths with explicit durable terminal states.
- Restart does not duplicate model or tool effects. An indeterminate started
  effect is not replayed.
- Missing, corrupt, stale, workflow-mismatched and runtime-identity-mismatched
  checkpoints stop safely.
- Direct and indirect imported instructions cannot grant permission or dispatch
  an unallowlisted tool.
- Graph checkpoints and node Trace contain bounded typed references and
  metadata, not raw prompts, responses, source text or the complete asset.
- The public `chair_incomplete` asset, progress and current-source retrieval
  Trace pass the artifact gate; the inspected UI capture contains only the
  synthetic public scenario.

## Verification

- backend pytest: 99/99;
- public QA: 31/31;
- frontend Vitest: 95/95;
- contract provenance: 15/15;
- real FastAPI/React Playwright: 17/17;
- clean Python 3.12.13 install and sync/async SQLite saver round-trips: PASS;
- Ruff, contract gate, artifact gate, schema/OpenAPI export, typecheck, lint
  and build: PASS.

## Remaining boundary

This is checkpoint-2 local evidence, not E2 promotion. `kinnyuww` still owns
independent review, the exact-reviewed-head W7900/ROCm/Qwen2.5-14B run, Serving
Reference S1, checkpoint 3, merge and E2 promotion. No real-model, GPU,
performance or optimization claim is made here.
