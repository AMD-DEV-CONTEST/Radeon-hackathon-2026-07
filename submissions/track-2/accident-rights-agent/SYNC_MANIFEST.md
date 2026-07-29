# Accident Rights Agent — Sync Manifest

- Track: 2 — Development & Local Deployment of Private AI Agents
- Source commit: `df9a143`
- Sync date: 2026-07-29 (UTC+8)
- Snapshot: `accident-rights-agent-df9a143.tar.gz`
- Snapshot SHA256: `d86bdf32d50484498b7cdd95d070890147cad33f8417ca1d875aa2fac1e3fb02`
- Legal corpus: 13 authoritative documents, 48 verified verbatim excerpts
- Business agents: Case Intake, Vehicle Nature, and Liability
- Local experience: `/experience` with complete, insufficient, and conflicting synthetic cases
- Validation: 63 tests passed; Ruff, mypy, and compileall passed
- Retrieval regression: Recall@4 1.0000, MRR 0.8333, citation completeness 1.0000

This is the current development snapshot. The final English project specification,
demo video, and supplementary material will be added before the submission pull
request is opened.

The previous `0325716` snapshot remains available for rollback. The current archive
was generated directly from the clean local Git commit with `git archive`; ignored
cases, checkpoints, vector indexes, model weights, and runtime credentials are not
included.
