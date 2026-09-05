# E8 A0 integrated W7900 functional acceptance

## Outcome and scope

- Result: **PASS** for the integrated A0 functional checkpoint on the Radeon
  Cloud W7900. This is not the E8 performance Baseline and makes no ranking
  claim.
- Exact implementation commit: `c9ec07489d17a2abb74bac66a23ade2c775c1b06`
  on PR #52.
- The application and vLLM remained separate and bound to pod localhost. A
  temporary local SSH tunnel was used only for the browser acceptance test.
- The inspected flow covered current-experience capture, semantic extraction,
  decision evidence, the insight/boundary map, correction-driven invalidation
  and regeneration, route/privacy review, and private three-format delivery.

## Reproduction

- Hardware: W7900 (`gfx1100`, 96 CUs, 48 GiB VRAM), ROCm/HIP 7.2.
- Model: local `Qwen3.5-9B` BF16 served by vLLM 0.26.0, 20K maximum context,
  thinking disabled for bounded structured output.
- Public fixture: the synthetic shopping-experience journey in
  `web/e2e/m4.spec.ts`, SHA-256
  `2991389c5a3f0c79d38626377ab2980d11d6e7d8ceeb1ddbaeed1f51bf3fe889`.
- The exact commands and exit status are recorded in `manifest.json`.

## Observed results

- Repository contract checks, the complete backend test suite and Ruff passed.
- Frontend lint, typecheck, build, 18/18 contract provenance checks, 223/223
  unit/component tests and 16 non-live browser tests passed.
- The exact-commit live W7900 browser journey passed in 2.0 minutes. It generated
  M1-M4, opened canonical evidence, invalidated downstream state after an
  upstream correction, re-confirmed the corrected M3 artifact and regenerated
  M4.
- A real M5 evaluation exposed all five routes. `PRIVATE_SELF` was eligible;
  disallowed external routes remained blocked or ineligible. The private path
  generated self-contained HTML, Markdown and JSON artifacts.
- Failed observations were retained: unconstrained M4 produced unusable gaps,
  decision-only core grounding could not power the evidence drawer, and the UI
  initially hid the only eligible private route. Request schemas, Runtime
  validation and UI behavior now close those defects.

## Decision and history

- Decision: `PASS` for merging the integrated A0 checkpoint.
- Still pending: the reduced Stage 2 A0-versus-A1 performance comparison, final
  evaluator-facing deployment choice, demo media, PPT/Poster and official
  contest PR.
- Raw logs and generated product artifacts remain under
  `/workspace/amd-track2-agent`; only this sanitized packet is stored in Git.
- Rollback: revert `c9ec074`; the parent is retained for diagnosis but is not a
  promoted A0 state.
