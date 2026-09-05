# E3 / M2 PR #20 requested-change closure

Result: `E3_FIX_READY_FOR_QUALITY_REVIEW`

This append-only packet supersedes
`evidence/milestones/e3-m2/20260729T075518Z/` and binds the requested-change
implementation to clean commit
`62216d0e5aa16f2a753d648043e109e82df8a54b`.

## Completed behavior

- M2 no longer labels every M1 statement as a change. Cue, change or turning
  point, and surprise roles require explicit current-source wording and remain
  linked to source statement IDs.
- The UI shows cue, change or turning-point, surprise and conflict evidence
  roles for each moment.
- An ordinary user no longer enters an M1 Version UUID. The UI reads the
  current canonical M1 identity and refreshes it immediately before initial
  generation or invalidation recovery; the backend compare-and-swap check
  remains authoritative.
- A real Chromium/FastAPI test covers first creation, role presentation,
  depended M1 correction, visible M2 invalidation and latest-version
  regeneration.
- The implementation owner prepared the complete W7900 execution route:
  exact-commit and clean-tree checks, W7900/ROCm/PyTorch/vLLM environment,
  full frozen-model hash, Tool Call, Runtime allow/deny/restart, M2 regressions,
  sanitized artifacts, failure retention and automatic packet finalization.

## Verification

- backend: 131/131 and Ruff pass;
- public QA: 32/32 and contract gate pass;
- frontend: 113/113, typecheck, ESLint, production build and 15/15 contract
  provenance pass;
- real browser/API M1→M2 journey: 1/1 pass;
- sanitized E3 artifact capture and W7900 runner dry-run: pass.

The first direct evidence-capture attempt found that an editable Python install
could resolve another checkout. That failed observation is retained in the
manifest. The script now binds imports to its own repository root, and direct
execution plus regression tests pass.

## Remaining boundary

Real W7900 execution remains `NOT_RUN_DELEGATED`. `kinnyuww` must run the
prepared command in `docs/E3_M2_W7900_HANDOFF.md`; this packet does not claim
W7900, ROCm, vLLM, latency, throughput, VRAM or optimization success.
Independent review and merge also remain with `kinnyuww`.
