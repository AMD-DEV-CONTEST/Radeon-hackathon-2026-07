# Accident Rights Agent — Sync Manifest

- Track: 2 — Development & Local Deployment of Private AI Agents
- Source commit: `4a67367`
- Sync date: 2026-08-01 (UTC+8)
- Snapshot: `accident-rights-agent-4a67367.tar.gz`
- Snapshot SHA256: `67d1a03cf29848fff5be13672eb06a983f607271b4c17a96ca6b618165cf7292`
- Legal corpus: 15 curated documents and 59 audited excerpts; 14 source records
  passed the automated online official-source gate. The GA 802 excerpts passed
  the retained official-snapshot audit, while its live verification endpoint
  could not be rechecked because that government site presented a self-signed
  TLS certificate
- Offline runtime assets: official-source snapshots, quote audit, SQLite legal
  corpus, and local Qdrant index are included so `bash scripts/run_demo.sh`
  works from a clean checkout without a public API or network fetch
- Legal runtime bundle SHA256: `6d349999918bb494f19dfbfd7dd3158d1e5da526b00ccb7f69689ee245db8d22`
- Business agents: Case Intake, Vehicle Nature, and Liability
- Rights workflow: deadline calculation, evidence-gap planning, review draft,
  human approval, and policy gate
- Owner-first local experience: complete, insufficient, and conflicting synthetic cases,
  action-first rights workflow, insurer collaboration, and human approval
- Multimodal demo: JPEG evidence, H.264 MP4 dashcam fixtures, valid PDF records,
  case-isolated document generation, and responsive desktop/mobile UI
- Local validation: 140 tests passed, 1 environment-conditioned skip; Ruff and
  mypy (82 source files) passed
- Radeon Cloud validation: 141 tests passed; Golden Case completed in 57.494s
  (mock) and 63.665s (local vLLM), with both flows stopping at human approval
  and leaving the generated document in `draft`
- AMD local inference: Qwen3-VL-8B on ROCm 7.2/vLLM, loopback-only endpoint,
  Prefix Cache enabled; text, image, and eight-frame smoke tests passed
- Radeon stability: vLLM remained healthy for 32m26s, the final interval test
  passed 10/10 requests, UI health passed, and the vLLM log contained no OOM or
  traceback markers
- Retrieval regression: Recall@4 1.0000, MRR 0.8333, citation completeness 1.0000

This is the current development snapshot. The final English project specification,
demo video, and supplementary material will be added before the submission pull
request is opened.

The previous `0325716`, `df9a143`, and `df85d5d` snapshots remain available for
rollback. The source archive was generated directly from the clean local Git
commit with `git archive`. This submission snapshot additionally includes the
verified, model-independent legal runtime assets needed for offline startup.
Cases, checkpoints, model weights, and runtime credentials are not included.
