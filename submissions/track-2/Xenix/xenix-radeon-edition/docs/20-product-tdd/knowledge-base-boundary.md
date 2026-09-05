# Knowledge Base Boundary

## Product Topology

Xenix exposes one global Knowledge Library in MVP while retaining an internal
library identity for future multiple-library instances. The Knowledge Workspace is
a secondary window; its Workspace-local `Task queue` is modeless. Import, retrieval,
document lifecycle, and Agent use remain service-owned rather than UI-owned.

```text
local file
  -> probe / normalize / parse / canonicalize
  -> source CAS + DoclingDocument envelope -> canonical-ready

canonical-ready generation
  -> independent derive / chunk / index publication
  -> retrieval-ready KnowledgeUnits + derived search projections
  -> knowledge.lookup -> bounded source-linked evidence
```

## Import Contract

- Accepted MVP inputs are TXT, DOC/DOCX, PPT/PPTX, PDF, JPEG, and PNG. Image sources
  use OCR; they do not imply VLM support. Markdown remains outside the committed MVP.
- `DoclingDocument` JSON is the common content IR. Xenix wraps it in an immutable
  envelope that binds document/import/generation identity, source and IR hashes,
  route descriptors, assets, and validation facts. SQLite—not the envelope—owns
  mutable lifecycle, readiness, and current-generation pointers.
- One immutable format capability binds a source suffix/media type to probe,
  normalizer, route-planner, and parser providers. The four pipeline stages dispatch
  through validated provider maps; extending the format set does not add a new
  central format branch. OOXML Word and PowerPoint packages share one
  format-parameterized safety verifier. Legacy DOC and PPT are configurations of one
  bounded LibreOffice normalization boundary, targeting DOCX and PPTX respectively,
  before the matching Docling Office parser.
- PDF routing consumes bounded page evidence rather than one document-wide choice.
  Native text is classified as `credible`, `suspect`, or `absent` from extracted
  text, suspicious Unicode, image coverage, and font evidence. Credible pages use
  native Docling, absent pages use OCR, and suspect pages use native+OCR hybrid when
  OCR is ready. Xenix does not claim generic complex-layout understanding from this
  classifier alone.
- Local OCR uses one optional, one-click-installed archive containing an
  Xenix-owned native worker built on official Paddle Inference C++, its compiled-in
  fixed pipeline configuration, complete dependency closure, and an explicitly
  identified model pack. Setup verifies the catalog, archive, member manifest,
  protocol, and self-test before atomic activation. The worker does not resolve a
  pipeline config from the build tree, its working directory, or a companion file.
  Deployment consumes one bundle source that binds catalog authority to either the
  generated local development archive or the immutable release origin; transport
  cannot bypass deployment-owned integrity gates. `ready` additionally requires a
  compact content-addressed generation directory and a self-test executed at that
  final Windows path before active-pointer publication, plus a
  freshness-bounded verification
  record produced by full member hashing and self-test; missing/stale evidence is
  refreshed off the UI thread. Canonical provenance records the exact runtime,
  generation, model pack, engine, protocol, and manifest identity actually used. It
  installs no Python packages and uses no global Paddle model cache. OCR runtime
  ownership is separate from LLM configuration and from import orchestration.
- OCR is an engine-neutral capability boundary. A managed Radeon realization may
  use KServe V2 with PAGE 2024-07-15 while preserving the same parent-owned
  import/canonical-publication authority. PAGE requests are PNG-only and carry
  one decoded logical image; responses contain one `PcGts/Page`. Text lines use
  preferred `TextEquiv index=1`; Xenix applies inverse transform, round-half-up,
  and bounds clamping. Legal no-text is an empty success, while transport,
  authentication, deadline, binding, XML, schema, and generation failures fail
  the whole import attempt without a partial canonical publication. The managed
  parent holds admission until its spawned child settles; the child receives only
  an ordinary memory-only OCR specification and imports no deployment manager.
- The selected user file is never modified. The parent snapshots source bytes into
  app-owned CAS. A worker may write canonical bytes only to its exact private
  attempt directory and returns one strict typed result manifest; the parent
  validates its hashes/identity and atomically moves it into canonical CAS.
  Same-library SHA-256 content reuses the current document membership by default.
- Heavy probe/normalize/parse/OCR/canonical work for one attempt executes in one
  spawned process, including Docling conversion in that process. The child has no
  SQLite or CAS-publication authority; the parent supervises one bounded operation,
  validates its envelope, and alone publishes application state. Crash, timeout, or
  cancellation leaves at most disposable private staging and cannot make a partial
  document current. On Windows the import worker owns a kill-on-close Job Object.
  Parent cancellation terminates that one managed boundary and its LibreOffice or
  native OCR descendants; cancellation callbacks do not propagate through pipeline,
  file, or OCR APIs.
- Default application and service composition always selects the spawned runner.
  Inline execution is an explicit test seam; injecting a normalizer or OCR double
  cannot silently change the process topology or count as package evidence.
- Each attempt has a bounded, content-free event log readable from the Workspace
  `Task queue`. The worker result distinguishes outcome, failure stage, and a safe
  diagnostic code; the parent separately records launch failure, timeout, process
  crash, and invalid result. Durable events never contain source paths, passwords,
  credentials, document excerpts, provider payloads, or arbitrary exceptions.

## Storage and Retrieval Authority

- SQLite owns bounded business/search metadata: document identity/current state,
  import status, Knowledge Units, source locators, and the FTS5 projection.
- The content-addressed filesystem store owns source bytes and compressed canonical
  envelopes. `ArtifactService` registers user-openable app-owned files; raw paths do
  not become Agent-facing identity.
- A Knowledge Unit is the current retrievable authority for a bounded passage.
  Derivation preserves page or passage anchors and splits oversized Docling items
  before any embedding call. FTS tokens, ranking values, query-centered excerpts,
  embeddings, and vector indexes are derived access paths and may not become a
  second content authority.
- Retrieval compatibility is published with each logical document as a projection
  version, bounded content fingerprint, and Unit count. A schema change clears the
  current retrieval pointer and re-derives from canonical content; persisted legacy
  Units do not become searchable merely because their rows still exist. Status and
  corpus compatibility use this bounded metadata instead of reading every Unit body.
- Unit identity is derived deterministically from document, canonical generation,
  projection version, and ordinal. One repository snapshot reads current projection
  metadata and ordered Unit DTOs from the same SQLite view and validates their
  implied identities/counts. Vector build embeds only that frozen snapshot and
  rechecks the same identity before publication and before the observable task can
  succeed.
- For retrieval-ready documents, keyword lookup is the minimum baseline. Semantic
  and hybrid lookup are compatible derived projections; absence of embeddings must
  not disable an available keyword projection or cause an explicit semantic/hybrid
  request to fall back silently. Canonical-ready alone does not imply retrieval-ready.
- Embedding configuration is independent from LLM configuration. SQLite publishes
  immutable generation metadata; each LanceDB directory contains only unit identity
  and vectors, and is accepted only when its bounded manifest, corpus/profile
  fingerprints, dimensions, count, path, and ordered current unit identities agree.
  MVP vector search is exact flat cosine search; hybrid retrieval fuses the SQLite
  FTS rank and vector rank deterministically with reciprocal-rank fusion.
- Index rebuilds are explicit, serialized, observable derived-state tasks. A corpus
  change may coalesce a text-vector rebuild only when Embedding is enabled and
  searchable Units exist. Keyword rebuild replaces FTS from current Units in one
  SQLite transaction; a vector generation is published only after its frozen corpus
  and non-secret compatibility profile still match current state.
- `KnowledgeDerivationService` is the only production publisher of ready Units and
  FTS rows. `KnowledgeService` is retrieval-only; test corpus seeders remain outside
  production code. A benchmark fixture enters through Import and canonical
  derivation rather than manufacturing a ready corpus.
- `KnowledgeDocumentLifecycleService` owns user-requested library membership
  removal. One guarded transaction deactivates the active membership; active import
  or derivation work yields a typed busy result. Retrieval and corpus fingerprints
  select active membership, so the visibility cutover is immediate and a
  superseded vector generation cannot remain authoritative. Index convergence is a
  separate coalesced corpus-change notification. Source/canonical lineage, task
  logs, and managed bytes are not synchronously deleted; retention/reachability
  policy remains an independent storage concern and never mutates the user's
  original file. Re-importing identical same-library content reactivates the same
  document identity and emits the symmetric corpus-change notification.

## Agent Contract

`knowledge.lookup` is the sole MVP Agent operation. It accepts a business-language
query and optional `auto`, `keyword`, `semantic`, or `hybrid` mode; result count and
document scope remain service-owned. An explicit requested projection that is not
ready returns typed unavailability rather than silently substituting keyword
retrieval. `auto` may fall back to a fresh keyword lookup only for expected semantic
readiness/provider/vector unavailability; integrity or unexpected failures remain
failures. A success reports the resolved mode and bounded
`source`/optional-human-location/`excerpt` results. It never exposes query echo,
scores, document/unit/generation/artifact/citation identities, raw locator objects,
filesystem paths, credentials, index internals, or entire documents.

Lookup is read-only with respect to indexes: it never embeds content or creates a
generation. Explicit semantic/hybrid mode reports typed unavailability unless the
exact current profile/corpus generation exists; `auto` may use keyword under the
bounded fallback rule above.

The Knowledge Workspace lists logical documents. The document viewport and the
footer status are independent background projections: first load is explicitly
loading, only a completed empty document query may show empty-library copy, and
slow/failing OCR or index status cannot withhold or erase the last successful
document list. Its service-owned `Task queue`
folds import plus initial content preparation into one intent row, shows independent
content preparation and index builds separately, and exposes only the actions
supported by each owning service. This is a presentation/query plane over separate
lifecycle authorities, not a generic task authority; internal `KnowledgeTask*`
identities remain domain-specific.
Right-clicking a concrete document item exposes `Delete` for that item. The
confirmation names the document, states that the imported copy/search/task state
will be removed, preserves the original file, and states that removal cannot be
undone. Removal runs through the lifecycle service off the UI thread; the Workspace
does not issue SQL or filesystem mutations and no deletion operation is exposed to
the Agent.
The Workspace shell and document-list viewport accept local file drops. Drag/drop
and the file picker feed one ordered, deduplicated submission operation; the drop
adapter extracts local URLs only, while `KnowledgeImportService` remains the
authoritative admission and task-creation boundary.
Knowledge Base Settings—not AI Settings—owns Embedding, OCR readiness/setup, index
status, and manual keyword/text-vector rebuild. An Embedding compatibility change is
confirmed only when it changes vector space and current searchable content exists;
credential and batching-policy edits do not falsely claim vector incompatibility.
Multimodal visual retrieval is not implied by preserving images or OCR text.

Knowledge retrieval methodology belongs to the data-analysis Skill, with small local
rules in preprocessing and modeling. The Tool remains commonly advertised; Skill
activation is methodology, not authorization, and does not grant a new tool scope.

## Verification Anchors

- Import formats, deduplication, encrypted retry, canonical CAS, independent
  derivation, PDF routing, bounded packages, and OCR adaptation:
  `tests/test_knowledge_import_service.py`,
  `tests/test_knowledge_import_lifecycle.py`,
  `tests/test_knowledge_pipeline_boundaries.py`,
  `tests/test_knowledge_pdf_routing.py`,
  `tests/test_knowledge_content_store.py`, and
  `tests/test_paddle_ocr_service.py`.
- SQLite/FTS, semantic/hybrid retrieval, and tool result shape:
  `tests/test_knowledge_retrieval.py`, `tests/test_knowledge_semantic_service.py`,
  `tests/test_knowledge_vector_store.py`, and `tests/test_knowledge_lookup_tool.py`.
- Independent embedding settings/wire contract and production composition:
  `tests/test_embedding_service.py`, `tests/test_settings_dialog.py`, and
  `tests/test_agent_composition.py`.
- Workspace loading, item removal, and queue composition:
  `tests/test_knowledge_import_ui.py`, `tests/test_knowledge_document_lifecycle.py`,
  and `tests/test_knowledge_task_query.py`. Picker/drop parity is covered by the
  first; the lifecycle suite proves retrieval cutover, reference-aware CAS cleanup,
  vector invalidation/rebuild, and same-SHA re-import.
- Import process/log and index lifecycle boundaries:
  `tests/test_knowledge_import_worker.py`, `tests/test_knowledge_index_service.py`,
  and `tests/test_settings_dialog.py`.
- Rule-plus-data Agent behavior:
  `benchmarks/agent_harness/test_rainy_season_restock.py`.
- Startup reclamation and derived-vector maintenance:
  `tests/test_knowledge_import_storage_maintenance.py` and
  `tests/test_knowledge_storage_maintenance.py`.
- Native OCR protocol and packaged delivery: `tests/test_paddle_ocr_worker.py`,
  `tests/test_paddle_ocr_service.py`, and
  `tests/test_knowledge_packaged_smoke.py`. With the locked native archive/image
  inputs, packaged smoke proves Import→Canonical→Derivation→lookup plus runtime
  provenance, not activation alone. The same smoke imports DOCX and PPTX through
  the frozen app's spawned Import worker and derives searchable presentation text.
  Run
  `pdm run package` followed by `pdm run smoke-package`.

An image may be canonical-ready while retrieval remains unavailable when local OCR
is absent or yields no text. Passwords for encrypted documents are attempt-local and
never persisted. Source-size, image-pixel, TXT, DOCX package, subprocess, canonical,
OCR-result, provider-response, Unit, query, and Tool-result limits have executable
boundary tests. Hierarchy-aware quality enrichment and bounded retention of
superseded healthy Lance generations remain later work; they do not change current
lookup correctness. The live semantic Agent case still requires explicit subject
LLM and Embedding settings and grades only final answer surfaces, never Tool
telemetry.
