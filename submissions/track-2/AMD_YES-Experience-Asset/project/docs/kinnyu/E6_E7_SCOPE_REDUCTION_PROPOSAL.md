# E6/E7 scope reduction proposal

- Date: 2026-08-01
- Author: `1olaqua616-web`
- Decision owner: `kinnyuww` (quality owner)
- Status: **PROPOSED / amended after quality review / pending owner decision**
- Affects: E6/M5 and E7 only. E5/M4 and its GraphRAG scope are **not** reduced.

This document proposes an explicit owner scope decision under
`L3_ENGINEERING_PLAN.md` Section 12, which states that removing an approved AC
requires such a decision and that a missed date is a re-planning signal rather
than silent permission to claim incomplete work. Nothing in the approved E6/E7
contract is rewritten by this document. If the proposal is rejected, the
current definitions stand unchanged.

## 1. Why

### 1.1 The remaining window is four days

`COMPETITION_READINESS_CHECKLIST.md` places T15 (clean reproduction and timed
rehearsal) on August 5 and T16 (submission) on August 6 at 12:00 internal. The
actual implementation window is **August 1–4**.

Still to be delivered in that window: E4 acceptance, E5, E6, E7, E8-A, E8-B and
T14 (English specification, README, video script, PPT/Poster).

### 1.2 Measured velocity

| PR | Milestone | Opened | Merged | Elapsed | Real W7900 run |
|---|---|---|---|---|---|
| #16 | E2 | 2026-07-28 03:59 | 2026-07-28 13:30 | 9.5 h | no |
| #20 | E3 | 2026-07-29 06:02 | 2026-07-29 13:17 | 7.2 h | no |
| #22 | E4 | 2026-07-29 14:04 | 2026-08-01 08:27 | **66.4 h** | yes; exact-head gate passed |

E2 and E3 reached merge without a real W7900 result.
`evidence/milestones/e3-m2/20260729T103358Z/manifest.json` records
`environment.w7900.execution_status = "NOT_RUN_DELEGATED"`. E4 was the first
milestone to combine a device gate with real-model debugging and repeated
integration review. Its elapsed time therefore demonstrates schedule risk, but
the difference must not be attributed to GPU execution alone. The final exact
head `5129963` passed the one-command W7900/ROCm gate; retained evidence is at
`/workspace/amd-track2-agent/evidence/e4-m3-w7900/pr22-5129963-final-20260801T2040Z/raw/`.

E8 cannot skip it.

### 1.3 The arithmetic

| Item | Owner | Estimated person-days |
|---|---|---|
| E4 completion | complete | 0 |
| E5 / M4 + GraphRAG (**unchanged**) | `1olaqua616-web` | 3–5 |
| E6 / M5 | `Eas000n` | 1.5–2.5 |
| E7 | `1olaqua616-web` | 1.5–2.5 |
| E8-A W7900 Baseline | `Eas000n` | 2–3 |
| E8-B product/UX evidence | `1olaqua616-web` | 1.5–2.5 |
| T14 English materials | all | 1–2 |
| T15 / T16 | all | 0.5 |
| **Total** | | **11–18** |

Available: four days × two implementation lanes = **8 person-days**. The quality
owner is a gating role and does not produce milestone code.

The dependency order in `E2_E8_PIPELINE_EXECUTION_PLAN.md` permits parallelism
only between E8-A and E8-B, and only after E7 merges. The shortfall therefore
cannot be absorbed by running lanes concurrently.

### 1.4 Why E6 and E7 rather than E5

`L3_ENGINEERING_PLAN.md` Section 12 defines the non-negotiable contest slice as
a complete useful user journey, a visible Agent loop, local W7900/ROCm proof,
durable state, bounded tool/permission behaviour, route/privacy correctness,
**one polished selected deliverable**, and reproducible evidence.

E5 carries the judge-visible local RAG on W7900, which is the Track 2
differentiator and has an approved MVP specification behind it
(`GRAPHRAG_MVP_SPEC.md`, 769 lines) plus a fully enumerated Issue. E6 and E7
deliver route, privacy, approval and rendering behaviour that is valuable but
not differentiating, and — unlike E5 — neither has an MVP-level design today.
Each is defined by six bullets in `L3_ENGINEERING_PLAN.md`.

Reducing E5 would remove the differentiator. Reducing E6/E7 removes matrix
breadth while keeping every user-visible path intact.

## 2. Proposed E6/M5 boundary

### 2.1 Retained

- All five `RouteDecision`s are still evaluated, with deterministic reason
  codes and user-visible explanation. The "five route decisions" claim is
  preserved.
- `Route Readiness Matrix` showing all five outcomes.
- User-visible route outcomes `READY`, `BLOCKED`, and `INELIGIBLE`, each with a
  deterministic reason code and supporting/missing statement IDs. The internal
  enum may stay lean, but it must preserve these observable distinctions.
- The per-route minimum content contract in `L3_ENGINEERING_PLAN.md` Section 5.7
  remains the basis for eligibility. It is not relaxed.
- `PrivacyFinding` with category, affected reference, severity, explanation and
  the user-visible `KEEP`, `GENERALIZE`, and `REMOVE` actions. A user may also
  explicitly acknowledge a surfaced residual risk where the approved contract
  permits it.
- One shared version/hash-bound `ApprovalRecord` mechanism for every
  external-audience shareable export, including `PUBLIC`; route-specific
  approval implementations are not required.
- Stale-approval invalidation whenever any bound input changes. A single binding
  hash may cover canonical version, route, language, risk resolution and
  renderer inputs instead of implementing separate invalidation subsystems.
- Public fixtures: complete, privacy-risk.

### 2.2 Deferred beyond P0

Deferred means recorded as not-implemented with a visible reason, not silently
dropped, and not claimed as passing.

- `ELIGIBLE_AFTER_PRIVACY_APPROVAL` as a distinct internal fourth state. The
  route may use the retained visible `BLOCKED` outcome with a privacy reason
  until the finding is resolved.
- Separate approval engines per external route; the retained generic approval
  record is sufficient.
- Exhaustive per-route UI polish and combinatorial fixture execution inside E6.
  Route-ineligible and correction fixtures remain required before final E8
  acceptance and cannot be removed from the final public suite.

### 2.3 AC impact

Implementation breadth is reduced for AC-05, AC-07 and AC-08, but their
observable acceptance behavior is retained. AC-09, AC-10, AC-14–AC-18,
AC-22–AC-25 and AC-30 are unaffected. No AC is removed; each deferred internal
mechanism must be recorded in the E6 evidence packet as an explicit non-goal.

### 2.4 Expected saving

1.5–2.5 person-days reduced to approximately 1–1.5. This is an estimate, not
a measured commitment.

## 3. Proposed E7 boundary

### 3.1 Retained

- Stored route drafts in Chinese or English, user-selected, one language
  generated per draft as already specified.
- Preview, self-contained HTML, editable Markdown, and canonical JSON.
- Cross-render version/hash consistency between HTML, Markdown and JSON.
- `ExportRecord` states, including marking a prior export `SUPERSEDED` when a
  new one is created.
- Idempotent deletion with second confirmation, plus one visible failure and
  retry path.
- Public fixtures: complete, privacy-risk.

### 3.2 Deferred beyond P0

- Separate route-specific renderer implementations; all formats may be thin,
  deterministic projections of the same canonical route draft.
- The exhaustive injected filesystem/SQLite partial-failure matrix. One
  representative failure/retry case and idempotency regression are retained.
- Full supersession workflow beyond the `SUPERSEDED` state marker.
- Public fixtures: correction, route-ineligible.

### 3.3 AC impact

Implementation breadth is reduced for AC-06 and AC-12, but HTML, Markdown,
JSON, second-confirmation deletion, idempotency and visible retry behavior stay
observable and testable. AC-05, AC-08, AC-09, AC-14, AC-17, AC-18 and
AC-22–AC-25 are unaffected. No AC is removed; the same explicit-recording rule
as Section 2.3 applies.

### 3.4 Expected saving

1.5–2.5 person-days reduced to approximately 1–1.5. This is an estimate, not
a measured commitment.

## 4. What this proposal does not do

- It does not reduce E5/M4 or any part of the approved GraphRAG MVP scope.
- It does not reduce E8-A or E8-B evidence requirements.
- It does not touch retrieval phase integrity, Runtime permission,
  non-contamination, persistence/restart, contract synchronisation or the real
  W7900 claim requirements. Those remain hard gates.
- It does not weaken any acceptance criterion by changing its target to match
  produced output, remove any hard-negative case, or permit a fake-model result
  to stand in for a real device claim.
- It does not change the dependency order or milestone ownership.

## 5. Residual gap after this reduction

This proposal does not close the shortfall, and should not be read as doing so.

With E6 and E7 at approximately 1–1.5 person-days each, the remaining total is
about **10–16 person-days against 8 available**. The range is planning evidence,
not a delivery guarantee. The reduction preserves the differentiator but does
not by itself make the current plan fit.

Two further decisions are therefore still open and are **not** proposed here:

1. How to schedule the seven required public fixture categories across local
   functional gates and representative W7900 runs without removing AC-25
   coverage. E4 now has an exact-head real W7900 pass in addition to the earlier
   E1-A3 evidence, so the earlier "exactly one successful run" premise is no
   longer current.
2. Whether T14 English materials start now in parallel, as
   `COMPETITION_READINESS_CHECKLIST.md` already directs, rather than after
   product completion.

## 6. Rollback

Reject this proposal, or revert the commit that adds it. The approved E6/E7
definitions in `L3_ENGINEERING_PLAN.md` and
`E2_E8_PIPELINE_EXECUTION_PLAN.md` are annotated with a pointer to this
document but are otherwise unmodified, so rejection requires no content
restoration.

## 7. Decision

- Quality-owner decision: **pending**. Merging this proposal records the
  decision-ready option; it does not activate the reduced boundary.
- If approved, the E6 and E7 Issues must be written against the boundaries in
  Sections 2 and 3, and each deferred item must appear in the corresponding
  milestone evidence packet as an explicit non-goal with its reason.
