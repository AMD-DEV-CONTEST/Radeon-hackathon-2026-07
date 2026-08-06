# Company SSOT

## Identity
- Name: ClaimCourt
- One-line description: A private local AI evidence court that turns sensitive documents into cited verdicts, contradiction timelines, and approval-gated decision briefs.
- Owner: AMD AI DevMaster Hackathon 2026 Track 2 team

## Mission
Make high-stakes document disputes auditable without sending private evidence to a closed remote model.

## Business Model
- Customers: Security-conscious operations, legal, procurement, customer-success, and compliance teams.
- Offer: A locally deployed evidence-analysis agent for disputed commitments, approvals, obligations, and timeline reconstruction.
- Pricing: Post-hackathon hypothesis: private-team deployment and support subscription.
- Revenue model: Not in scope for the hackathon; product-market signal is a repeatable decision brief that saves expert review time.

## Operating Principles
- Evidence before prose: every material conclusion must trace to retrieved source evidence.
- Privacy by architecture: documents, embeddings, prompts, and reports stay inside the trusted deployment boundary.
- Controlled agency: fixed roles and schemas beat unconstrained autonomous loops.
- Honest degradation: unavailable model, inaccessible source, or insufficient evidence must be visible states, never hidden substitutions.
- AMD proof is part of the product: local Radeon/ROCm inference, latency, and throughput are observable in the demo.

## Constraints
- Time: Hackathon submission deadline is 2026-08-06 23:59 Beijing time.
- Budget: Limited Radeon Cloud credits; only one active GPU instance per account.
- Legal/compliance: Demo corpus must be synthetic. Real customer documents must never be used in public demo materials.
- Technical: Core inference must run on an AMD Radeon GPU with ROCm and must not depend on a closed remote model API.

## Current Priorities
1. Preserve a reliable, judge-ready end-to-end demo on Radeon Cloud.
2. Replace the explicit fallback demo path with a GPU-backed Qwen3-class local vLLM path once model artifacts are available.
3. Produce English submission materials: README, PRD/specification, benchmark evidence, video, and poster/PPT.
