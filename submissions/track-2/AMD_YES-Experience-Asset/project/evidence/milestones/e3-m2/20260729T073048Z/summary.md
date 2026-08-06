# E3 / M2 LangGraph conformance evidence

Result: `E3_EXACT_COMMIT_READY_FOR_QUALITY_REVIEW`

This append-only packet supersedes the earlier E3 packet for the current
candidate. It is bound to exact implementation commit
`e37b94cdb59147f8d2c41fc37a4d7a37263e5e64` on
[#20](https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/20). The
packet files themselves are added by the following evidence-only commit, so
the implementation identity remains unambiguous.

## Demonstrated behavior

- M2 generation now runs through a real five-node LangGraph subgraph compiled
  once at application startup. SQLite remains canonical business truth, while
  the shared LangGraph SQLite checkpointer stores only bounded orchestration
  state.
- Graph checkpoints and traces contain identifiers and sanitized outcomes, not
  source text, canonical asset payloads, prompts, model responses or rendered
  output.
- Node effects are idempotent. The public tests demonstrate stale-input
  safe-stop, checkpoint restart and resume without a duplicate M2 artifact or
  canonical version.
- Agent output can only propose critical moments. Every moment must receive an
  explicit trusted user decision before the map can be confirmed.
- `USER_CONFIRMED` entries carry a trusted confirmation timestamp;
  `UNRESOLVED` entries remain visible and lead to `COMPLETE_WITH_GAPS`.
- Editing the title of a previously confirmed moment withdraws that moment's
  old criticality confirmation, reopens M2 and requires a fresh user decision.
- Related M1 corrections still invalidate dependent M2 artifacts; unrelated M1
  edits do not.
- An invalidated M2 remains visible and read-only. Explicit regeneration after
  the corrected M1 is accepted creates a replacement map bound to that new M1
  version.

## Verification result

- backend: 126/126 tests and Ruff PASS;
- public QA: 32/32 and contract gate PASS;
- frontend: 108/108 tests, typecheck, production build and 15/15 contract
  provenance checks PASS;
- ESLint: PASS with no warnings;
- contract export and diff check: PASS;
- real loopback FastAPI/Vite/Playwright journey: PASS.

The standard Playwright wrapper encountered a local npm TLS error, so the
already cached Playwright CLI package was used offline. The same CLI-first flow
and the in-app browser verification completed successfully. The browser
console's two 404 observations were the missing favicon and the expected M2
lookup before its first creation.

## Evidence and decision boundary

The four screenshots use only a synthetic chair-selection scenario. They show
trusted per-moment decisions, post-confirmation edit reopening, correction
invalidation, and explicit regeneration against the newly accepted M1.

This is exact-commit local evidence, not independent quality-owner acceptance,
merge authorization, W7900 evidence or a performance claim. PR #20 must still
be reviewed and merged by the quality owner.
