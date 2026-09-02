# Allowlisted Source Snapshot

This directory is a source-only competition snapshot assembled on 2026-08-07 from:

```text
F:/doyin_mcp_AMD/.worktrees/amd-rocm-port
Git HEAD: 5baa41b5b76283ce20559986219abb0ac3c3e856
Branch: codex/amd-rocm-port
```

It contains 386 files selected by [`../submission-source-whitelist.txt`](../submission-source-whitelist.txt). The import excludes model weights, generated media, databases, caches, logs, private handoff files, real environment files, and credentials.

This is a working-tree snapshot, not a claim that the source was clean at the listed Git revision. Eligible uncommitted source files were included from these paths:

- `creative_hub/src/creative_hub/visual_identity/`
- `drama_factory/src/drama/amd_memory_guard.py`
- `ops/amd/run-h3-production-smoke.py`
- `shared_contracts/src/shared_contracts/amd_resource.py`
- `shared_contracts/src/shared_contracts/visual_identity.py`
- `tests/test_h3_production_smoke_runner.py`

Uncommitted handoff records, model-upload state, and tests outside the allowlist were deliberately not imported. The snapshot should be reviewed as the submitted source state; it must not be treated as a complete Git checkout or as evidence that the final user-initiated AMD GPU Runtime Proof was performed.
