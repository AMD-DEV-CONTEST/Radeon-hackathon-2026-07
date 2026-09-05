# 02 — M4 Insight and Boundary Map, editable end to end

**What to build:** A user who has a confirmed Decision and Evidence Ledger can produce
an Insight and Boundary Map, read it, correct it, and see where it is incomplete. Each
lesson shows the evidence it rests on, and the user can open that evidence.
Counterfactuals, limitations, counterexamples, and transfer conditions are first-class
parts of the map. Correcting the underlying ledger invalidates the map and makes the
stale state visible.

**Why the boundary fields are not a later enhancement:** a lesson drawn from one
person's experience, presented without its limitation and its transfer condition,
reads as general advice. The user then applies it in a situation the original
experience never covered, and the asset has actively misled them — a worse outcome
than having no lesson. The boundary fields are what convert a personal account into
something safe to reuse, so they ship with the lesson or the lesson is not shippable.

**Why this ticket stays whole despite being the largest:** splitting it backend/UI
would produce two halves, neither demonstrating the feature; splitting it by field
group would force a second contract regeneration, which is exactly the cost ticket 01
was paid to avoid, and would invalidate E6/E7 mocks mid-flight.

**Blocked by:** 01 — Contract and fixture freeze.

**Wave 1, parallel.** Branch from the E5 integration branch after 01 lands; merge back
when done. Tickets 04, 06 and 08 run concurrently on their own branches.

- **Consumes:** 01's frozen contracts and registered M4 route module; the real existing
  M3 implementation. This ticket needs no fixture substitute for anything, because
  everything upstream of it already exists.
- **Produces:** the editable M4 map, its editing and versioning, and its invalidation
  on upstream M1–M3 correction. Ticket 03 consumes the accepted map; ticket 04 currently
  builds against 01's M4 fixture and switches to this ticket's real output once both
  land.
- **May write:** `application/m4/`, `workflow/m4_*`, the handlers inside the M4 route
  module, `web/src/features/m4/`. Everything in the shared-entry list stays read-only —
  see `../INTEGRATION-CONTRACT.md` §4.
- **Completion:** this is the only Wave 1 ticket that can reach `INTEGRATION_READY`
  within the wave, because it carries no fixture debt.

**Owns:** M4 artifact schema, editing, versioning, and M4 invalidation caused by
upstream M1–M3 correction. Ticket 03 reads the artifact to decide acceptability;
ticket 09 owns only post-readiness invalidation.

**Not in this ticket:** anything cross-asset. No readiness transition (ticket 03), no
projection (04), no discovery (05), no relation state of any kind. The Issue title
mentions gated RAG, which makes it tempting to prepare for it here — but M4 runs before
readiness exists, so any cross-asset read added at this stage would let a historical
asset anchor an experience the user is still clarifying, and that anchoring is
invisible afterwards: the resulting lesson reads as self-derived. The whole value of
this ticket is a lesson the user can trust as their own.

**Model wiring:** follow the M3 pattern already in the repository — the real inference
adapter on the product path, a deterministic fake in tests. Do not invent a new model
integration shape.

**UI placement:** the M4 workspace joins the existing workspace shell alongside M1–M3.
Building a standalone page instead would give the user two places where their asset
lives, and the two would drift on version and invalidation state.

**Verify with:** the shared command set, plus M4 HTTP behavior tests and the affected
frontend contract/view-model tests.

**Status:** ready-for-agent

**Model-input risk to design around:** the M4 payload is strictly larger than M3's,
and E4's first blocker was the production model returning HTTP 422 / timing out on an
oversized pre-injected payload. Injecting the full canonical record set and hoping it
fits fails in a particular way: the request either errors or silently truncates, and a
truncated context produces a proposal that references records the model never saw,
which then fails Runtime validation for reasons that look like model quality rather
than payload size. Bounding the canonical context deliberately, and recording the
bound, keeps that failure legible.

## Acceptance criteria

- [ ] A user with a confirmed or gap-accepted ledger can generate an Insight and
      Boundary Map through the product path, backed by real SQLite and the real
      Runtime policy.
- [ ] The map contains lessons, supporting evidence, counterfactuals, limitations,
      counterexamples, and applicability/transfer conditions as declared in the frozen
      contract.
- [ ] Every map item exposes its canonical statement, evidence, and source provenance,
      and the user can open that evidence from the map. Without the drill-down the user
      can only accept or reject a lesson on its plausibility, which is precisely the
      judgment the evidence exists to replace.
- [ ] Editing the map produces a new canonical version rather than mutating an accepted
      one, so an accepted version stays a fixed thing that a readiness binding and any
      relation built on it can continue to refer to.
- [ ] Visible gaps are represented explicitly and render distinguishably from confirmed
      content. A gap that renders like a finished lesson is worse than a missing
      lesson, because the user has no signal to go looking for what is absent.
- [ ] Model output is validated against allowed canonical record and statement
      identities before persistence. A structurally invalid proposal is repaired within
      the bounded budget or fails with a terminal state; it is never partially accepted,
      because a half-applied proposal leaves the artifact in a state no contract
      describes.
- [ ] The canonical context sent to the model is explicitly bounded, and the bound is
      recorded alongside the model-call budget, timeout, and repair count.
- [ ] Correcting M1, M2, or M3 invalidates the map and surfaces the invalidated state.
      Continuing to display the old map would present conclusions drawn from evidence
      the user has since corrected.
- [ ] The UI renders not-started, in-progress, needs-input, review-ready, confirmed,
      complete-with-gaps, invalidated, and failed states from backend-owned contracts.
- [ ] Retrieval during M4 stays within current sources and prior versions of the same
      asset. Letting a historical asset in at this stage would anchor an experience the
      user is still clarifying, and the anchoring is invisible afterwards — the
      resulting lesson looks self-derived.
- [ ] Tests assert externally visible behavior at the public HTTP seam, with focused
      unit coverage only where an algorithm's edge cases cannot be reached through HTTP.
