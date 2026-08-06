# Case Log: finalize championship PRD and durable product memory

## Intent
Goal: Publish ClaimCourt's competition strategy, final product scope, and detailed PRD with verified documentation and deployment lessons.

Success criteria:
- None

Risk: low

## Context
Files read:
- None

SSOT used:
- None

## Gates
First-principles check:
- Judges need a credible private-agent workflow with visible evidence discipline and AMD GPU proof, not simulated multi-agent autonomy.

Assumptions:
- A single local Qwen3-class model can support controlled roles once model artifacts are available.

Adversarial findings:
- Cloud routing, ephemeral environments, and blocked model egress can invalidate a polished UI demo, so deployment health and fallback states must be explicit.

Edge cases:
- Empty uploads, parser failure, unavailable model endpoint, untrusted citations, and export without approval must be safe visible states.

Rejected options:
- A broad document-chat product was rejected because it is less memorable and does not foreground contradiction analysis or approval-gated privacy.

## Changes
- docs/company.md
- docs/product.md
- docs/customers.md
- docs/system.md
- docs/PRD.md

## Verification
Commands:
- None

Results:
- None

## Surprises
- None

## Reusable Lessons
- On Radeon Cloud, preserve project and model artifacts outside ephemeral runtime, avoid restarting Jupyter without a recovery plan, and use an SSH tunnel for private UI access when the provider web gateway fails.

## Follow-ups
- None
