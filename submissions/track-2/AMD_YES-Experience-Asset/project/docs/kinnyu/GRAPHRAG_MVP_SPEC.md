# GraphRAG MVP Specification — Explainable Cross-Asset Experience Discovery

This document is a draft for collaborator review. It specifies the E5/M4
GraphRAG slice but does not claim that M3, M4, `KnowledgeCardReady`, GraphRAG,
or AC-30 is implemented. It follows the approved Experience Asset vocabulary
and the repository's existing Agent, Runtime, local-inference, canonical-state,
and retrieval-phase boundaries.

## Problem Statement

After turning one experience into a trustworthy Knowledge Card, a user may
have older Experience Assets that are useful to compare with it. Those assets
can cover unrelated topics while still sharing a reusable method, supplying a
counterexample, exposing a prerequisite, or continuing an earlier line of
work. Plain text retrieval alone can miss those cross-topic structural
relations.

Showing a weak or erroneous relation is more harmful than missing a plausible
one. A false relation spends the user's attention, makes an explainable asset
feel less trustworthy, and can pull later reasoning away from the current
experience. Returning more candidates does not repair that harm. The user
therefore needs conservative discovery that can abstain, explains every shown
relation from both assets, and does not expose detailed historical content or
change current facts before the user confirms the relation.

The repository already defines the two required retrieval gates and their
Runtime permissions, but it does not yet implement production M3/M4 artifacts,
the readiness transition, an FTS5 index, a graph projection, cross-asset
candidate discovery, or confirmed-relation detail retrieval. Existing
candidate and UI shapes are contract or fixture scaffolding and do not yet
provide the complete bilateral mapping and transfer boundary required by this
MVP.

## Solution

Once the current Knowledge Card is explicitly accepted and bound to an exact
version and hash, the user can choose “find related experiences.” The system
then compares a compact role graph for the current card with compact role
graphs for eligible historical cards. For the initial MVP, the fixture corpus
contains the current asset and two historical assets, and one local-model call
compares both historical graphs in a single batch.

The local model may propose at most one structural mapping using only supplied
node identifiers and one of six fixed relation types. The Runtime validates
the proposal against the stored projections, readiness bindings, role rules,
provenance, and an explicit transfer or non-applicability boundary. The Runtime
then either exposes one source-grounded candidate, records a truthful semantic
no-match, or reports a retryable technical failure. It never pads the result
to satisfy `top_k`.

If the user confirms the candidate, the Runtime authorizes detailed reads only
from that bound historical asset. The product renders a deterministic evidence
comparison card directly from canonical statements, evidence, and source
identifiers. It does not make a second model call, generate advice, invent a
new claim, or rewrite the current Experience Asset. Declining a candidate or
receiving no match is a successful outcome and does not block M5.

## User Stories

1. As an Experience Asset user, I want M1–M4 retrieval limited to my current sources and versions of the same asset, so that an older experience cannot anchor the experience I am still clarifying.
2. As an Experience Asset user, I want cross-asset discovery locked until I explicitly accept the current Knowledge Card, so that historical material is introduced only after my current experience is coherent.
3. As an Experience Asset user, I want readiness bound to the exact Knowledge Card version and hash, so that a later edit cannot reuse stale relation results.
4. As an Experience Asset user, I want to start relation discovery explicitly, so that accepting a Knowledge Card does not spend model time or expose historical summaries without my intent.
5. As an Experience Asset user, I want one click to search using the whole ready Knowledge Card, so that I do not need to invent a comparison query that changes the meaning of the durable relation.
6. As an Experience Asset user, I want structurally related experiences to be discoverable even when their topics differ, so that reusable methods and boundaries are not limited to shared keywords.
7. As an Experience Asset user, I want at most one candidate in the MVP, so that my attention is spent on the strongest defensible comparison rather than a ranked list of weak possibilities.
8. As an Experience Asset user, I want no candidate shown when the evidence package is incomplete, so that presentation pressure cannot turn an uncertain association into an apparent fact.
9. As an Experience Asset user, I want a visible no-match result, so that abstention feels like a completed search rather than a broken feature.
10. As an Experience Asset user, I want semantic no-match separated from model or storage failure, so that I know whether no relation exists or the search should be retried.
11. As an Experience Asset user, I want every candidate to use a stable relation label, so that relation meaning remains understandable across sessions and assets.
12. As an Experience Asset user, I want to see which roles or structures correspond on both sides, so that I can inspect why the system considers the experiences related.
13. As an Experience Asset user, I want the candidate explanation assembled from canonical role content, so that model-written prose cannot introduce an unsupported reason.
14. As an Experience Asset user, I want every candidate to show a transfer or non-applicability boundary, so that similarity is not mistaken for universal applicability.
15. As an Experience Asset user, I want provenance from both assets, so that I can trace the candidate back to specific statements and evidence rather than trusting an opaque score.
16. As an Experience Asset user, I want detailed historical evidence hidden during candidate discovery, so that I can judge the relationship before consuming the old story in depth.
17. As an Experience Asset user, I want to confirm or decline the exact candidate and related asset, so that only my explicit decision can grant detailed access.
18. As an Experience Asset user, I want a declined candidate to remain declined for its bound discovery result, so that it does not repeatedly demand attention in the same state.
19. As an Experience Asset user, I want pre-confirmation detail requests denied, so that a model, stale UI, or malformed request cannot bypass my choice.
20. As an Experience Asset user, I want confirmation to unlock only the selected historical asset, so that one approval cannot broaden retrieval to unrelated assets.
21. As an Experience Asset user, I want confirmed detail rendered as a bilateral evidence comparison card, so that the useful output remains inspectable and source-grounded.
22. As an Experience Asset user, I want the evidence card built without another model summary, so that the final comparison cannot drift from the relation I reviewed.
23. As an Experience Asset user, I want historical detail retrieval to leave the current Knowledge Card hash unchanged, so that comparison cannot silently become authorship.
24. As an Experience Asset user, I want advice and new conclusions excluded from the evidence card, so that the card remains evidence for my judgment rather than an unreviewed recommendation.
25. As an Experience Asset user, I want correcting either asset to invalidate affected projections, candidates, confirmations, and detail access, so that stale relations cannot survive changed evidence.
26. As an Experience Asset user, I want the same unchanged discovery input to return the same validated candidate or no-match, so that repeated clicks do not produce arbitrary alternatives.
27. As an Experience Asset user, I want a changed current card, historical corpus, model, prompt, or inference configuration to permit a new search, so that meaningful input changes are not hidden behind an old cache entry.
28. As an Experience Asset user, I want technical failures excluded from semantic no-match caching, so that a temporary outage does not permanently erase a possible relation.
29. As a privacy-conscious user, I want graph construction to read only confirmed canonical records, so that raw conversation and unconfirmed model output do not become cross-asset memory.
30. As a privacy-conscious user, I want all core discovery inference to use the approved local vLLM path, so that private Experience Assets are not sent to a closed remote model API.
31. As a privacy-conscious user, I want candidate discovery to send summary-role data rather than detailed evidence to the local model, so that the prompt contains only what the discovery decision requires.
32. As a returning user, I want projections, discovery outcomes, decisions, and confirmations restored from SQLite, so that process or pod restarts do not lose the relation workflow.
33. As a user continuing to M5, I want no-match or decline to leave route evaluation available, so that a historical comparison is helpful but never mandatory.
34. As a collaborator, I want the role graph to express membership rather than inferred causality, so that later implementation does not turn ordering or similarity into a false cause-and-effect claim.
35. As a collaborator, I want model output treated as an untrusted mapping proposal, so that the Runtime remains the only authority for scope, permission, validation, and durable state.
36. As a collaborator, I want graph nodes and edges bound to canonical versions, hashes, statements, and evidence, so that every graph element can be invalidated and audited deterministically.
37. As a collaborator, I want one SQLite storage boundary for canonical state, FTS5, graph projections, and relation records, so that the MVP does not introduce an independent graph database or distributed consistency problem.
38. As a collaborator, I want the initial fixture limited to three assets, so that the team can close the functional and safety contract before claiming 50- or 100-asset capacity.
39. As a collaborator, I want future corpus growth to add deterministic prefiltering before model comparison, so that prompt size does not grow linearly with every stored asset.
40. As a quality reviewer, I want public positive, hard-negative, gate-denial, invalid-proposal, and non-contamination evidence, so that AC-30 can be judged from behavior rather than architecture claims.
41. As a Track 2 reviewer, I want a trace that distinguishes local retrieval, model proposal, Runtime validation, user confirmation, and bounded detail access, so that RAG, tool invocation, memory, and permission control are visible as one real workflow.
42. As a maintainer, I want old mock relation labels migrated to the fixed vocabulary, so that fixture-only terminology cannot diverge from production contracts.
43. As a maintainer, I want current-source text retrieval to return a real no-match instead of zero-score filler, so that both lexical RAG and GraphRAG follow the same precision-first policy.
44. As a maintainer, I want observable failures to contain safe reason codes and hashes rather than private prompts or responses, so that debugging does not create a second sensitive-data store.

## Implementation Decisions

### 1. Product boundary and quality posture

- The MVP goal is to find a historical experience worth comparing without
  contaminating the current experience, and to expose detailed comparative
  evidence only after the user confirms the relation.
- Precision, provenance, and explanation take priority over recall. A weak
  false relation costs user attention and can redirect later reasoning, while a
  missed relation leaves the current asset intact. The system therefore treats
  abstention as a successful semantic outcome and never fills a result list
  merely because an interface exposes `top_k`.
- Requirements state the replacement behavior and its value rather than only
  banning an unsafe behavior. For example, historical details stay unavailable
  before confirmation because summary-only candidates preserve an unanchored
  current card and let the user allocate attention deliberately.
- The feature is a project-specific role-graph retrieval design. It does not
  adopt graph-community summaries, a general knowledge graph, or an external
  product named GraphRAG.

### 2. Existing state and delivery dependency

- M1 and M2 production code slices are present in the repository. This is a
  code-availability statement, not a milestone-promotion claim; promotion
  status remains governed by the current iteration and milestone evidence.
  M3, M4, the production `KnowledgeCardReady` transition, and the E5 GraphRAG
  slice do not yet exist. E5 integration remains dependent on accepted M3 and
  M4 canonical contracts; this specification does not authorize
  out-of-sequence integration.
- Existing retrieval can search only current-source statements and uses a
  simple scan that may return zero-score entries. It is scaffolding, not the
  final lexical-quality baseline.
- Cross-asset tool names, readiness fields, relation bindings, Runtime checks,
  retrieval trace contracts, and a relation UI view already exist. They are
  prior art to extend rather than parallel abstractions to replace.
- Existing candidate shapes do not fully represent bilateral role mapping,
  a transfer boundary, validated projection bindings, or discovery
  fingerprinting. Existing fixture relation names also differ from the fixed
  vocabulary and must be migrated when production contracts change.

### 3. Deterministic retrieval phases

The Runtime owns a fixed phase route:

| Phase | Permitted retrieval | Reason |
|---|---|---|
| M1–M4 before readiness | Current sources and prior versions of the same Experience Asset | Keeps historical assets from anchoring the experience while it is being elicited and corrected. |
| Ready Knowledge Card, after explicit discovery action | Summary-only role graphs from eligible local historical assets | Gives the user a bounded way to discover structure without exposing detailed history. |
| User-confirmed relation | Detailed canonical statements and evidence from only the confirmed historical asset | Converts the user's decision into an exact access binding rather than a broad permission. |

- The local model cannot switch retrieval phases by inferring that a task is
  “simple” or “difficult.” Difficulty-based routing would require a separate
  Agentic RAG policy and could silently broaden scope, so it is deferred.
- `KnowledgeCardReady` does not run discovery automatically. The explicit user
  action authorizes one summary-only discovery for the bound card; it does not
  confirm a relation or grant detailed access.
- Discovery accepts no free-text comparison query. The whole ready Knowledge
  Card and a versioned fixed discovery intent form the current-side input, so
  the resulting relation can remain a durable asset relation rather than a
  transient query answer.
- The discovery contract replaces its current required free-text `query` with a
  Runtime-owned `discovery_intent_version`. Neither the user nor the model can
  populate or override that intent. The contract regeneration that makes this
  change must update every backend, frontend, OpenAPI, and fixture consumer
  together.

### 4. Module responsibilities and interfaces

| Module | Responsibility | Interface decision |
|---|---|---|
| M4 application service | Confirm the Insight and Boundary Map and create readiness | Emits one exact asset-version and card-hash binding after explicit acceptance. |
| Lexical index repository | Index and retrieve approved current-source and summary text | Applies asset/version/scope filters before BM25 ranking and returns an explicit no-match when no positive match exists. |
| Role-graph projector | Build a read-only graph projection | Accepts only confirmed canonical records and emits deterministic nodes, edges, role signatures, provenance, and a projection hash. |
| Cross-asset discovery service | Orchestrate eligibility, fingerprinting, one batch model call, validation, and persistence | Returns a discriminated candidate, semantic no-match, technical failure, or stale result; never an unvalidated proposal. |
| Local inference adapter | Request one strict structured relation proposal | Receives only Runtime-supplied compact role graphs and has no tools or side effects. |
| Runtime policy and validator | Enforce phase, permission, identity, version/hash, relation, provenance, and detail gates | Remains authoritative even when model output is schema-valid. |
| Relation ledger | Persist candidates, decisions, confirmed relations, and invalidation | Keeps relation state version-bound without changing the current Experience Asset content hash. |
| Relation API | Expose discovery, status, decision, and confirmed evidence operations | Requires expected bindings on every state-changing request and returns safe typed outcomes. |
| Relation UI | Render the explicit action and all discovery states | Consumes backend-owned contracts and never reconstructs permission or relation truth from presentation state. |
| Retrieval trace | Preserve judge-visible phase and permission evidence | Records identifiers, hashes, decisions, reason codes, and timings without private prompt or response bodies. |

The Cross-Asset Discovery Service is the primary deep module. Its HTTP-facing
interface is the highest test seam: graph storage, FTS5, local-model transport,
validation, caching, and persistence remain implementation details behind one
externally observable workflow.

### 5. SQLite lexical retrieval

- The existing SQLite database remains the canonical storage boundary. FTS5
  provides BM25 lexical retrieval; no separate vector store, Supabase, TiDB,
  PGlite, or graph database is introduced.
- Current-source indexing stores approved source chunks and confirmed
  canonical statements with asset, version, source, span, status, and privacy
  scope metadata. Scope filters are applied before results are returned.
- Summary indexing stores only active ready-card summary material and role
  labels. It does not index raw chat, unconfirmed proposals, or detailed
  historical source spans because those inputs do not improve summary
  discovery enough to justify broader exposure.
- Search text is normalized deterministically. Latin text is case-normalized
  and tokenized by words; CJK text receives application-generated character
  n-gram tokens before FTS5 indexing. This avoids depending on optional SQLite
  tokenizers and gives Chinese and English fixtures a reproducible lexical
  path.
- A lexical query with no positive match returns no hits. Returning zero-score
  rows would look complete while supplying no evidence, so explicit no-match
  is the safer and more useful result.
- The three-asset MVP sends both eligible historical summary-role graphs to one
  batch comparison. FTS5 is still established as the repository's lexical
  foundation, but it does not exclude either historical fixture from the
  initial comparison.

### 6. Canonical role-graph projection

- A projection is generated only after M4 is confirmed or the user explicitly
  accepts visible gaps and `KnowledgeCardReady` is bound to that exact version
  and hash.
- Projection is deterministic and read-only. It maps existing confirmed
  canonical fields into roles; it does not ask a model to extract another set
  of facts from raw text. This preserves one source of truth and makes graph
  invalidation mechanical.
- Every projection, node, edge, and provenance entry is bound to the asset,
  canonical version, Knowledge Card hash, projection schema version, and
  projection hash.
- Node identifiers are deterministic within the projection and derive from
  canonical record and role identities. Edge identifiers derive from their
  projection, endpoints, and fixed role relation. Rebuilding unchanged input
  therefore produces the same graph content and hash.
- The graph is a role graph, not a causal graph. Its edges mean “this canonical
  record has this member in this role.” Statement order, temporal proximity,
  and semantic similarity do not create a cause-and-effect edge because those
  signals cannot prove causality.

The allowed projection structures are:

| Root record | Allowed member edges |
|---|---|
| `CriticalMoment` | `HAS_CUE`, `HAS_CHANGE`, `HAS_SURPRISE`, `HAS_CONFLICT` |
| `DecisionRecord` | `HAS_ALTERNATIVE`, `HAS_REASON`, `HAS_ACTION`, `HAS_RESULT`, `HAS_EVIDENCE` |
| `InsightRecord` | `HAS_SUPPORT`, `HAS_COUNTERFACTUAL`, `HAS_LIMITATION`, `HAS_COUNTEREXAMPLE`, `HAS_APPLICABILITY` |

- There is no inferred `CriticalMoment → Decision → Insight` edge. If later
  product work requires an explicit cross-record link, that link needs its own
  user-visible canonical statement and a separately reviewed contract.
- Compact discovery payloads contain root identifiers, fixed roles, bounded
  summary-safe labels already present in the canonical card, role signatures,
  and opaque node identifiers. Exact evidence text and source spans are not
  included. Provenance remains stored for Runtime expansion after validation.
- Bounded graph reads use keyed SQLite lookups, bounded recursive CTEs, or
  in-process traversal over the supplied projection only. The MVP needs no
  general graph query engine, unrestricted traversal, or graph-library-owned
  state.

### 7. Persistence model

SQLite migrations add versioned projection, discovery, and relation tables
alongside the existing immutable asset snapshots and run records.

| Record | Required identity and content |
|---|---|
| Role-graph projection | Projection ID, asset ID, asset version ID, Knowledge Card hash, projection schema version, projection hash, lifecycle state, creation time, and invalidation metadata. |
| Role-graph node | Projection ID, deterministic node ID, root/member kind, canonical record ID, role, display order, bounded summary-safe text, and text hash. |
| Role-graph edge | Projection ID, deterministic edge ID, fixed `HAS_*` type, root node ID, member node ID, and canonical record binding. |
| Node provenance | Node ID plus canonical statement, evidence, source, and available span identifiers. At least one statement reference is required for every candidate-visible node. |
| FTS5 summary row | Active projection ID, asset title, summary-safe text, normalized lexical tokens, and role-signature text. |
| Discovery attempt | Run ID, discovery fingerprint, current projection ID, eligible-set hash, model/prompt/config hashes, attempt number, outcome, safe failure class, timing, and optional candidate ID. |
| Validated candidate | Candidate ID, discovery fingerprint, current and historical projection IDs, fixed relation type, mapped node pairs, boundary node IDs, validation contract version, and lifecycle state. |
| Candidate decision | Candidate ID, exact current and historical bindings, `CONFIRM` or `DECLINE`, decision time, and user-action provenance. |
| Confirmed asset relation | Relation ID, source candidate ID, bilateral asset/version/projection bindings, relation type, confirmation time, and active or stale state. |

- Canonical Experience Asset content and the relation ledger are separate
  durable aggregates in the same database. This makes relation confirmation
  durable without appending historical claims to the current asset or changing
  its content hash.
- The E5 contract migration retires embedded candidate, decision, and related
  asset fields from persisted Experience Asset snapshots. Persisted snapshot
  JSON never carries discovery, candidate, decision, or confirmation state.
  API workspace responses may compose equivalent read-only relation views from
  the relation ledger for compatibility, but those views are not serialized
  back into the snapshot. The ledger is therefore the only authority and a
  relation read cannot change the snapshot JSON or its content hash.
- Projection creation and activation are transactional. A projection becomes
  eligible only after all nodes, edges, provenance, and FTS rows are complete
  and its recomputed hash matches the stored hash.
- Discovery and relation records are append-only except for explicit lifecycle
  transitions to stale or invalidated. Historical decisions remain auditable;
  invalidation removes access rather than erasing the event.

### 8. Three-asset, one-batch-call discovery

- The minimum functional corpus contains three sanitized ready assets: A is
  current, B covers a different topic but has one defensible structural
  relation to A, and C is a hard negative with no defensible relation.
- One local-model request receives A, B, and C as separate compact graphs. It
  must compare B and C in that request and return either one proposed mapping
  to the strongest defensible historical asset or semantic no-match.
- “One call” means one batch comparison per attempt, not one call per
  historical asset. A controlled retry for timeout, transport failure, or
  malformed structured output is a technical retry and remains bounded by the
  Runtime retry budget.
- The model cannot request more assets, tools, source spans, or graph expansion.
  It receives a closed set selected by the Runtime, so its finite attention is
  directed toward comparing allowed structure rather than deciding its own
  scope.
- The service returns zero or one candidate. The existing `top_k` argument may
  retain its bounded interface default of 3 for compatibility, but it is a
  ceiling rather than a quota and the MVP output cap is one. No contract or
  acceptance criterion requires three displayed candidates.

### 9. Structured model proposal

The local-model output is a strict discriminated proposal with two outcomes:

| Outcome | Required proposal data |
|---|---|
| Semantic no-match | Outcome only; no relation, asset, mapping, boundary, or generated explanation is allowed. |
| Candidate proposal | Historical projection ID, one fixed relation type, one or more bilateral node-mapping pairs, at least one current-side boundary node ID, and optional historical-side boundary node IDs. |

- Each mapping pair contains only a supplied current node ID and supplied
  historical node ID. The model does not return new facts, graph nodes, graph
  edges, provenance, confidence scores, titles, summaries, or permissions.
- The required current-side boundary node must resolve through
  `HAS_LIMITATION`, `HAS_APPLICABILITY`, or `HAS_COUNTEREXAMPLE`. Optional
  historical boundary nodes use the same roles. A card accepted with gaps but
  without a source-grounded current boundary cannot yield a candidate; it must
  abstain. Requiring this boundary directs model attention toward safe transfer
  rather than similarity alone.
- Human-readable title and summary come from the historical Knowledge Card.
  The Runtime renders the relation reason, bilateral role mapping, transfer
  boundary, and provenance from validated canonical nodes. This design gives
  the model the narrow task it is useful for while preventing its prose from
  becoming an unsupported durable claim.
- Complex confidence scoring is not part of the contract. A score can look
  precise without proving the association; a complete validated evidence
  package is the MVP admission rule.

### 10. Fixed relation vocabulary and admissibility

Exactly six candidate relation types are allowed:

| Relation type | Admissible meaning and projected role shape |
|---|---|
| `SAME_THEME` | Two source-grounded root records explicitly contain the same non-generic subject phrase in their canonical labels. Runtime requires normalized lexical overlap and a root-to-root mapping; generic words alone are insufficient. |
| `METHOD_REUSE` | `HAS_ACTION` or `HAS_REASON` on one side maps to `HAS_ACTION` or `HAS_APPLICABILITY` on the other. |
| `COUNTEREXAMPLE` | `HAS_RESULT`, `HAS_LIMITATION`, or `HAS_COUNTEREXAMPLE` on one side maps to `HAS_SUPPORT`, `HAS_ACTION`, or `HAS_APPLICABILITY` on the other. |
| `SUPPLEMENT` | `HAS_EVIDENCE`, `HAS_SUPPORT`, or `HAS_ALTERNATIVE` on one side maps to `HAS_SUPPORT`, `HAS_LIMITATION`, or `HAS_APPLICABILITY` on the other. |
| `PREREQUISITE` | `HAS_APPLICABILITY` on one side maps to `HAS_ACTION` or `HAS_RESULT` on the other; no top-level constraint or hidden dependency is inferred. |
| `FOLLOW_UP` | `HAS_RESULT` or `HAS_ACTION` on one side maps to `HAS_ACTION` or `HAS_APPLICABILITY` on the other, and the mapped canonical label explicitly marks the later action rather than relying on chronology alone. |

- The Runtime owns a versioned role-pair admissibility table for these
  relations. At least one mapping pair must satisfy the selected relation's
  role rule, and every mapped node must remain source-grounded.
- The vocabulary is closed. If no label and role rule fit, no-match preserves
  meaning better than a model-created synonym.
- These labels describe durable asset relations. They do not add causal edges
  to either role graph.

### 11. Runtime validation algorithm

The Runtime validates in this order and exposes no partial candidate:

1. Verify the explicit discovery permission, current asset identity, exact
   ready version/hash, and `CROSS_ASSET_SUMMARY` scope.
2. Load the active current projection and verify its stored and recomputed
   hashes match the ready card.
3. Resolve eligible historical projections: current, ready, active,
   non-deleted, locally permitted, and different from the current asset.
4. Compute the discovery fingerprint and return an existing validated semantic
   result when the same fingerprint already completed.
5. Reserve a bounded discovery attempt before local inference so concurrent
   identical requests cannot create divergent successful results.
6. Validate the local response against the strict discriminated schema and
   reject tool calls or extra fields.
7. For no-match, verify that candidate fields are absent, then persist the
   semantic outcome for the fingerprint.
8. For a candidate, verify that the historical projection was supplied, the
   fixed relation type is valid, the proposal contains at least one mapping,
   at least one allowed current-side boundary, and no second candidate.
9. Verify every mapped and boundary node exists on its declared side, every
   referenced role edge exists, and the relation satisfies its role-pair and
   lexical admissibility rules.
10. Expand provenance deterministically and require canonical statement and
    evidence/source references from both assets.
11. Build the readable relation package from canonical labels and reject it if
    relation type, bilateral mapping, transfer boundary, or bilateral
    provenance is absent.
12. Recheck all version, hash, projection, and eligibility bindings in the same
    write transaction, then persist and expose the candidate.

- A schema error, nonexistent node, forbidden relation, missing boundary,
  one-sided provenance, stale binding, or failed admissibility rule is a
  validation or technical failure, not semantic no-match. The UI receives a
  safe retryable state and no candidate.
- Nuanced semantic correctness cannot be proven by identifier validation
  alone. Conservative instructions, relation-specific role rules, a
  source-grounded boundary, deterministic rendering, hard-negative fixtures,
  and local-model quality evidence work together to reduce false relations.
  If those checks do not support a candidate, abstention receives the model and
  Runtime attention instead of a fallback association.

### 12. Discovery fingerprint, caching, and idempotency

- The discovery fingerprint hashes a canonical serialization of the current
  Knowledge Card version/hash and projection hash; the sorted eligible
  historical asset, version, and projection hashes; model identity and frozen
  model revision; prompt version; role and validation contract versions;
  inference parameters; and deterministic prefilter configuration version.
- Same fingerprint means same discovery input. It returns the same validated
  candidate or semantic no-match without another model call.
- A changed current card, newly eligible or changed historical asset, changed
  projection, or formally versioned model/prompt/configuration creates a new
  fingerprint and permits a new search.
- Timeout, model unavailability, malformed output, storage conflict, and
  Runtime validation failure are retained as attempts for audit but are never
  reusable semantic no-match entries. A later explicit retry can therefore
  recover from a technical failure.
- Concurrent requests for one fingerprint share a reserved run. One caller may
  observe `RUNNING`; they cannot produce competing canonical candidates.

### 13. API and tool contract behavior

- The relation API exposes four user-level operations: start discovery for an
  exact ready card, read discovery status/result, decide an exact candidate,
  and read the confirmed relation's evidence comparison.
- Start discovery carries current asset ID, expected version, expected
  Knowledge Card hash, the Runtime-owned discovery-intent version, and the
  fixed summary scope. It carries no free-text query; the old required query is
  removed in the same contract regeneration. A compatibility `top_k` remains
  bounded but cannot raise the MVP output cap above one.
- Discovery responses are discriminated as `NOT_READY`, `RUNNING`,
  `CANDIDATE`, `NO_MATCH`, `TECHNICAL_FAILURE`, or `STALE`. A candidate response
  contains the validated fixed relation, bilateral mapping, boundary,
  bilateral provenance, and `detail_included=false`.
- Candidate decision carries candidate ID, related asset ID, expected current
  card version/hash, and `CONFIRM` or `DECLINE`. The Runtime rejects mismatched,
  stale, repeated-conflicting, or unknown bindings.
- Confirmed evidence read carries the exact relation and related-asset binding.
  Runtime authorization checks the persisted confirmation rather than trusting
  a client boolean or model proposal.
- The existing cross-asset tool contracts remain useful Runtime audit
  boundaries, but explicit user actions initiate discovery and detail reads.
  The relation-mapping model is not allowed to invent a tool call or turn
  readiness into permission.
- Checked-in JSON Schema, OpenAPI, backend domain contracts, frontend types,
  examples, and retrieval-phase trace schemas change together. Contract export
  remains the source for generated schemas.

### 14. User-visible states

| State | Required presentation and action |
|---|---|
| Not ready | Discovery action is locked with the reason that the current card has not been explicitly accepted. |
| Ready | “Find related experiences” is available; no search runs automatically. |
| Running | One bounded local discovery is in progress; duplicate clicks attach to the same fingerprinted run. |
| Candidate | Show exactly one relation type, bilateral role mapping, transfer boundary, and provenance summary with confirm and decline actions. |
| Semantic no-match | Show a completed no-match message and allow M5 to continue. Do not imply a technical error. |
| Technical failure | Show a safe failure category and an explicit retry action. Do not display or cache it as no-match. |
| Declined | Preserve the explicit decline for the bound candidate and keep detail locked. |
| Confirmed | Mark the exact relation as confirmed and make its bounded evidence comparison available. |
| Invalidated or stale | Hide candidate/detail actions, explain that an asset changed, and require a new ready projection and discovery. |
| Evidence comparison | Render deterministic current and historical evidence, relation, mapping, boundary, statement IDs, evidence/source IDs, and unchanged current-card binding. |

- The UI never creates a candidate, confirmation, no-match, or permission state
  from local component state. It derives presentation from backend contracts
  and the retrieval trace, as the current relation view already does for gate
  fixtures.
- The candidate view does not expose detailed historical source spans. This
  preserves the value of the confirmation choice instead of presenting the
  decision after the user has already consumed the details.

### 15. Confirmation-bound deterministic evidence card

- Confirmation creates a durable bilateral relation bound to the candidate,
  both asset versions, both projection hashes, and the current Knowledge Card
  hash.
- Detailed retrieval reads only the confirmed historical asset and only the
  statement, evidence, source, and span identifiers reachable from the
  validated mapping and boundary package. It cannot turn one relation into a
  general historical search.
- The evidence card is rendered by application code, not a second LLM call. It
  contains the relation type, canonical labels for each mapped role, canonical
  transfer/non-applicability boundary content, current and historical evidence,
  and bilateral provenance identifiers.
- The evidence card contains no generated advice, next-step recommendation, or
  new fact. Its benefit is a stable evidence surface on which the user can form
  a judgment; generative interpretation would reintroduce drift after the
  confirmation gate.
- The service hashes current statements and the Knowledge Card before and after
  detailed retrieval. Equality is an externally tested invariant, and no
  Experience Asset content version is appended by the read.

### 16. Correction, versioning, and invalidation

- Any correction or reopening that changes the current asset creates a new
  canonical version and invalidates its readiness, active projection,
  fingerprinted discovery result, pending candidate, confirmed relation access,
  and evidence card. The historical records remain auditable but stale.
- A changed related asset invalidates projections and relations bound to its old
  version. The current asset remains unchanged, but its affected candidate or
  confirmed detail becomes stale until a new discovery is explicitly run.
- A projection schema change creates a new projection version. Old projections
  remain readable for audit but cannot be mixed with new projection contracts
  in one discovery call.
- Invalidation removes stale projections from the active FTS5 summary index and
  eligibility set in the same transaction. This prevents an index row from
  granting access after canonical state has changed.
- Delete and privacy-scope changes invalidate eligibility and confirmed detail
  access immediately. Durable audit metadata follows the repository's deletion
  and evidence-retention policy without retaining deleted private content in a
  second graph store.

### 17. Failure behavior and recovery

| Failure family | Semantic meaning | Recovery |
|---|---|---|
| No admissible relation | Valid semantic no-match | Cache for the fingerprint; user may continue to M5. |
| Local model unavailable or timed out | Technical failure | Preserve durable state and allow a bounded explicit retry. |
| Malformed structured proposal or tool call | Invalid model output | Expose no candidate; record safe failure and retry only within policy. |
| Runtime validation rejection | Unsafe or incomplete proposal | Expose no candidate and do not convert to no-match; retain reason codes for diagnosis. |
| Stale asset, card, or projection | Binding conflict | Invalidate the run and require new readiness/projection as appropriate. |
| SQLite write conflict | Concurrent state change | Reload current bindings; never overwrite a newer decision. |
| Process restart during discovery | Incomplete durable attempt | Recover or safely mark retryable according to the reserved run state; never assume success. |

- All failure paths preserve the last durable canonical asset version.
- Retry budgets, timeouts, and terminal outcomes remain Runtime-owned. The
  model cannot hide a failure by returning a plausible fallback relation.

### 18. Privacy and security boundaries

- Core relation inference runs through the approved loopback-only local vLLM
  service on the Radeon Cloud environment. No closed remote model API receives
  Experience Asset content.
- Raw conversation, imported instructions, unconfirmed statements, and source
  details are treated as untrusted data. Projection reads only canonical
  confirmed fields, and the model request exposes no tools.
- Asset eligibility enforces local ownership/privacy scope, current lifecycle,
  readiness, and deletion state before any summary enters the model request.
- Prompt and response bodies are not persisted in logs, traces, evidence
  packets, or relation records. The system retains structured validated output
  where needed plus hashes, model identity, token counts, timings, and safe
  reason codes.
- Private source text, credentials, model weights, and raw sensitive traces stay
  out of Git. Public QA uses sanitized deterministic fixtures only.

### 19. Observability and evidence

- The retrieval trace remains the public behavioral proof of phase ordering. It
  records readiness, explicit discovery, summary scope, candidate or no-match,
  user decision, bounded detail, provenance references, invalidation, and the
  unchanged current-statement hash invariant.
- Discovery observability adds safe fingerprint, projection, prompt/config,
  validation-contract, outcome, retry, timing, and model metadata. It records
  no private text and no hidden QA material.
- The eventual E5 evidence packet must include the three sanitized fixtures,
  exact code commit, schema and migration versions, commands, public test
  results, retrieval traces, failures, rollback notes, and local-inference
  identity. The Spec-only PR creates no fake runtime evidence and makes no
  W7900 performance claim.
- Track 2 relevance is direct: the workflow makes local RAG, structured model
  proposal, deterministic Runtime permission, durable SQLite memory, user
  confirmation, and non-contamination visible in one product path.

### 20. Capacity evolution

- The first closure target is three assets and one batch call. There is no
  50-asset or 100-asset capacity promise in this MVP.
- Before expanding the corpus, the service adds deterministic prefiltering. It
  first filters active ready projections by permission and lifecycle, then by
  relation-compatible role signatures, and uses FTS5/BM25 summary relevance as
  a bounded ordering signal. Role filtering prevents cross-topic candidates
  from depending entirely on shared words.
- The fingerprint still includes the sorted eligible corpus state and the
  prefilter contract version, so adding or changing an eligible asset can
  trigger a new result.
- The model prompt must remain bounded; implementation may not keep adding all
  assets to one call. A generated 50-asset capacity smoke is optional future
  evidence after functional closure, not an MVP acceptance gate.
- Embeddings, vector search, graph databases, and community summaries may be
  evaluated only if measured retrieval failures remain after the deterministic
  role and lexical prefilter. Adding them now would increase storage,
  invalidation, and explanation complexity before the minimum task is proven.

### 21. Rollout and reversibility

- Delivery follows the approved sequence: M3 canonical contracts, M4 Insight
  and Boundary Map plus readiness, role projection and storage, discovery and
  validation, confirmation-bound detail, UI states, then E5 public evidence.
- Schema and API changes are introduced through normal versioned migrations and
  checked-in contract regeneration. The migration separates persisted
  Experience Asset snapshots from API-composed relation views and establishes
  the relation ledger as the only candidate/decision/confirmation authority.
  Existing mock relation data maps `SIMILAR_SITUATION` to `SAME_THEME` and
  `SHARED_METHOD` to `METHOD_REUSE`, or is replaced by equivalent fixtures in
  the same contract change so the UI never carries two vocabularies.
- The feature remains unavailable unless active projections and the relation
  service are healthy. M1–M4 current-source retrieval and M5 progression after
  no-match/decline remain independent.
- Rollback disables relation discovery, removes active projection eligibility,
  and reverts the application and contract changes. Immutable Experience Asset
  snapshots remain valid because graph and relation state are sidecar records,
  not historical-content rewrites.

## Testing Decisions

### Testing posture and primary seam

- Good tests assert externally visible behavior: allowed scope, typed outcome,
  candidate package, confirmation gate, evidence provenance, idempotency,
  invalidation, and unchanged current content. They do not assert SQL query
  order, private helper calls, prompt phrasing, or internal traversal steps.
- The primary seam is the public relation HTTP workflow backed by a temporary
  real SQLite database, the real projection/index/relation repositories, the
  real Runtime policy, and a deterministic local-model fake. This is the
  highest existing seam that can prove the feature while keeping FTS5, graph
  storage, caching, and validation replaceable beneath it.
- Frontend tests do not create a second business-logic seam. Contract and
  relation view-model tests prove that backend states render correctly; a small
  browser test proves the explicit action and confirm/decline interaction. The
  backend remains authoritative for every gate.
- Focused unit tests are reserved for deterministic algorithms whose edge cases
  are difficult to isolate through HTTP: projection hashing, CJK/Latin lexical
  normalization, fingerprint canonicalization, role-pair admissibility, strict
  proposal validation, and deterministic evidence rendering.

### Three sanitized fixture scenarios

| Fixture | Shape | Expected discovery behavior |
|---|---|---|
| Cross-topic positive | A and B have different subject matter but a source-grounded role mapping and explicit transfer boundary; C is unrelated | Exactly one validated candidate for B; C is never shown. |
| Hard-negative corpus | Neither historical asset has a defensible relation package to A | Valid semantic no-match with zero candidates. |
| Invalid false-association proposal | The fake model proposes a forbidden label, nonexistent/wrong-side node, missing boundary, one-sided provenance, or inadmissible role pair | No candidate is displayed; result is validation/technical failure, not semantic no-match. |

### External behavior acceptance matrix

| ID | Behavior at the primary HTTP seam | Required result |
|---|---|---|
| GRAG-01 | Start discovery before exact `KnowledgeCardReady` | Denied with a stable readiness reason; no cross-asset read or model call. |
| GRAG-02 | Accept a card without clicking discovery | No discovery run is created. |
| GRAG-03 | Run the cross-topic positive fixture | One candidate with a fixed relation type, bilateral mapping, boundary, and bilateral provenance; no detail. |
| GRAG-04 | Run the hard-negative fixture | Successful semantic no-match and zero candidates. |
| GRAG-05 | Request `top_k=3` when only one valid relation exists | One candidate; no padding or zero-score fallback. |
| GRAG-06 | Submit each invalid false-association proposal | No candidate; safe validation failure and retry semantics. |
| GRAG-07 | Repeat discovery with the same fingerprint | Same candidate or no-match and no additional model call. |
| GRAG-08 | Repeat after a timeout or malformed response | A new bounded technical attempt is allowed; prior failure is not returned as no-match. |
| GRAG-09 | Change the current card, eligible historical projection, model, prompt, or config | New fingerprint; stale result is not reused. |
| GRAG-10 | Ask for detail before confirmation | Runtime denial; no historical detail read. |
| GRAG-11 | Decline the candidate | Decline persists and detail remains denied. |
| GRAG-12 | Confirm with mismatched candidate/asset bindings | Runtime denial; no broad permission is created. |
| GRAG-13 | Confirm the exact candidate and read detail | Deterministic bilateral evidence card limited to the confirmed asset. |
| GRAG-14 | Compare persisted current snapshot JSON, statement hash, and card hash before/after detail | Snapshot JSON and hashes are identical and no current Experience Asset content version is appended. |
| GRAG-15 | Restart after candidate, decline, or confirmation | SQLite restores the same durable state and permissions. |
| GRAG-16 | Correct or delete either bound asset | Projection and relation become stale; candidate/detail access is removed. |
| GRAG-17 | Attempt prompt injection through canonical summary text | Text remains data; no tool call, scope expansion, or extra output field is accepted. |
| GRAG-18 | Complete no-match or decline and continue | M5 route evaluation remains available. |

### Contract, UI, QA, and local-inference coverage

- Contract tests keep backend models, checked-in JSON Schema, OpenAPI,
  frontend types, public examples, and retrieval-phase traces synchronized.
- Migration tests initialize a fresh database and upgrade the preceding schema,
  verify FTS5 availability, rebuild deterministic projections, enforce unique
  successful fingerprints, and preserve existing M1/M2 data.
- Retrieval repository tests cover current-asset scoping, active-ready summary
  scoping, positive BM25 results, explicit no-match, Chinese and English
  normalization, invalidated-index removal, and hard-negative behavior.
- Runtime policy tests extend existing allow/deny, readiness, version/hash, and
  confirmed relation-binding prior art with projection hashes, fixed relation
  vocabulary, mapping sides, boundary requirements, and validation failures.
- Inference adapter tests follow the existing strict structured-output prior
  art: correct JSON Schema request, no tools, one candidate maximum, no-match
  exclusivity, malformed response, timeout, unavailability, and safe metadata
  retention.
- Relation view-model and component tests cover not ready, ready, running,
  candidate, no-match, technical failure/retry, declined, confirmed, stale, and
  evidence-card states. Existing retrieval-trace gate tests are extended rather
  than replaced.
- Public QA runs the retrieval-phase checker against positive, no-match,
  declined, pre-confirmation denial, invalid-proposal, correction, and
  non-contamination traces. It contains no private blind cases or guessed
  thresholds.
- The eventual E5 local-inference gate runs the positive and hard-negative
  structured proposal on the approved loopback vLLM/W7900 path and records
  exact model/runtime identity. It is required before claiming the real local
  GraphRAG path works, but is not run or claimed by this documentation PR.

## Out of Scope

- Production implementation, migrations, contract regeneration, fixtures, or
  tests in this Spec-only change.
- Generating `/to-tickets`, creating implementation issues, assigning work, or
  starting E5 implementation before collaborator review.
- Merging this specification PR or promoting E5, M4, AC-30, or any competition
  milestone.
- Dynamic “simple task versus difficult task” classification or any other
  Agentic RAG scope-broadening policy.
- Automatic discovery immediately after `KnowledgeCardReady`.
- A user-authored free-text cross-asset comparison query.
- More than one displayed MVP candidate or any requirement to fill the existing
  `top_k=3` default.
- A 50-asset or 100-asset capacity commitment, stress-test claim, or production
  scale target.
- Embeddings, vector retrieval, rerankers, an external graph database, TiDB,
  Supabase, PGlite, or a second canonical data store.
- Graph-community detection, global summaries, open-ended entity extraction,
  or model-created nodes, edges, facts, relation labels, or causal links.
- A multi-stage causal graph connecting critical moments, decisions, and
  insights without explicit canonical evidence.
- Complex confidence scoring, learned ranking, or showing a weak fallback
  relation after validation fails.
- Pre-confirmation historical detail, broad historical access after one
  confirmation, or historical content rewriting current statements.
- A second LLM call to summarize the confirmed comparison, generated advice,
  or new claims in the evidence card.
- Closed remote model APIs in the core path, public service exposure, model
  training, fine-tuning, or a new model selection.
- W7900 benchmark execution, performance Baseline/Candidate changes, or
  submission-quality performance claims in this specification phase.

## Further Notes

- **Status:** requirement decisions are confirmed by the user; engineering
  document status is draft for collaborator review; implementation status is
  not started.
- **Change classification:** material feature/architecture/schema/permission
  specification. It refines the approved E5 gated-RAG deliverable without
  weakening AC-01 through AC-30.
- **Authority mapping:** primary acceptance is AC-30. Supporting criteria are
  AC-03, AC-04, AC-09, AC-10, AC-18, and AC-22 through AC-25. The primary L1
  boundary is M4 and the M4→M5 relation gate. L2 impact includes Canonical
  state, Evidence discipline, Retrieval phase integrity, Persistence and
  resume, Runtime permission, Failure behavior, Privacy, and Local inference.
- **Ownership and sequence:** the approved engineering plan assigns E5/M4 to
  `1olaqua616-web` and requires E4 to merge and pass its quality gate before E5
  integration becomes Ready. This document may guide bounded preparation but
  does not override that dependency.
- **Track 2 impact:** direct. The planned path produces judge-visible local RAG,
  one structured local-model proposal, deterministic tool/policy validation,
  durable memory, explicit user permission, failure behavior, and provenance.
- **Evidence/submission impact:** a future implementation must add a sanitized
  E5 evidence packet and eventually a real W7900 product trace. This PR changes
  only the reviewed design; it adds no runtime evidence and no submission
  claim.
- **Key risks:** local-model semantic false positives, insufficient
  summary-safe canonical fields in unfinished M3/M4 contracts, Chinese lexical
  quality, stale projection access, duplicate relation authority, and mock
  contract drift. The design mitigates them through abstention, deterministic
  role projection, explicit boundary nodes, one relation ledger, version/hash
  invalidation, bilingual lexical tests, and checked-in contract synchronization.
- **Open implementation assumption:** M3 and M4 will expose confirmed record,
  statement, evidence, and bounded canonical labels within the already selected
  role fields. The projection may map only those accepted fields; it does not
  add an E5 extraction schema. If the accepted M3/M4 contracts cannot supply
  one of them, E5 must update this specification through review rather than
  performing a second open-ended extraction from raw text.
- **Deliberate refinement:** the approved architecture permits summary
  discovery after readiness; this specification adds an explicit user click
  before that permitted action. The extra gate spends local-model time and
  historical-summary attention only when the user requests comparison. The
  architecture diagram should be synchronized when the implementation contract
  is accepted.
- **Review handoff:** this specification is intentionally published through a
  repository PR rather than marked `ready-for-agent` in GitHub Issues. After
  collaborator approval, the user will explicitly invoke `/to-tickets`; that
  later phase may create implementation tickets and dependency edges. No ticket
  list is embedded here so review can change the destination before work is
  partitioned.
