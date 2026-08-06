# E2 / M1 Local Vertical-Slice Correction Evidence

Result: `LOCAL_CHECKPOINT_2_READY_FOR_REVIEW`

This packet describes implementation commit
`3606cba7be473041594655d9525df811fd9196d2` on
`codex/e2-m1-experience-brief` and Draft PR
[#16](https://github.com/kinnyuww/amd-devmaster-track2-agent/pull/16).

## Corrected behavior

- Adjacent Chinese sentences such as `第一句。第二句。` are separate
  source-supported Statements without requiring whitespace.
- The same bounded behavior covers adjacent English sentences while avoiding
  decimal and common lower-case URL/domain boundaries.
- The original complete-source span, source reference and Statement order are
  preserved.
- Chinese or English same-day return/exchange claims are compared with
  multi-day, multi-week or multi-month use/return claims.
- A possible conflict produces one visible user question linked to the
  affected source Statement IDs; the Runtime does not choose a timeline.
- A same-day return without a competing longer-duration claim is not marked as
  a conflict.

No public schema, OpenAPI, migration, RAG boundary, route behavior, governance
document or W7900 configuration changed.

## Reproduction result

- public QA: 31/31;
- backend: 81/81 and Ruff PASS;
- generated contracts: current;
- frontend: 95/95, contract provenance 15/15, typecheck/lint/build PASS;
- real loopback FastAPI/React Playwright: 17/17;
- repository contract gate: PASS.

The first targeted test run exposed one retained failure: the initial sentence
boundary pattern split the ASCII exclamation in an HTML fixture comment opener.
The ASCII boundary was constrained to sentence-follow contexts, while Chinese
full-width punctuation remains whitespace-independent. The targeted and full
test suites then passed.

## Decision boundary

This is local evidence for independent review of checkpoint 2. It is not a
quality-owner `PASS`, E2 promotion, permission to merge, Serving Reference S1,
W7900 evidence, the E8 Baseline, or a performance claim. W7900/ROCm/vLLM
verification remains explicitly pending.
