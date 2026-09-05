# E5 → E6 handoff: the read-only composer input

**Authority:** written by the E5 owner. This is the document
`E5_T01_TO_E6_COMPATIBILITY_PREFLIGHT.md` names as handoff trigger 4 — "the E5
owner documents the read-only composer input and invalidation behaviour needed
by the E6 consumer".

**It describes what E5 does, not what E5 intends.** Where a behaviour is
specified but unbuilt, this document says so and names the ticket that owns it.
A handoff document that describes intentions is how a consumer ends up building
against a guarantee that does not exist.

**Bound to:** `e5/t08-evidence-card` at the commit carrying tickets 03–08. Every
behavioural claim is either a named file and line, or a named test that
demonstrates it.

**Companion:** `CONSUMER-CONTRACT-FACTS.md` carries the sensitivity-tag ruling
and the evidence-field semantics. It is not repeated here.

---

## 1. What E6 reads

One composed read model, `RelationWorkspaceV1`, served by
`GET /api/v1/relations/assets/{asset_id}/discovery`. E6 reads nothing else. It
does not query the relation ledger tables, and it does not read candidate detail.

Composition is in `api/routes/relation.py`, the `workspace()` helper. Every call
re-reads from storage; nothing is cached between requests.

| Field | Source | Notes |
|---|---|---|
| `readiness` | `repository.read_active_readiness(asset_id)` | `None` when not ready. See §3 for exactly when it becomes `None`. |
| `discovery_outcome` | latest settled attempt, else `NOT_READY` | See §2. |
| `failure_class` | that attempt's `failure_class` | `None` unless the outcome is `TECHNICAL_FAILURE`. |
| `candidates` | the settled attempt's candidate, if any | At most one. Never carries historical detail: `detail_included` is `Literal[False]`. |
| `decisions` | the decision bound to that candidate | Empty until the user answers. |
| `confirmed_relations` | `repository.list_confirmed_relations(asset_id)` | Bound to the asset's current version since ticket 09. §4. |

## 2. Deriving the four M5 outcomes

E6's preflight expects one of `NO_MATCH`, `DECLINED`, `CONFIRMED_RELATION`,
`STALE`. E5 does not serve those four directly; it serves
`DiscoveryOutcome` plus the decision and relation records. The derivation:

| M5 outcome | Derive from |
|---|---|
| `CONFIRMED_RELATION` | a row in `confirmed_relations` whose `source_candidate_id` matches the candidate, **or** a decision with `user_action == "CONFIRM"`. Either alone is sufficient — the relation row is itself proof the write committed, and requiring both would render an answered candidate as still open when only one half was read. |
| `DECLINED` | a decision with `user_action == "DECLINE"` |
| `NO_MATCH` | `discovery_outcome == "NO_MATCH"` |
| `STALE` | `discovery_outcome == "STALE"` |

Two values E5 emits do **not** map onto the four, and E6 must handle them
separately rather than folding them in:

- **`NOT_READY` is overloaded.** It means "the card is locked" when `readiness`
  is `None`, and "ready, never searched" when `readiness` is present. Only the
  readiness record separates them. Collapsing them either hides the search action
  from a ready card or offers it on a locked one.
- **`TECHNICAL_FAILURE` is not `NO_MATCH`.** No-match is a semantic claim E5
  caches; a technical failure is an auditable event carrying no claim, and E5
  never serves one as a cached answer (`read_settled_result` returns only
  `CANDIDATE` and `NO_MATCH`). Presenting a failure as "nothing found" turns a
  five-minute outage into a conclusion the user acts on.
- **`RUNNING`** means a reservation is held. Not a terminal state.

## 3. Readiness binding, and why the card hash is not the asset content hash

`KnowledgeCardReadinessRecordV1` binds `(asset_id, version_id, m4_artifact_id,
knowledge_card_hash)` plus lifecycle and acceptance evidence.

### 3.1 The two hashes

E6's preflight requires the composer to obtain the asset content hash separately
and never substitute the card hash for it. **That is correct, and here is the
precise reason, which is not the one the preflight assumed.**

In the current implementation the two are *numerically equal at the moment of
acceptance*: `ReadinessService.accept` mints readiness against the version that
records the acceptance, and takes `knowledge_card_hash` from
`repository.get_version_content_hash(snapshot.version_id)`. So on the day a card
becomes ready, card hash == that version's content hash.

**The equality is an implementation consequence, not a contract guarantee, and it
stops holding the moment the asset moves.** `knowledge_card_hash` is pinned to
the accepted version forever. The asset's current content hash moves with every
subsequent edit. After any post-acceptance change they differ, and a consumer
that substituted one for the other would be comparing a live value against a
frozen one without knowing it.

So: treat them as two identities that happen to coincide once. Read the current
asset content hash from the asset; read the card hash from the readiness record.

### 3.2 When readiness stops answering

`read_active_readiness` binds to the asset's *current* version in the query
itself:

```sql
WHERE r.asset_id=? AND r.lifecycle='ACTIVE' AND a.current_version_id=r.version_id
```

So the moment the asset advances past the accepted version, readiness returns
`None` rather than a stale record. Fail-closed by construction, and demonstrated
by `test_readiness_stops_answering_once_the_asset_moves_past_it`.

It is not the only invalidation behaviour E5 implements — ticket 09 added the
rest. See §5.

## 4. Confirmed relations — the gap is closed; the compensating control is not needed

**This section previously told E6 to compensate for a permission that outlived
its card. Ticket 09 closed it; the instruction below replaces that guidance.**

`list_confirmed_relations` and `read_confirmed_relation` now join the asset and
require `assets.current_version_id = relation.current_version_id`, alongside
`lifecycle = 'CONFIRMED'` and the asset not being deleted. When the asset
advances a version, readiness and the relation list withdraw together, which is
the property that was missing — the two used to disagree about whether the card
was usable.

Fixed in the read rather than in a caller, because authorization re-projects
from the repository at every policy evaluation, and a binding checked anywhere
else is bypassed by the next caller that forgets it. **E6 therefore does not
need the readiness-plus-hash gate this section used to prescribe.** Adding it is
harmless but redundant.

`test_a_confirmed_relation_does_not_outlive_the_card_it_was_confirmed_against`
now asserts the closed behaviour. It was rewritten rather than deleted so the
record that the hole existed survives.

For audit reads, use `read_relation_record`, which returns the row whatever its
lifecycle. It is deliberately a different call from the one that authorizes
access: reconstructing what happened must never be possible with the call that
grants a read.

## 5. Invalidation — what exists and what does not

| Behaviour | Status |
|---|---|
| Readiness withdraws when the asset advances past the accepted version | **Implemented.** §3.2. |
| M4 map invalidates when M1/M2/M3 correction retires its evidence | **Implemented**, ticket 02. `invalidation_reason`, `invalidated_by_m3_artifact_id`, `affected_insight_ids`, `reusable_insight_ids` are populated. |
| Projection invalidation removes eligibility and the index row in one transaction | **Implemented**, ticket 04, `invalidate_projection`. |
| Readiness transitions to `STALE`/`INVALIDATED` with evidence | **Implemented**, ticket 09. Written by `invalidate_for_asset_change` with `invalidated_at` and `invalidation_reason`. |
| Confirmed relations transition to `STALE`/`INVALIDATED` | **Implemented**, ticket 09. §4. |
| `invalidate_for_asset_change` | **Implemented**, ticket 09. One transaction across readiness, projections, index rows, candidates and relations. |
| Mutation-by-artifact matrix | **Implemented**, ticket 09. `docs/e5/INVALIDATION-MATRIX.md`, sourced from `application/invalidation/matrix.py`. |

E6's preflight integration check 4 — "a relation or readiness invalidation turns
the M5 context stale and makes prior route, privacy, draft and approval state
ineligible for reuse" — **is now satisfiable against E5.** What E6 reads:

- `InvalidationService.apply(event, asset_id=..., reason=...)` performs the
  revocation; the matrix states, per event, what each of the eight artifacts
  moves to.
- Stale and invalidated are different answers. Stale means the basis of a
  comparison moved and the user must explicitly search again; invalidated means
  its subject is gone. E6 should not collapse them: one asks the user to redo a
  comparison, the other says there is nothing left to compare.
- A related asset changing does **not** invalidate the referring asset's
  readiness (GRAG-16). Its candidate and relation go stale, and its card stays
  accepted. Treating that as a readiness invalidation would make the user redo
  an acceptance on an asset nobody touched.
- Attempts and decisions survive every event. An M5 context that reports "no
  decision was made" because the relation was invalidated would misstate the
  user's own history.

## 6. Historical evidence is opened only by an exact-bound confirmation

Before a confirmation there is nothing to open: the candidate carries
`detail_included: Literal[False]`, and the bounded detail read resolves against
node identifiers a confirmed relation names. `NO_MATCH`, `DECLINED` and `STALE`
expose no historical reference of any kind.

After a confirmation, the opened set is bounded by the relation's own mapping and
boundary nodes — not by the historical asset. `resolve_bounded_detail` reads only
the named nodes of the named projection, and reports a missing or
provenance-less node rather than skipping it, because a card missing half its
provenance still looks authoritative.

The confirmation grants access to **one** asset, the one the user was shown. It
does not widen retrieval to the corpus: the user agreed that this experience is
worth comparing to that one, not to open their archive. Demonstrated by
`test_the_grant_is_scoped_to_the_one_asset_shown`.

**The evidence card cannot currently be returned over HTTP.**
`RelationWorkspaceV1` has no field it can occupy, so
`routes/relation.py` still raises the typed not-implemented for the evidence
read. The card is built, hashed and verified at the module seam. The contract
change is being made on `e5/t01-evidence-card-field`; until it merges, E6 should
treat the evidence card as a surface that exists in application code and not yet
on the wire.

## 7. Known gaps, collected

Stated together so none has to be inferred from its absence.

1. ~~**Ticket 09 is not started.**~~ **Closed 2026-08-05.** Readiness and
   relation lifecycle transitions, invalidation evidence, the
   mutation-by-artifact matrix and restart resume are implemented. §5.
2. ~~**Confirmed relations do not expire.**~~ **Closed 2026-08-05.** The
   version binding is enforced in the repository read; the compensating control
   this list previously prescribed is no longer needed. §4.
3. **The evidence card has no HTTP surface.** §6.
4. **`sensitivity_tags` has no producer.** E6's canonical privacy detection has
   no real data source. `CONSUMER-CONTRACT-FACTS.md` §1.2.
5. **`EvidenceStrength.DIRECT` and `ConfirmationState.REJECTED` are unreachable.**
   `CONSUMER-CONTRACT-FACTS.md` §2.
6. ~~**The retrieval trace exists as a contract but the product path does not
   emit into it.**~~ **Closed 2026-08-05.** Acceptance, denied and completed
   searches, confirmations and bounded detail reads now emit into
   `retrieval_phase_events`, validated in tests by the real
   `qa/scripts/check_retrieval_phase.py` rather than by restating its rules.
   An earlier version of this list claimed no trace existed at all, which was
   wrong: the schema, the checker and emitted E2/M1 artifacts were already in
   the tree. What was missing was a producer on the product path.
7. **E5 has never run against the real model.** Every E5 test uses the
   deterministic fake. Ticket 05's real-model probe is not run. No W7900, ROCm or
   performance claim attaches to anything here.

## 8. Handoff trigger status

Against `E5_T01_TO_E6_COMPATIBILITY_PREFLIGHT.md`:

| # | Condition | Status |
|---|---|---|
| 1 | one reviewed controlling head | **Open.** PR #35 is the head; PR #40 (tickets 03–08) and PR #42 stack on it and are unreviewed. |
| 2 | tickets 02 and 03 provide the real M4 artifact and readiness transition | **Substantially met, one criterion short.** Both are implemented; ticket 03's criterion 9 (retrieval trace) is unmet per gap 6. |
| 3 | E5 completed its own integration and merged in E5→E6→E7 order | **Open.** Nothing has merged. |
| 4 | the E5 owner documents composer input and invalidation behaviour | **This document.** |
