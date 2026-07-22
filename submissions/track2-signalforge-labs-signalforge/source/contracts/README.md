# SignalForge Contracts

Retrieval boundaries are also versioned: `evidence-chunk.schema.json` preserves point-in-time
regulatory and investor-relations lineage without pretending issuer material is an SEC filing.
The original `filing-chunk.schema.json` remains as a legacy Sprint 05 artifact, while
`retrieval-vector-fixture.schema.json` separates reproducible derived vectors
from source evidence. Structured financial facts and calculation receipts remain directly
resolvable and are not converted into opaque embedding-only records.

Official investor-relations discovery is bounded by
`investor-relations-source-map.schema.json`. The corresponding Go policy validates issuer,
allowlisted domains, document class, authority tier, timestamps, content identity, rights class,
and supersession before narrative material can enter retrieval. The bounded golden corpus is
portable through `investor-relations-document-manifest.schema.json`; raw issuer files stay outside
Git while their immutable identities remain testable.

SignalForge agents, engines, and evidence tooling communicate through versioned JSON contracts.
The canonical Go types and fail-closed validation rules currently live in
`internal/contracts`.

Version `signalforge/v1` establishes four boundaries:

- `ContextPacket`: evidence-grounded specialist findings for one research step;
- `EngineRequest`: an authorized request for a registered deterministic operation;
- `CalculationReceipt`: immutable numerical results, validation, provenance, and replay data;
- `ReceiptSupersession`: append-only linkage from a prior receipt to a corrected replacement;
- `EvidenceManifest`: the code, model, dataset, environment, and artifact identity behind a measured run.

Portable JSON Schemas currently cover:

- `engine-request.schema.json`;
- `calculation-receipt.schema.json`;
- `failure-receipt.schema.json`;
- `evidence-manifest.schema.json`;
- `benchmark-row.schema.json`;
- `research-trace.schema.json`;
- `orchestration-trace.schema.json`;
- `safe-decision-replay.schema.json`;
- `golden-journey-scorecard.schema.json`;
- `golden-semantic-rubric.schema.json`;
- `golden-semantic-evaluation.schema.json`;
- `demo-evidence.schema.json`.

`orchestration-trace.schema.json` is the runtime state-machine trace. It records only bounded
identifiers, lifecycle events, artifact references, concurrency, and timestamps. Prompt text,
answers, credentials, tokens, and secret-shaped metadata are outside this contract by design.

`safe-decision-replay.schema.json` is the public, privacy-safe projection of a golden run. It keeps
route reason codes, content hashes, claim dispositions and their explicit assumption authority,
aggregate and per-role latency, token
counts, and an optional all-or-none Radeon runtime attestation. It deliberately excludes prompt
bodies, response bodies, chain-of-thought, source locators, and failure messages.

`golden-journey-scorecard.schema.json` separates measured runtime and release-integrity properties
from claims that have not been established. Its quality block reports disposition, authority,
review, evidence coverage, and a hash-bound frozen semantic rubric while explicitly recording that
external answer accuracy has not been scored against an independent ground truth. Passing the
frozen rubric establishes contract conformance, not universal factual accuracy.

All decimal values are JSON strings. Production Go validation remains
authoritative; the schemas make the boundary portable to fixtures, CI, and
independent consumers.

Material facts require primary-evidence references. Material calculations require successful,
replayable receipts. Inferences require both support and explicit assumptions. A confidence score
never replaces evidence.
