# Customer SSOT

## Segments
- Procurement and vendor-management teams handling disputed SLAs, renewals, and commitments.
- Customer-success and account teams responding to escalation claims.
- Legal operations and compliance teams that need a reviewable factual record before counsel is engaged.
- Internal project teams resolving "who approved this?" or "what was promised?" disputes.

## Pain Points
- Relevant facts are split across contracts, emails, meeting notes, addenda, and chat exports.
- Generic RAG answers blur binding language, marketing, drafts, and conditional plans.
- Sensitive records cannot be casually uploaded to a public AI service.
- Teams need a human-reviewable record, not an opaque chatbot response.

## Feedback
| Date | Source | Signal | Decision |
| --- | --- | --- | --- |
| 2026-07-19 | Radeon Cloud deployment | GPU and ROCm worked, but public port routing and model egress were unreliable. | Make deployment diagnostics and explicit fallback states first-class; preserve a terminal/API demo path. |

## Objections
- "Can an LLM invent citations?" Answer: citations are validated against the retrieved packet before display/export.
- "Is this legal advice?" Answer: no; it creates a factual evidence brief for human review.
- "Do files leave our trust boundary?" Answer: core document processing and model inference are local to the configured deployment; external browser exposure must be treated as a deployment configuration risk.
- "Why three agents?" Answer: they are controlled serial analysis stages using one model, not a claim of autonomous multi-agent intelligence.

## Success Signals
- A decision-maker uses the brief to request a signed SLA addendum instead of making an unsupported demand.
- Reviewers can open every material citation and understand why the verdict is insufficient, supported, or contradicted.
- Demo viewers ask about applying ClaimCourt to their own approval, delivery, or compliance disputes.
