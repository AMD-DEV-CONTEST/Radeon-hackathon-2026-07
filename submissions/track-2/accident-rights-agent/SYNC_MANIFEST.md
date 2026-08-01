# Accident Rights Agent — Sync Manifest

- Track: 2 — Development & Local Deployment of Private AI Agents
- Source commit: `4a67367`
- Sync date: 2026-08-01 (UTC+8)
- Snapshot: `accident-rights-agent-4a67367.tar.gz`
- Snapshot SHA256: `5bbc9ef4b3c1ee247777ec18ba6ecfd1ed9f99ff0a3ad8fdecd98e75a878090f`
- Legal corpus: 13 authoritative documents, 48 verified verbatim excerpts
- Business agents: Case Intake, Vehicle Nature, and Liability
- Rights workflow: deadline calculation, evidence-gap planning, review draft,
  human approval, and policy gate
- Owner-first local experience: complete, insufficient, and conflicting synthetic cases,
  action-first rights workflow, insurer collaboration, and human approval
- Multimodal demo: JPEG evidence, H.264 MP4 dashcam fixtures, valid PDF records,
  case-isolated document generation, and responsive desktop/mobile UI
- Validation: 140 tests passed, 1 environment-conditioned skip; Ruff and mypy
  (82 source files) passed
- Retrieval regression: Recall@4 1.0000, MRR 0.8333, citation completeness 1.0000

This is the current development snapshot. The final English project specification,
demo video, and supplementary material will be added before the submission pull
request is opened.

The previous `0325716`, `df9a143`, and `df85d5d` snapshots remain available for
rollback. The current archive was generated directly from the clean local Git
commit with `git archive`; ignored cases, checkpoints, vector indexes, model
weights, and runtime credentials are not included.
