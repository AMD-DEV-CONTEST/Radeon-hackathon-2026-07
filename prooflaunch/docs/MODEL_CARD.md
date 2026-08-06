# ProofLaunch Competition Model Card

## Intended use

ProofLaunch is a multimodal GTM production and governance system. It is designed
to help campaign operators turn rights-bound product evidence into review-ready
strategy and media while preserving traceability and human release authority.

It is not intended to autonomously publish, send, spend, approve claims,
provide financial advice, or make causal revenue claims.

## Competition model roles

| Role | Model family | Purpose | Key evidence |
|---|---|---|---|
| Understand | Qwen3-VL | Product/image/video observations with source locators | Model ID, revision, input hash |
| Reason | Gemma multimodal-safe adapter | Audience and emotion reasoning under retained modality checks | Base revision, adapter hash |
| Create | SDXL | Image candidate generation | Prompt/input hash, seed, steps, dtype |
| Motion | LTX-Video | Image-to-video candidate generation | Model revision, seed, timing |
| Semantic audit | SigLIP2 | Candidate-to-brief similarity | Revision and threshold |
| Product localization | GroundingDINO + SAM2 | Object grounding and temporal identity tracking | Revision, boxes/masks, tolerance |
| Audio audit | CLAP | Audio semantic alignment | Revision and score |
| Optional transcript | Whisper | Timestamped transcript evidence | Revision and segment locators |

The immutable registry is [`config/model_supply_chain.json`](../config/model_supply_chain.json).

## Execution design

The supervisor sequences model calls and admits only one heavy model at a time.
Each adapter has typed inputs and outputs. A candidate moves through claim,
identity, typography, safe-zone, cross-media, and codec checks before delivery.
Failed candidates may receive at most two recorded repair rounds.

## Inputs and outputs

Inputs may include product images, selectable-text specifications, approved
claims, audience, market, platform, goal, and optional audio/video references.
Outputs include structured strategy documents, channel assets, campaign media,
audit findings, repair receipts, approvals, and a content-addressed export.

## Limitations

- Model observations may be wrong or incomplete and require source review.
- Mechanical scores are not named-human preference or production effect.
- Platform and policy requirements change and need current human review.
- High-regulation marketing requires domain and legal approval.
- Local memory and VRAM limits can reduce resolution, duration, or throughput.
- The deterministic evaluator replay is not proof of a fresh end-to-end Radeon
  campaign run; historical Gemma-4 Radeon execution is evidenced separately.

## Safety and release authority

Models cannot publish, send, spend, approve, or promote learning. A named human
must approve the exact content hash released. Tenant isolation, bounded
budgets, immutable audit events, and fail-closed evidence gates are enforced in
code.

## Licensing

Project code is MIT licensed. Model weights, datasets, fonts, and media retain
their own terms and are not relicensed by this repository. Users must review
the supply-chain registry and [`THIRD_PARTY.md`](../THIRD_PARTY.md) before
download or redistribution.
