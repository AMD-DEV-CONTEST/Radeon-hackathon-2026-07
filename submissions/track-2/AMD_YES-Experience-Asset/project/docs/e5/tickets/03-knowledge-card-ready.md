# 03 — Explicit acceptance to KnowledgeCardReady

**What to build:** The user's explicit acceptance — confirming the map, or explicitly
accepting its visible gaps — turns the Insight and Boundary Map into a ready Knowledge
Card bound to that exact asset version and card hash. Until then, "find related
experiences" is locked and the reason is legible. Accepting the card does not start a
search.

**Why readiness is bound to an exact version and hash rather than to the asset:** a
relation discovered against one version of a card is an argument about that specific
content. If readiness pointed at the asset, a later edit would silently inherit every
relation built on the old text, and the user would see a confirmed relation whose
stated reason no longer matches what the card says. Binding to version and hash makes
that inheritance impossible to express, so staleness surfaces as a state instead of as
a quiet inconsistency.

**Why acceptance does not auto-run discovery:** it costs local model time and puts
historical summaries in front of someone who has not asked to compare anything. The
separate click is what makes the comparison a deliberate allocation of the user's
attention rather than a side effect of finishing their own work.

**Blocked by:** 02 — M4 Insight and Boundary Map.

**Owns:** the readiness state transition — the only ticket that writes it. Ticket 02
submits the M4 artifact; ticket 09 revokes post-readiness derivatives.

**Not in this ticket:** the discovery action itself. This ticket proves discovery is
*denied* before readiness and *not started* by acceptance; ticket 05 builds what
happens when it is allowed. Building the trigger here fails in a way that costs the
evidence: if acceptance and discovery land together, no test can show that acceptance
alone creates no run, and GRAG-02 becomes unprovable. Spend the effort instead on the
denial path — the typed reasons, and proving no cross-asset read or model call happens
before the denial returns.

**Verify with:** the shared command set, plus GRAG-01 and GRAG-02 at the HTTP seam.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] Explicit acceptance is the only path to `KnowledgeCardReady`. An inferred
      transition — for instance treating "no unresolved questions" as acceptance —
      would produce readiness the user never granted, and every downstream permission
      derives from it.
- [ ] Readiness is bound to the exact asset version identifier and Knowledge Card hash.
- [ ] Explicitly accepting visible gaps produces readiness under the same binding
      rules as full confirmation, so a user who knows their experience is incomplete
      can still proceed without being forced to fabricate the missing parts.
- [ ] Starting discovery before exact readiness is denied with a stable, safe reason
      code, and performs no cross-asset read and no model call. Doing the read and
      discarding it would already have exposed historical material to the model and
      spent the budget, so the denial has to happen before the work, not after.
      (GRAG-01)
- [ ] Accepting a ready card creates no discovery run. (GRAG-02)
- [ ] Denial distinguishes at minimum not-ready, stale version, hash mismatch, already
      accepted, and storage conflict. A single generic reason leaves the user unable to
      tell "finish your card" apart from "your card changed underneath you", which
      have opposite next actions.
- [ ] Repeat acceptance of the same version is idempotent; acceptance of a stale
      version is refused rather than silently rebinding to the current one.
- [ ] The UI shows the discovery action as locked with its reason before readiness and
      available after, deriving both from backend contracts. A locally computed lock
      would disagree with the backend the moment the card changes in another tab, and
      the user would see an action that fails when clicked.
- [x] The retrieval trace records the readiness transition, its bindings, and the
      denial reason for pre-readiness attempts. Emitted by `ReadinessService.accept`
      and by the route gate; verified against `qa/scripts/check_retrieval_phase.py`
      in `test_e5_retrieval_trace.py`.
- [ ] Restart preserves readiness and its exact bindings.
