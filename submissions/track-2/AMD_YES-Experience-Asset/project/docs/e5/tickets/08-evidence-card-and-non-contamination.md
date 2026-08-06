# 08 — Confirmation-bound deterministic evidence card and non-contamination

**What to build:** After confirming, the user sees the comparison they were deciding
about: a bilateral evidence card built from canonical statements, evidence, and source
identifiers on both sides. It is assembled by application code. Reading history never
becomes writing history — the current Experience Asset's snapshot and hashes come out
byte-identical.

**Why no second model call:** the user reviewed and confirmed a specific relation — a
relation type, a role mapping, a boundary. A generated summary of that relation is a new
artifact they did not review, produced after the gate that was supposed to be their last
checkpoint. It would drift from the thing they agreed to, and the drift would be
invisible because the summary reads as a description of it.

**Why the card carries evidence and not advice:** a recommendation compresses the
comparison into someone else's conclusion, and the user then owns a decision they cannot
inspect. Presenting both sides' canonical content leaves the inference where it belongs
— with the person who lived both experiences and can weigh the boundary against their
actual situation.

**Why the unchanged-hash invariant is tested externally rather than asserted in code:**
the failure it guards against is subtle. Nothing crashes if a relation read appends a
content version; the asset simply acquires history it did not earn, and its hash stops
matching the readiness binding that other relations depend on. Comparing persisted
snapshot JSON and both hashes before and after is what makes the failure visible at all.

**Blocked by:** 01 — Contract and fixture freeze. (Under the sequential plan this
followed 07; in Wave 1 it builds against 01's confirmed-relation fixture — see
completion note below.)

**Wave 1, parallel.** Branch from the E5 integration branch after 01 lands.

- **Consumes:** 01's frozen confirmed-relation, projection, node, edge and provenance
  schemas, plus 01's projection-pair fixture and confirmed-relation fixture. The pair is
  what makes bilateral provenance concrete; inventing it here would mean designing the
  exact thing this ticket exists to render correctly.
- **Produces:** deterministic evidence-card rendering and the bounded detail read, plus
  the unchanged-hash invariant. Nothing downstream consumes it inside E5.
- **May write:** the evidence and detail-read modules, the evidence-read handler inside
  the relation route module, and the evidence-card view. Tickets 05 and 07 fill their own
  handlers in that same route module in later waves, so keep changes inside the
  evidence-read handler rather than restructuring the module.
- **External verification is partial in Wave 1.** The rendering, the bounded read set,
  and the before/after hash invariant can all be verified now against 01's fixture and a
  real asset with statements. GRAG-13 and GRAG-14 through the real confirm-then-read flow
  need ticket 07 and move to Wave 3. Reporting them as passing now would mean the flow
  was never exercised — only its last step was.
- **Fixture debt:** built in Wave 1, `INTEGRATION_READY` once 07 lands and the card is
  rendered from a genuinely confirmed relation.

**Owns:** evidence-card rendering and bounded detail reads. It does not write canonical
snapshots and does not create decisions or relations; ticket 07 owns those.

**Not in this ticket:** no second model call, no generated summary, advice, or
next-step; no writing to the canonical snapshot; no creating decisions or relations
(ticket 07). Two canonical statement lists side by side look raw, and summarising them
is the obvious polish — it fails because the summary is a new artifact produced *after*
the confirmation gate, so the user never reviewed it, and it will read as a faithful
description of the relation they did approve while being free to drift from it.

The thing that makes the card useful without a summary is deterministic structure:
each mapped role labelled with its canonical content, the transfer boundary quoted from
its source, and provenance identifiers on both sides. Spend the effort on making that
legible, because the value here is a surface the user can form their own judgement on —
which is precisely what a generated conclusion would take away.

**Verify with:** the shared command set, plus GRAG-13 and GRAG-14 at the HTTP seam,
including a before/after comparison of persisted `content_json`, statement hash, card
hash, and version count.

**Status:** ready-for-agent

## Escalation — the HTTP seam has no field for the card

Raised by ticket 08 during Wave 1, per the integration contract §四 rule that a
branch which needs to write a file it does not own records the need instead of
changing it in place.

`POST /api/v1/relations/assets/{asset_id}/relations/{relation_id}/evidence` is
frozen in `contracts/openapi.json` with `RelationWorkspaceV1` as its 200 body,
and `RelationWorkspaceV1` carries readiness, discovery outcome, failure class,
candidates, decisions and confirmed relations — **there is no field the rendered
evidence card can occupy**. The card can be built, hashed and verified, but it
cannot be returned over the declared contract.

Ticket 08 does not resolve this: the response model lives in
`domain/relation.py` and the generated contract in `contracts/`, both of which
§四 marks frozen with ticket 01 as the owner. Changing either here would be an
ownerless shape change while 04, 05 and 07 write assertions against the current
shape, and the conflict would surface only at integration.

**What 01 has to decide:** either `RelationWorkspaceV1` gains an optional
`evidence_card` field carrying the rendered card or its typed refusal, or the
evidence operation gets its own response model. The first keeps one composed
read shape for the whole relation surface; the second keeps the card's refusal
vocabulary out of a model that four other operations also return.

Until that lands, ticket 08's rendering, bounded read, determinism and refusal
behaviour are verified at the module seam, and the HTTP handler continues to
raise the typed not-implemented result rather than returning a shape the
contract does not declare. Reporting GRAG-13 as passing at the HTTP seam before
this resolves would claim a surface that does not exist.

## Escalation — WITHDRAWN 2026-08-05

This escalation claimed *"there is no retrieval trace in the backend"* and asked
ticket 01 to specify and freeze one. **The claim was wrong and the escalation is
withdrawn before ticket 01 acts on it.**

What I checked was `grep -rn RetrievalPhaseTrace app/`, which returns nothing,
and I concluded from an absent class name that the artifact was absent. It is
not. The retrieval-phase trace is an established evidence contract with four
parts already in the tree:

| Part | Location |
|---|---|
| Contract schema | `qa/schema/retrieval_phase_trace.schema.json` |
| Invariant checker | `qa/scripts/check_retrieval_phase.py` |
| Producer | `scripts/capture_e2_m1_local_evidence.py` |
| Emitted artifacts | `evidence/milestones/e2-m1-langgraph-local/*/artifacts/retrieval-phase-trace.json` |
| Frontend consumer | `web/contracts/json-schema/retrieval-phase-trace-v1.schema.json`, read by `deriveRelationDiscovery` |

It exists as `{"schema_version": "retrieval-phase-trace/v1", "asset_id", "events"}`
dictionaries rather than a typed class, which is why the class-name grep missed
it. Reasoning from a missing symbol to a missing capability is the same error
this ticket made once before, in the other direction.

**The real gap is smaller and belongs to E5, not to ticket 01.** The contract,
the checker and the vocabulary are frozen; the seven event types already cover
what tickets 03, 04 and 08 need. What is missing is that **no E5 operation emits
an event.** Readiness transition, projection activation, discovery and the
bounded detail read all run without writing one, so the only traces that exist
were built by an evidence-capture script for E2/M1.

No contract change, no domain type and no schema decision is required. The work
is to make the product path emit into a shape that is already agreed, and it is
tracked in E5's own tickets rather than escalated.

One genuine extension is needed and is not a contract change: criterion 9 of
ticket 03 requires the denial reason for pre-readiness attempts to be recorded,
and the frozen vocabulary has no way to say "this attempt was refused". Emitting
a plain `relation_candidate_search` would be read by the checker as a cross-asset
read that ran before readiness, which is a CRITICAL finding and the opposite of
what happened. The event schema sets `additionalProperties: true`, so the fields
fit without a schema change; the checker gains one rule.

## Acceptance criteria

- [ ] Detailed retrieval reads only the confirmed historical asset, and only the
      statements, evidence, sources, and spans reachable from the validated mapping and
      boundary package. An unrestricted read of the confirmed asset would turn one
      approved comparison into a general search over that history, which is more than
      the user approved.
- [ ] The evidence card contains the relation type, canonical labels for each mapped
      role, canonical transfer or non-applicability boundary content, current and
      historical evidence, and bilateral provenance identifiers. (GRAG-13)
- [ ] The card is rendered deterministically by application code with no second model
      call, and contains no generated advice, recommendation, or new fact.
- [ ] Persisted current snapshot JSON, current statement hash, and Knowledge Card hash
      are identical before and after relation and detail reads, asserted as an external
      test invariant. (GRAG-14)
- [ ] No current Experience Asset content version is appended by a relation or detail
      read.
- [ ] Missing sources or spans, revoked permission, a stale relation, partial
      provenance, and deleted or privacy-restricted content each produce a typed result
      rather than a partially rendered card. A card missing half its provenance still
      looks authoritative, and the user has no way to see what was dropped.
- [ ] The UI renders the evidence comparison including the unchanged current-card
      binding, and the pre-confirmation candidate view exposes no historical detail —
      showing it there would make the confirmation decision moot, since the user would
      already have read what they were deciding whether to read.
- [x] The retrieval trace records the bounded detail access, its provenance references,
      and the unchanged current-statement hash invariant. `read_evidence_card_traced`
      emits it; a refused card emits nothing, because logging a read the gate refused
      would put a `cross_asset_detail` event on the record for an access that never
      happened.
