# Case Log: harden-real-workspace-ingestion

## Intent
Goal: Replace demo-only intake assumptions with a safe, diagnosable real-folder scanner and production acceptance criteria

Success criteria:
- None

Risk: high

## Context
Files read:
- None

SSOT used:
- docs/PRD.md
- docs/product.md
- docs/system.md

## Gates
First-principles check:
- None

Assumptions:
- None

Adversarial findings:
- Unrestricted rglob could follow an unexpectedly broad user-selected tree and silently consume dependency caches or oversized files.

Edge cases:
- None

Rejected options:
- None

## Delivery Contract
Status: approved
Why:
Real users will point ClaimCourt at large private folders; unsafe recursive scanning, dependency caches, symlinks, and oversized files can leak scope, hang ingestion, or make failures invisible.

Acceptance criteria:
- {"criterion": "A normal nested workspace returns every supported regular document in deterministic order", "evidence": "unit tests with mixed nested formats", "prohibited": "do not hardcode fixture filenames"}
- {"criterion": "Excluded directories, symlinks, unsupported files, and oversized files are not indexed and have explicit reasons", "evidence": "unit tests plus UI diagnostic rendering path", "prohibited": "do not silently drop files"}
- {"criterion": "Existing callers of discover_workspace still receive a list of paths and the fuzzy/court regression gates remain green", "evidence": "full unit suite and benchmark scripts", "prohibited": "do not weaken existing assertions"}

Anti-gaming rules:
- Synthetic tests prove scanner behavior only, not production readiness of the entire product.
- A successful page load is not evidence that real folder ingestion is safe.

Infeasible or blocked paths:
- L3/L4 real-user directory dogfood is unavailable without selecting a user-approved private test directory.

Alternatives and trade-offs:
- Keep Path.rglob and add UI warnings: rejected because scope control and skip diagnostics remain scattered and silent.
- Add a filesystem watcher now: deferred until the scanner contract and workspace identity are stable.


## Changes
- core.py
- app.py
- tests/test_core.py
- README.md
- HANDOFF.md
- docs/PRD.md
- docs/product.md
- docs/system.md
- docs/case-log/2026-08-04-private-alpha-workspace-scanner.md

## Verification
Required evidence level: 2
Achieved evidence level: 2

Commands:
- python -m py_compile core.py app.py tests/test_core.py scripts/fuzzy_retrieval_check.py scripts/championship_check.py
- python -m unittest discover -s tests -v
- python scripts/fuzzy_retrieval_check.py
- python scripts/championship_check.py

Results:
- 49 tests passed; Streamlit AppTest real-folder path passed; fuzzy Top-1 and Recall@3 100% on 8 synthetic cases; championship 23 files/30 chunks; no live judge.

## Surprises
- None

## Reusable Lessons
- A real private-folder product needs an auditable scan contract before retrieval quality matters; fixture accuracy cannot compensate for silent scope expansion or skipped files.

## Follow-ups
- Implement isolated named workspaces and retention controls before background watching.
