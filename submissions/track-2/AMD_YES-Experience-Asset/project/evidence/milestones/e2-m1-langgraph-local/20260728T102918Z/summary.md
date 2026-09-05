# E2 / M1 LangGraph Local Candidate Evidence

Result: `LOCAL_CANDIDATE_COMPLETE_COMMIT_BINDING_PENDING`

This packet records the complete non-W7900 local candidate for Issue #15 and
Draft PR #16. The implementation is still an uncommitted working-tree change
on top of `30d7c35248bbb1bbb16838641679f91ad9e308e2`; therefore this packet is
not checkpoint acceptance evidence and must not be relabeled as exact-head
evidence.

## Implemented local behavior

- One real eight-node LangGraph is compiled during FastAPI startup and injected
  into the M1 route.
- Production no longer imports or calls `DurableFakeAgentLoop`; that class
  remains only as the accepted E1 fixture.
- SQLite Asset Repository remains canonical truth. A separate LangGraph SQLite
  saver owns the graph cursor.
- Checkpoint state is limited to typed identities, workflow/topology, cursor,
  projection sequence and terminal candidate. Source text, raw prompts, raw
  model responses and complete assets are excluded.
- Allow, policy denial, model failure, restart, missing/corrupt/incompatible
  checkpoint, stale version, cancellation, tool failure and repository failure
  all produce reviewable behavior and explicit durable terminal states.
- Restart tests prove model and tool effects are not replayed.
- A started-but-indeterminate tool effect is not replayed after restart.
- Resume fails closed when workflow, base version, model, loopback server,
  model-config hash or code-commit identity changes.
- Direct and indirect imported instructions cannot expand permission or
  dispatch a tool.
- Policy denial produces a DENIED audit record with zero ToolExecutor calls.
- `CODE_COMMIT` is stored with each workflow run; `UNCOMMITTED` is permitted
  only for local development.

Workflow identity:

```text
workflow_version = experience-asset/e2-m1/v1
topology_hash = 2ed5001b1c7bf177335e0bbff59e964b115c1a90c8454f3784e9e695e3cbd707
```

## Reproduction result

- clean Python 3.12.13 editable install: PASS;
- backend: 99/99 and Ruff PASS;
- public QA: 31/31;
- public artifact gate for `chair_incomplete`: PASS;
- generated contracts: current;
- frontend: 95/95, contract provenance 15/15, typecheck/lint/build PASS;
- real loopback FastAPI/React Playwright: 17/17;
- repository contract gate and disclosure/credential boundary: PASS;
- `git diff --check`: PASS.

The packet includes bounded public artifacts: a public Experience Asset,
state-derived progress, M1 workspace, current-source retrieval Trace,
checkpoint-linked LangGraph node Trace, SHA-256 manifest and an inspected live
UI capture. The first artifact-gate attempt used `chair_public_complete`,
whose expected M5 route decisions are intentionally outside E2; that failed
observation is retained in the manifest. The corrected E2-scoped
`chair_incomplete` artifact passed without fabricating future route
eligibility.

## Responsibility boundary

`Eas000n` owns the implementation and local checkpoint-2 candidate.
`kinnyuww` owns:

- independent checkpoint-2 review;
- W7900/ROCm/Qwen2.5-14B real-model execution;
- Serving Reference S1;
- checkpoint-3 Evidence / Promotion decision;
- PR merge and E2 promotion.

No W7900, ROCm, real-model, performance or promotion claim is made here.

## Required next transition

After the user explicitly authorizes Git commit/push:

1. commit the reviewed implementation;
2. rerun the same gates with `CODE_COMMIT` set to the exact new SHA;
3. create a new clean-tree exact-head packet that references this packet;
4. update PR #16 for independent checkpoint-2 review;
5. hand the exact approved head to `kinnyuww` for the bounded W7900 work.

This dirty-tree candidate is retained rather than silently rewritten.
