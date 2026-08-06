# 04 — Role-graph projection and FTS5 summary index

**What to build:** Once a Knowledge Card is ready, the system derives a compact,
deterministic, read-only role graph from the accepted canonical records and makes it
eligible for comparison. Rebuilding the same inputs produces the same graph and the
same hash. Alongside it, summary text becomes lexically searchable in the existing
SQLite database with reproducible Chinese and English normalization.

**Why the graph is projected rather than extracted:** asking a model to read the raw
text and produce entities would create a second set of facts with no canonical owner.
When the user later corrects a statement, there would be no mechanical way to find
which extracted nodes depended on it — invalidation would have to be guessed, and
guessed invalidation means stale relations survive corrected evidence. Projecting from
already-accepted records keeps one source of truth, so invalidation is a lookup rather
than an inference.

**Why edges mean membership and never causality:** the available signals are statement
order, temporal proximity, and semantic similarity. None of them distinguishes cause
from coincidence. An edge labelled as causation would present the system's guess with
the same visual authority as the user's own confirmed account, and the user has no way
to tell which is which. Membership edges claim only what the canonical record already
states.

**Why an explicit no-match beats zero-score rows:** a result list padded with
zero-score entries looks like a completed search that found something. The user then
spends attention on rows that carry no evidence, and a downstream caller cannot
distinguish them from real hits without re-deriving the scores. Saying "nothing
matched" costs one state and preserves the meaning of a non-empty result.

**Scope note:** this ticket also corrects the existing current-source retrieval path to
the same no-match policy. It is deliberate rather than scope creep — both paths share
the retrieval repository, and leaving one on zero-score filler would mean two lexical
policies in one system and a second edit to the same code later.

**Blocked by:** 01 — Contract and fixture freeze. (Under the sequential plan this
followed 03; in Wave 1 it builds against 01's fixtures instead and reconciles with 03
later — see completion note below.)

**Wave 1, parallel.** Branch from the E5 integration branch after 01 lands.

- **Consumes:** 01's frozen projection, node, edge, provenance and FTS schemas, plus
  01's accepted-M4-map fixture and readiness-record fixture. Those fixtures stand in for
  tickets 02 and 03, which are not finished yet.
- **Produces:** deterministic projection construction, activation and rebuild; the FTS5
  summary index with its recorded normalization constants; explicit lexical no-match on
  both lexical paths. Ticket 05 consumes the active projections.
- **May write:** the projection and retrieval modules. No route module — this ticket
  adds no endpoint.
- **External verification is partial in Wave 1.** Projection and index state are meant
  to be observable through readiness status, which ticket 03 owns and has not built. In
  this wave, verify at the repository seam plus determinism tests: rebuild reproduces
  the same hash, activation is transactional, Chinese and English normalization are
  reproducible, invalidation removes the index row in the same transaction. The HTTP-level
  observability check moves to Wave 2. Claiming HTTP verification now would mean testing
  against 01's fixture rather than a real ready card, which proves the fixture, not the
  feature.
- **Fixture debt:** this ticket is *built* in Wave 1 but not `INTEGRATION_READY` until
  02 and 03 land and its tests run against a real accepted map and a real readiness
  record. The debt is owned here, not by 02 or 03 — this ticket knows which assumptions
  it made about the fixture, and they do not.

**Owns:** projection and index creation, activation, and rebuild. Ticket 09 submits
invalidation events into the same transaction but does not create or rebuild
projections.

**Not in this ticket:** no embeddings, vector search, reranker, external graph database,
or any second data store; no discovery call (ticket 05); no invalidation orchestration
(09). "Retrieval" makes a vector index the obvious reach, and it fails this way: a
second store holds a copy of canonical state that must be invalidated in the same
transaction as SQLite, and any partial failure leaves the two disagreeing — a relation
already revoked in one view and still clickable in the other. That class of
inconsistency is very hard to construct in a test and usually surfaces as a user
report.

Spend the effort on the deterministic parts instead, because they are what makes
invalidation mechanical: stable node and edge identifiers, a projection hash that
recomputes, recorded normalization constants, and transactional activation. If recall
later proves insufficient *with measurements*, the deterministic role and lexical
prefilter is the thing a vector approach would have to beat.

**Verify with:** the shared command set, plus fresh-database and upgrade migration
tests, Chinese and English lexical tests, explicit no-match, and stale-removal tests.

**Status:** ready-for-agent

## Acceptance criteria

- [ ] A projection is generated only from a readiness-bound card and only from accepted
      canonical records.
- [ ] Node and edge identifiers are deterministic, so rebuilding unchanged input
      reproduces the same content and the same projection hash. Without that, a rebuild
      would produce a graph that differs only in identifiers, every fingerprint bound to
      it would change, and cached discovery results would be discarded for no semantic
      reason.
- [ ] Every projection, node, edge, and provenance entry is bound to asset, canonical
      version, card hash, projection schema version, and projection hash.
- [ ] Projection creation and activation are transactional: a projection becomes
      eligible only after all nodes, edges, provenance, and index rows are complete and
      the recomputed hash matches the stored hash. A partially built projection that is
      already eligible would be compared against and produce a candidate missing the
      provenance needed to explain it.
- [ ] Summary-safe material is indexed for BM25 retrieval in the existing SQLite
      database. Introducing a second store would add an independent copy of canonical
      state that has to be invalidated in lockstep, and the two would diverge under any
      partial failure.
- [ ] Search text is normalized deterministically — Latin case-folded and
      word-tokenized, CJK given application-generated character n-grams — with the
      n-gram size, case-folding, and Unicode normalization recorded. Depending on an
      optional SQLite tokenizer would make lexical behavior differ between the developer
      machine and the evaluation environment, and the difference would surface as
      unexplained recall changes.
- [ ] Only active ready-card summary material and role labels are indexed. Indexing raw
      chat or unconfirmed proposals would let material the user never confirmed become
      cross-asset memory and reach the model on a later discovery.
- [ ] A lexical query with no positive match returns an explicit no-match, on both the
      summary path and the corrected current-source path.
- [ ] Invalidating a projection removes it from the active summary index and the
      eligibility set in the same transaction. Split across transactions, a crash
      between them leaves an index row that still grants eligibility for canonical state
      that no longer exists.
- [x] Projection and index state are observable through the retrieval trace or readiness
      status, so this ticket is verifiable at an external seam. The projection id and
      hash ride the `knowledge_card_ready` event, because acceptance is the single
      moment readiness is minted and the projection activates.
- [ ] Deterministic tie-breaking is defined for equal BM25 scores, so repeated searches
      over unchanged data return the same order.
