# Product SSOT

## Product
- Name: ClaimCourt: A Private Local AI Evidence Court
- Category: Private AI agent for evidence-grounded business decisions
- Promise: Turn a disputed claim across private documents into a cited verdict, contradiction timeline, and approval-gated decision brief without exporting the evidence to a closed remote model.

## Target Users
- Primary user: An operations, procurement, customer-success, or legal-operations lead preparing for a dispute or negotiation.
- Buyer, if different: A security-conscious team lead responsible for private AI deployment.
- Jobs to be done:
  - Determine what the record actually supports before escalating a dispute.
  - Separate binding commitments from sales language, drafts, exceptions, and assumptions.
  - Produce an auditable brief another human can inspect and approve.

## Scope
### In Scope
- Local intake of PDF, DOCX, TXT, Markdown, and EML evidence.
- Local chunking and retrieval with stable citation identifiers.
- A controlled prosecution -> defense -> judge workflow using one local instruction model.
- Structured verdict JSON: claim, verdict, confidence, citations, contradictions, timeline, missing evidence, and next action.
- Citation whitelist enforcement and explicit insufficient-evidence outcomes.
- Local session memory, approval-gated Markdown export, and Radeon/ROCm performance telemetry.
- Vague local artifact discovery followed by an all-chunk, citation-grounded summary from the live local model.
- A query-only local intent compiler trained on synthetic fuzzy-recollection examples; private workspace text is never used as training data.
- Synthetic SLA dispute demo corpus and a deterministic fallback only when local inference is unavailable.

### Out of Scope
- Legal advice, autonomous negotiation, automatic contract modification, or a claim that the verdict is legally binding.
- Training on private workspace documents or changing the judge's base model weights; a small optional LoRA is allowed only for the query-only intent compiler using synthetic data.
- Multi-model autonomous debate, browser automation, external closed-model APIs, or public sharing of real private documents.

## Core Workflows
1. Load the synthetic demo or upload trusted local evidence.
2. State a disputed claim.
3. Retrieve an evidence packet with stable citations.
4. Run prosecution, defense, and judge roles against that packet only.
5. Inspect verdict, evidence, contradictions, timeline, and missing evidence.
6. Explicitly approve export of a local decision brief.

For artifact-recovery requests, steps 3-5 become: compile fuzzy recollection -> rank file families -> select a confident file -> summarize every chunk locally -> show the full path, cited overview, and key points. Low-confidence recollections trigger a clarification question instead of a guessed file.

## Roadmap
### Now
- Private-alpha product path: controlled real-directory scanning, explicit skip/parser diagnostics, persistent provenance, reliable Radeon Cloud inference, and adversarial retrieval evaluation.
- Treat `demo_corpus` and `championship_corpus` only as regression fixtures and presentation material, never as proof of general product readiness.

### Next
- Isolated named workspaces, incremental background synchronization, user-controlled retention/deletion, encrypted local case memory, source-page anchors, and a benchmark panel built from owner-approved non-repository documents.

### Later
- Team roles, signed case audit logs, policy packs, private on-premises deployment, and evaluation datasets across procurement and approval disputes.

## Success Metrics
- Every displayed verdict cites only retrieved evidence.
- The SLA demo reaches the intended `insufficient_evidence` verdict with a signed-addendum next action.
- A first-time viewer can explain the product in 10 seconds: "AI puts private evidence on trial locally."
- On the synthetic eight-query fuzzy benchmark, intent-aware retrieval reaches 100% Top-1 and Recall@3 versus 62.5% and 75% for raw BM25; this benchmark is a release regression gate, not a universal accuracy claim.
- On the analyst-reviewed private alpha manifest dated 2026-08-05 (60 total rows, hash `b277f451...60cda`), 37 single-target cases reached 100% Top-1, 40 positive retrieval cases reached 100% Recall@5, three multi-target cases reached 100% full coverage, and 12 explicit no-answer cases reached 100% abstention. Auto-selection precision was 100% at 85% coverage with zero unsafe wrong auto-selections. Raw queries, paths, labels, and document text remain outside Git; owner review is still required before calling the manifest gold.
- External holdout baseline (deterministic path, no embedding/router): SciFact Top-1 55.33% and Recall@10 80.31%; BRIGHT biology Top-1 9.71% and Recall@10 15.03%; C-MTEB T2Reranking first 100 valid-query Top-1 59.60%. These results mean fuzzy semantic understanding remains alpha and must not be described as solved.
- Radeon Cloud demo records GPU architecture, ROCm/HIP/vLLM versions, model name, quantization/dtype, first-token latency, end-to-end latency, completion tokens, and output tokens/s.
- No real document or model prompt reaches a closed remote API.
- Every real-directory scan reports included files, exclusions, limits, and unreadable items; no skipped scope is silent.
- Production readiness is not claimed until the owner reviews the private labels and repeated dogfood expands beyond the current 180 indexed sources and deterministic local compiler path.
- Enabling embedding, reranking, or the LoRA router is accepted as an improvement only when the same external holdout protocol improves materially without weakening privacy and no-answer behavior.
