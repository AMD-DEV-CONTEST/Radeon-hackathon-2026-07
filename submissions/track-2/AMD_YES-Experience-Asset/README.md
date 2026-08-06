# Experience Asset

**Track:** Track 2 - Development & Local Deployment of Private AI Agents

**Team:** AMD_YES

**Application:** Experience Asset

Experience Asset is a private local Agent that turns fragmented first-person
experience into an evidence-bound, editable and reusable asset, then prepares
audience-specific deliverables while keeping facts, privacy and approval under
user control.

## Submission materials

- [Project Specification](Experience_Asset_Project_Specification.pdf)
- [Presentation](Experience_Asset_Track2_Deck.pptx)
- [Complete source code](project/)
- [Environment, dependencies, startup and reproduction guide](project/README.md)
- Demo video: **pending public upload**

## Product flow

```text
M1 Experience Brief
-> M2 Critical Moment Map
-> M3 Decision and Evidence Ledger
-> M4 Insight and Boundary Map
-> M5 Route Readiness Matrix
-> private preview / approved HTML / Markdown / JSON
```

React and FastAPI provide the product surface. LangGraph owns the durable
multi-step workflow. A deterministic Runtime owns tool permissions, argument
validation, phase-gated retrieval, privacy, approval, retries, persistence and
verification. Model output is a proposal, never execution authority.

## Local Radeon deployment

- Model: `Qwen/Qwen3.5-9B`, immutable revision
  `460979c3d11864dd16408d860ac930a360a2fac2`
- Precision: BF16; quantization: none
- Serving: vLLM 0.26.0 on ROCm/HIP 7.2
- Device: Radeon PRO W7900, 48 GiB
- Core inference: local, loopback-bound OpenAI-compatible vLLM endpoint
- Selected launch profile: P1-prefix-cache; S0 is the one-command rollback

The exact tested application implementation is
`c9ec07489d17a2abb74bac66a23ade2c775c1b06`. A complete local-model journey
passed on W7900, including M1-M4 generation, evidence inspection, upstream
correction, downstream invalidation/regeneration, M5 route/privacy review and
private HTML/Markdown/JSON delivery.

## Evidence boundary

- Complete-product packet:
  [`project/evidence/milestones/e8-a0-w7900/20260806T122806Z/`](project/evidence/milestones/e8-a0-w7900/20260806T122806Z/)
- Minimal Stage 2 packet:
  [`project/evidence/performance/stage2-minimal/20260806T124938Z/`](project/evidence/performance/stage2-minimal/20260806T124938Z/)

The same complete Agent/model/public case passed with S0 and P1. S0 completed
in approximately 120 seconds and P1 in 109.21 seconds. This is one observation,
not a statistical latency or causal prefix-cache claim; the P1 run reported
0.0% cache hit and Stage 2 peak VRAM was not measured.

The project controls evidence, permission and privacy risk; it does not claim
to eliminate hallucinations. The submission Demo uses public synthetic data.

## Team contributions

- `kinnyuww`: requirements and quality architecture, W7900 serving benchmark,
  integrated device acceptance and Stage 2 evidence.
- `Eas000n`: Runtime foundation, M1/M3/M5 milestones, privacy/approval path and
  submission materials.
- `1olaqua616-web`: React application shell, M2 semantic extraction, gated M4
  retrieval and complete-product integration.
