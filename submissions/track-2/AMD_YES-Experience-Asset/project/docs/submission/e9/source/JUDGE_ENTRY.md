# Experience Asset - One-Minute Judge Entry

> **Submission document snapshot:** current `main@c4d14bf`; tested application
> `c9ec074`; material snapshot `EA-SUBMISSION-E9-20260806-R8`. All required
> documents and Demo link are included; signed-out link verification remains.

## What it is

Experience Asset is a private local Agent that turns fragmented first-person
experience into an evidence-bound, editable and reusable asset, then prepares
audience-specific deliverables while keeping facts, privacy and approval under
user control.

`M1 Experience Brief -> M2 Critical Moment Map -> M3 Decision and Evidence Ledger -> M4 Insight and Boundary Map -> M5 Route Readiness Matrix -> preview / HTML / Markdown / JSON`

React and FastAPI provide the product surface. LangGraph maintains the durable
workflow. A deterministic Runtime owns tool permissions, validation,
phase-gated retrieval, privacy, approval, retries, persistence and verification.
Core inference is local through loopback vLLM, ROCm and Radeon PRO W7900.

## What is verified

- PR #52 merged the complete product path. Exact implementation `c9ec074`
  passed a real Qwen3.5-9B W7900 journey covering M1-M4, evidence inspection,
  correction-driven invalidation/regeneration, M5 route/privacy evaluation and
  private HTML/Markdown/JSON delivery.
- The local stack is Qwen/Qwen3.5-9B BF16, immutable revision
  `460979c3d11864dd16408d860ac930a360a2fac2`, vLLM 0.26.0, ROCm/HIP 7.2
  and Radeon PRO W7900. Services remained bound to localhost.
- Stage 1 service evidence places P1 first: p95 TTFT 83.89% lower than S0,
  median E2EL 4.33% lower and output TPS 0.47% higher, with 85% warm-up
  reliability.
- The same complete-Agent case passed on both S0 and P1 in the minimal Stage 2
  check. P1 completed in 109.21 seconds versus about 2.0 minutes for S0, but
  this one observation is not a statistical or cache-attribution claim.
- P1 is the selected launch Profile; S0 is the one-command rollback.

## Why it matters

The product is not a one-shot writer. It keeps source facts, judgments,
inferences and gaps inspectable; blocks historical retrieval until readiness
and user confirmation; invalidates stale downstream state; and binds external
delivery to the exact approved version.

## Honest limitations

The Demo uses a public synthetic case. Stage 1 metrics describe the model
service, not complete-Agent acceleration. The one Stage 2 observation is not a
statistical benchmark, recorded no prefix-cache hit and did not measure peak
Stage 2 VRAM. Final editable language still requires user review, and the
project controls rather than eliminates hallucination and privacy risk.

## Submission links

- Team repository: https://github.com/kinnyuww/amd-devmaster-track2-agent
- Project Specification:
  [`../deliverables/Experience_Asset_Project_Specification.pdf`](../deliverables/Experience_Asset_Project_Specification.pdf)
- Presentation:
  [`../deliverables/Experience_Asset_Track2_Deck.pptx`](../deliverables/Experience_Asset_Track2_Deck.pptx)
- Source, setup and startup: [`../../../README.md`](../../../README.md)
- Demo video:
  https://drive.google.com/drive/folders/1_cOmcYBIJuPfkoJ4VuA7ZuBYV8nYB8yr?usp=drive_link
- Official submission PR: not opened; copy is ready in
  [`OFFICIAL_PR_DRAFT.md`](OFFICIAL_PR_DRAFT.md)
