# Accident Rights Agent — Sync Manifest

- Track: 2 — Development & Local Deployment of Private AI Agents
- Source commit: `df85d5d`
- Sync date: 2026-07-29 (UTC+8)
- Snapshot: `accident-rights-agent-df85d5d.tar.gz`
- Snapshot SHA256: `121c3607afbfae1b71ee5408b5795912344d0c5e88f395b9e5b198179979f191`
- Legal corpus: 13 authoritative documents, 48 verified verbatim excerpts
- Business agents: Case Intake, Vehicle Nature, and Liability
- Rights workflow: deadline calculation, evidence-gap planning, review draft,
  human approval, and policy gate
- Local experience: `/experience` with complete, insufficient, and conflicting synthetic cases
- Validation: 90 tests passed; Ruff, mypy, and compileall passed
- Retrieval regression: Recall@4 1.0000, MRR 0.8333, citation completeness 1.0000

This is the current development snapshot. The final English project specification,
demo video, and supplementary material will be added before the submission pull
request is opened.

The previous `0325716` and `df9a143` snapshots remain available for rollback. The current archive
was generated directly from the clean local Git commit with `git archive`; ignored
cases, checkpoints, vector indexes, model weights, and runtime credentials are not
included.
