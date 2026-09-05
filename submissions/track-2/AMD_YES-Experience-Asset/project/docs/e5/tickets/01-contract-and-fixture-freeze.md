# 01 — Contract and fixture freeze

**What to build:** Every contract E5 depends on becomes inspectable and frozen in one
reviewed change, before any behavior exists. A reviewer can read the checked-in
schemas, the migration, and three sanitized fixtures and know exactly what readiness,
relations, and discovery outcomes mean without running the product.

**Why one horizontal change here, rather than freezing each contract inside the
vertical slice that needs it:** the backend models, JSON Schema, OpenAPI, frontend
types, examples, fixtures, and trace schemas are generated from one source and
consumed by each other. Freezing them piecemeal means every later slice regenerates
the same artifacts, and two slices that regenerate from different intermediate states
produce a diff nobody can review as one decision. Worse, E6 and E7 are now developing
in parallel against these exact symbols — a second contract change mid-flight
invalidates their mocks after they have already built against the first. Paying for
one reviewed freeze up front is what buys the other three lanes a stable surface.

This is the expand step of expand–contract: new forms are added beside existing ones,
so nothing breaks at this commit.

**Blocked by:** None. E4 merged through PR #22 with its exact-head W7900 gate, and
`CURRENT_ITERATION.md` at `main@59a20f8` records Issue #24 as ready for E5
implementation.

**Owns:** frozen contracts, generated artifacts, migration numbering and DDL, shared
entry points. Tickets 02–11 consume these and do not redefine them; a later slice that
finds a contract gap returns here for an explicit contract-change review rather than
patching the schema locally.

**Not in this ticket:** any product behaviour. No M4 generation, no readiness
transition, no projection, no discovery, no decision, no evidence card. Migration
number is `0008` (baseline is `0007_m3_policy_decisions.sql`,
`MIGRATION_VERSION = 7`).

Starting to implement behaviour here fails in a specific way: the contract is still
under review, so any behaviour built against it may have to be rewritten when the
review changes a field — and because behaviour and contract arrive in one diff, the
reviewer can no longer evaluate the contract as a single decision. E6 and E7 are
building against these same symbols, so the review has to be readable on its own.
Put the effort into making the frozen shapes complete enough that tickets 02–11 never
need to come back here.

**Verify with:** `python3 scripts/export_contracts.py --check`,
`bash qa/gates/pr_gate.sh --mode contract`,
`python3 -m unittest discover -s qa/tests -v`, `python3 -m pytest -q`, `ruff check .`.

**Status:** ready-for-agent

## Standing decisions this ticket implements

Three symbol-level conflicts between Issue #24 and the PR #28 parallel-execution
contract are already resolved; see `../OWNERSHIP-AND-DECISIONS.md` for the full
reasoning. In short:

1. All four relation-bearing snapshot fields retire into sidecar records —
   `relation_candidates`, `relation_candidate_decisions`, `related_assets`, and
   `knowledge_card_readiness`. Keeping relation state inside the snapshot would force a
   new asset content version on every confirmation, which changes the content hash —
   and GRAG-14 requires that hash to be unchanged across a relation read. Readiness
   retires for a separate reason: created by an explicit action after a version exists,
   it would need a new version to store, leaving "the version that records readiness"
   permanently one step ahead of "the version judged ready", or self-referential if it
   points at itself.
   The **types** `RelationCandidate` and `RelationCandidateDecision` survive but are
   **materially extended** — the current shape cannot express a fixed relation type
   (`proposed_relation` is free text), bilateral node mapping, boundary nodes,
   projection bindings, discovery fingerprint, validation contract version, or
   lifecycle, and its flat `provenance_refs` cannot say which side a reference belongs
   to. This is a breaking change to a symbol the PR #28 handoff manifest freezes for
   E6, so it must be communicated to E6 before it lands.
2. `AgentRunStateV1` keeps its six relation fields, but as a read-only permission
   snapshot re-projected from the ledger at each policy evaluation. Treating run state
   as authoritative lets a long-running run keep authorizing detail reads for a
   relation that was invalidated after the run started — the exact stale access
   GRAG-16 exists to catch.
3. `query` is removed from the two cross-asset tool contracts and kept on
   current-source search, for two different reasons. On the discovery side a
   user- or model-supplied query makes the same pair of assets yield different
   relations under different phrasings, so the relation degrades into what one sentence
   returned once; a Runtime-owned discovery-intent version removes that variance,
   though reproducibility itself comes from the fingerprint and idempotent cache, not
   from the intent. On the confirmed-detail side the query is removed and **not**
   replaced by an intent: the readable set is computed from the exact confirmed
   relation, asset, version/hash bindings and the validated mapping and boundary
   package, so any remaining tunable would mean one confirmation could read different
   things. Current-source search is a genuine query operation and keeps its query.
   E6 consumes relation outcomes, not the discovery tool, so this change does not
   reach its handoff surface.

## Acceptance criteria

- [ ] The editable M4 Insight and Boundary Map contract is frozen, covering lessons,
      supporting evidence, counterfactuals, limitations, counterexamples, and
      applicability/transfer conditions, with an explicit representation for visible
      gaps.
- [ ] Explicit acceptance — confirmation, or explicit acceptance of visible gaps — is
      the only declared source of a version- and hash-bound `KnowledgeCardReady`.
      Any weaker trigger would let readiness attach to a card the user never agreed
      was finished, and every downstream relation inherits that binding.
- [ ] Role projections are declared as deterministic read-only mappings over accepted
      canonical M2/M3/M4 records. A second model-driven extraction pass would create a
      set of facts with no canonical owner, so invalidating them later would have no
      mechanical trigger and stale relations could outlive corrected evidence.
- [ ] A new migration, numbered from the current baseline of 7, adds the sidecar
      relation ledger: projections, nodes, edges, provenance, FTS5 summary rows,
      discovery attempts, validated candidates, decisions, and confirmed relations.
- [ ] The same migration retires all four relation-bearing snapshot fields per standing
      decision 1, each ruled individually rather than as a group: `relation_candidates`,
      `relation_candidate_decisions`, `related_assets` (whose free-text `relation` also
      maps onto the six fixed types), and `knowledge_card_readiness` (into a readiness
      sidecar keyed by asset, version, and card hash). API workspaces may compose
      read-only views; those views are never serialized back into the snapshot.
- [ ] `RelationCandidate` and `RelationCandidateDecision` are extended to carry the
      fixed relation type, bilateral node mapping, boundary nodes, current and
      historical projection bindings, discovery fingerprint, validation contract
      version, lifecycle state, and side-attributed provenance. The extension is
      recorded as a breaking change to a frozen E6 handoff symbol and communicated to
      E6 before it lands. Asserting the shape is unchanged fails on integration day:
      E6 writes mocks and assertions against the old shape, and the mismatch surfaces
      only when both lanes are already near `INTEGRATION_READY`.
- [ ] The relation-ID versus candidate-ID conflict is resolved. The Runtime currently
      requires `confirmed_relation_ids` to be a subset of `relation_candidate_ids`,
      while a confirmed relation now carries its own identifier plus a source candidate
      reference — under which that subset check fails for every valid confirmation.
      Freeze the migration or compatibility rule; checking each confirmed relation's
      source candidate against the run's candidate set preserves the original intent
      that nothing can be confirmed which was never proposed.
- [ ] The attempt record, discovery fingerprint field set, and relation-ledger
      interfaces are frozen here, so tickets 05 and 06 each implement part of one
      agreed shape rather than one defining the other's contract.

### Additional deliverables required because Wave 1 runs in parallel

Tickets 02, 04, 06 and 08 are built concurrently on separate branches after this
ticket lands. Two things they would otherwise each invent must be produced here.

- [ ] **All E5 endpoint paths are decided and their routers registered here** — M4,
      readiness, and the four relation operations — with each route module created and
      its unimplemented handlers returning a typed not-implemented result that the
      owning ticket later replaces. `api/main.py` has one router registration point;
      four branches each adding a line there conflict, and the conflict lands on a
      151 KB regenerated OpenAPI document where a hand-resolved merge easily drops a
      field. Registering once here means each parallel branch only fills in handlers
      inside its own route module.
- [ ] The typed not-implemented result is recorded as non-shippable, and ticket 10's
      public QA verifies none remains at the evidence head. Left in place, it reads to
      a reviewer as "the feature exists and is broken" rather than "the feature is not
      written yet".
- [ ] **Worked instance fixtures are produced for every intermediate artifact**, not
      only the three scenario fixtures: one accepted M4 map, one readiness record, one
      projection pair (current and historical, with nodes, edges and provenance), one
      attempt record with its discovery input, one validated candidate, and one
      confirmed relation. Without them a parallel ticket has no concrete input and its
      Agent fabricates one — for example ticket 08 would invent its own bilateral
      provenance shape, which is the very thing it exists to render correctly, and the
      divergence would surface only when the real producer lands.
- [ ] Exactly six relation types are frozen — `SAME_THEME`, `METHOD_REUSE`,
      `COUNTEREXAMPLE`, `SUPPLEMENT`, `PREREQUISITE`, `FOLLOW_UP` — each with its
      versioned role-pair admissibility rule. A closed vocabulary is what lets a
      relation label mean the same thing in a session six weeks later; a model-invented
      synonym would read as a distinct relation to the user while carrying no defined
      admissibility rule.
- [ ] Exactly six discovery outcomes are frozen: `NOT_READY`, `RUNNING`, `CANDIDATE`,
      `NO_MATCH`, `TECHNICAL_FAILURE`, `STALE`. Collapsing failure into no-match would
      make a temporary outage indistinguishable from a proven absence of relation, and
      the cache would then preserve the outage permanently.
- [ ] The discovery request's required free-text query is replaced by a Runtime-owned
      discovery-intent version, per standing decision 3. A bounded `top_k` remains for
      compatibility, documented as a ceiling rather than a quota, because a quota would
      pressure the service into padding a single defensible candidate with weaker ones.
- [ ] Backend contracts, checked-in JSON Schema, OpenAPI, frontend types, public
      examples, relation fixtures, and retrieval-phase trace schemas are regenerated
      and synchronized in this one change.
- [ ] Existing mock relation vocabulary is migrated — `SIMILAR_SITUATION` to
      `SAME_THEME`, `SHARED_METHOD` to `METHOD_REUSE` — or replaced by equivalent
      fixtures, so the UI carries one vocabulary. Two live vocabularies would let a
      fixture-only label reach a user-visible surface with no admissibility rule
      behind it.
- [ ] Three sanitized fixtures exist: cross-topic positive (A relates to B, C
      unrelated), hard-negative corpus (no defensible relation), and invalid
      false-association proposal.
- [ ] The GRAG-01 through GRAG-18 external behavior matrix is recorded and mapped to
      the fixtures.
- [ ] Migration, invalidation, privacy, rollback, and append-only evidence boundaries
      are recorded.
- [ ] Contract synchronization tests pass, and migration tests cover a fresh database
      plus an upgrade from the preceding schema without losing existing accepted
      M1/M2/M3 data.
- [ ] The three standing decisions are recorded on Issue #24 so E6 and E7 can read
      what changed under them without reconstructing it from a diff.
