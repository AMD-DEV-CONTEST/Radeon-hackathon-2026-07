# Phase E contracts and replay

`EvidenceRecord` is a frozen provenance record. Construct it with
`EvidenceRecord.from_dict`; exactly one of `value` and `value_range` is required,
and supplied hashes must be SHA-256 hex digests. Unknown fields and missing
provenance fields fail closed.

`ModelSelectionAgent.select(request, candidates)` applies capability and
radionuclide applicability rules deterministically. It returns `eligible`, the
single highest-priority `selected` model, and rejected model names mapped to
explicit reasons. Missing applicability data is never treated as eligible.

`ReplayBundle.write(...)` writes normalized input, sources, results, tool trace,
environment metadata, and a SHA-256 manifest. Bundle payloads are strict JSON:
non-finite values and symbolic-link indirection are rejected. `verify_bundle(path)`
verifies integrity. A rerun is never inferred: callers must pass an explicit
deterministic `rerun(input)` callback to compare results. The CLI verifies bundles; its
`replay` command intentionally fails with guidance rather than executing code.
