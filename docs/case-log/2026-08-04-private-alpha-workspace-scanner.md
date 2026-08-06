# Private Alpha Workspace Scanner

Date: 2026-08-04

## Decision

ClaimCourt is a real-product effort at private-alpha maturity. `demo_corpus` and `championship_corpus` are regression fixtures and presentation aids, not the product boundary and not evidence of general production readiness.

The first production-hardening slice replaces unrestricted `Path.rglob` discovery with a policy-controlled `WorkspaceScanner` module. Its public interface is `scan(root) -> WorkspaceScanResult`; existing callers retain `discover_workspace(root) -> list[Path]` through a compatibility wrapper.

## User Outcome

When a user explicitly selects a real folder, ClaimCourt now reports what it scanned, what is indexable, and what was skipped. It does not silently follow links outside the selected root or recursively ingest common dependency/cache directories.

## Implementation

- Deterministic recursive file discovery.
- Explicit supported-suffix filtering.
- Conservative exclusions for VCS, IDE, cache, virtual environment, build, and dependency directories.
- Hidden-entry exclusion by default.
- Symlink and Windows junction rejection.
- Default 100 MiB per-file limit and 50,000-file workspace limit.
- Structured skip counts and bounded diagnostic records.
- Streamlit scan summary and skip-reason display.
- Backward-compatible `discover_workspace` list result.

## Evidence

- Python compilation passed.
- 49 unit/regression tests passed.
- New adversarial tests cover deterministic order, excluded directories, hidden directories, unsupported files, file-size limits, file-count limits, and file symlinks.
- Streamlit AppTest indexed one supported document from a temporary real directory, excluded `node_modules`, displayed the scan result, and produced no exceptions.
- Fuzzy benchmark remained Top-1 100% and Recall@3 100% on eight synthetic queries; deterministic compiler mode only.
- Championship check remained green for 23 files and 30 chunks; live judge was not run.

Evidence level is L2 for scanner integration. This does not prove L3/L4 reliability on the owner's private document collection.

## Residual Risks

- One global index can still mix unrelated roots; named and isolated workspace identity is required.
- Index evidence and history are still plaintext at rest; encryption and key management are unresolved.
- Synchronization is manual; there is no background watcher, cancellation, or progress job.
- In-memory TF-IDF and character matrices rebuild globally and need scale testing.
- Parser/OCR/embedding/reranker coverage still requires Radeon Cloud and real-format verification.
- The fuzzy benchmark is small and synthetic; it is a regression gate, not a universal accuracy measure.
- Authentication and concurrent-user behavior are not defined.

## Next Slice

Implement isolated named workspaces with a manifest containing selected roots, scan policy, index version, sync status, and retention controls. Verify migration from the current single-index layout before adding background synchronization.
