# E5–E7 integration evidence — 2026-08-05

- Head: `fc32868` on `integration/e5-e8-a0`
- Independent decision: **`CONDITIONAL`**
- W7900 execution status: **`NOT_RUN_INFRA_BLOCKED`**

## What this packet does claim

E5, E6 and E7 are integrated at one exact head, and the seams the execution
package names for E6 — real E5 projection, SQLite, API, App, persistence and
restart, exact-bound approval — are exercised by tests that drive the real
application rather than a contract-equivalent mock.

Both audited producer/consumer gaps are closed and verified against data the
product actually produces:

- **`sensitivity_tags` producer.** E1–E5 never populate the field, so PR #31's
  tag-driven detector finds nothing on a real asset. A deterministic offline
  text detector now supplies proposals, the review records which producers ran
  and binds that into `review_hash`, and a review with no producer behind it
  fails closed with `NO_PRIVACY_PROPOSAL_SOURCE` instead of looking clean.
- **`EvidenceStrength.DIRECT`.** The predicate accepts `DIRECT` *or* `INDIRECT`,
  so it was not weakened and not changed. What was added is proof at the
  integrated head: no statement produced by the real M1–M4 path carries
  `DIRECT`, all five `RouteDecision`s execute, and `CUSTOMER_EVALUATOR` returns
  `INELIGIBLE` / `MISSING_QUALIFYING_CONTEXT`.

PR #34's two reported blockers were rechecked against live code, not against
the fix author's own fixtures:

- the live `route_draft_binding_hash` reproduces the approval hash E7 consumes,
  and each of the three bound inputs is shown to move it;
- an expired deletion request does not lock the asset — the retry is carried
  through to a **completed** deletion (`SUCCEEDED`, counts `(0, 0)`, files gone),
  which PR #34's own test stopped short of.

One further defect was found and fixed during this integration: the public
export read the canonical snapshot's placeholder route decisions and published
"every route blocked for missing evidence" while the product surface showed
three routes eligible. `to_public_asset` now accepts the live M5 decisions, and
a regression test pins both the fixed behaviour and the failure mode.

## What this packet does not claim

It is **not** an `A0` freeze and must not be read as one.

- No model service was called. Every model-facing step used a scripted
  deterministic client, so there is no locality, latency, throughput, VRAM or
  task-success claim here.
- The input is a deterministic scaffold, **not** one of the seven public chair
  fixtures. The seven-fixture matrix needs the real ingestion path against a
  live local model and was not run.
- The public adversarial and failure checklist was not executed.
- E5 T11 — the external W7900 exact-head local-inference gate — remains open.
- `8192` remains the only device-verified context window; `20480` remains a
  business budget ceiling and is not verified deployment capability. Neither is
  exercised here.

## Why W7900 is `NOT_RUN_INFRA_BLOCKED`

No Radeon Cloud Pod was reachable from the session that performed this
integration. The repository deliberately records no Pod host identifier and no
Radeon Cloud SSH host is configured locally. The failure is retained rather than
worked around: no CPU or local run is presented as device evidence, and every
non-GPU task continued.

## Retained artifacts

| File | SHA-256 |
|---|---|
| `artifacts/canonical-asset.json` | `0ae928efdada21aa01b8fa6f08ea6c5a0887655afacf1f9aeb1704ce7848a91a` |
| `artifacts/retrieval-trace.json` | `2d436a1705bf44ed4ba6d0aace1af942170eddf436dad02a63d801bacdeae352` |

The asset-schema check was run against `qa/expected/chair_public_complete.expected.json`
and its one `HIGH` finding is retained rather than suppressed: the scaffold
asset is not that fixture's content, so its privacy findings differ and the
public route lands on `eligible` instead of `eligible_after_privacy_approval`.
That result is reported as what it is — a mechanism check, not a fixture-matrix
result.

## Rollback

```bash
git checkout integration/e5-e8-a0 && git reset --hard d32730f
```

`d32730f` is `main` at the point the integration branch was cut. Nothing in this
lane has been merged to `main`.
