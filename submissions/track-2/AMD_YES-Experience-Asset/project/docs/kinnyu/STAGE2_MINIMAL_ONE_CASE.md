# Stage 2 deadline-minimal paired integration check

## Authority and status

- Status: **OWNER-APPROVED / EXECUTE NOW**
- Effective: 2026-08-06 AEST
- This file supersedes every larger Stage 2 matrix, repetition, drift-bookend,
  statistical-sample and 60-minute requirement. It does not alter the retained
  Stage 1 evidence or ranking.
- Purpose: produce the smallest honest complete-Agent integration comparison
  that can still support the final report before the submission deadline.

## Exact scope

Run one identical public synthetic business case under each Profile:

1. `A0 = merged complete Agent + S0`;
2. `A1 = the same commit, model, input and generation settings +
   P1-prefix-cache`.

The already accepted A0 run in
`evidence/milestones/e8-a0-w7900/20260806T122806Z/` is the S0 observation. Run
P1 once against the same journey. Do not add fixtures, repetitions, a final S0
bookend, concurrency testing, model judging, tuning or another Candidate.

Only the P1 flag may differ:

```text
--enable-prefix-caching
```

Use the current 20K Qwen3.5-9B BF16 application configuration. Do not restore
the historical 8K Stage 1 limits merely for this check.

## Minimum retained result

Record for S0 and P1:

- exact commit, model/revision, vLLM/ROCm/W7900 identity and launch command;
- case identity/hash and terminal PASS/FAIL;
- wall-clock business-flow time and available model/API latency;
- peak VRAM when available;
- deterministic schema, evidence, privacy/permission and delivery result;
- failure, rollback and any missing measurement.

No retry is required for a product failure. One startup retry is allowed only
for a labeled infrastructure failure. Missing data is `NOT_MEASURED`, never a
fabricated PASS.

## Decision and claim boundary

- P1 may become the launch Profile only if the single business case completes
  with the same deterministic safety/quality result and no new integration
  defect. Otherwise keep S0.
- The final report must call this a **one-case complete-Agent integration
  check**, not a statistically representative latency benchmark.
- General service-performance claims come from the frozen Stage 1 packet. The
  one-case Stage 2 result only shows whether that winner also runs safely in
  the integrated product and gives the observed case delta.
- After the paired record, immediately produce the sanitized comparison and
  E9-ready paragraph/chart data. No additional Stage 2 approval gate remains.

## Completion

Stage 2 is complete when the P1 run, paired comparison, selected/rollback
Profile and bounded claim text are retained. Submission work must not wait for
any larger benchmark.
