# E1 combined gate — merged main integration review

Packet: `e1-combined-20260726T220422Z-23653d6`

## Outcome

The merged E1 implementation at
`main@23653d6937259e9d9ae93851e5238f8000b45739` passes the combined local
repository, backend, frontend, mock-browser and real loopback integration
checks. This packet is `PASS_REVIEW_PENDING`: it gives the quality owner the
evidence needed to promote or hold T06, but does not self-promote the
milestone.

PR #7 (E1-A) and PR #8 (E1-B) were reviewed and merged before this run. The
combined gate adds no product behavior. It checks that their final contracts,
typed UI states and FastAPI health integration still agree on current `main`.

## Track 2 and submission relevance

- Preserves a reproducible checkpoint for the local Agent Runtime, bounded Tool
  Call policy, durable state, phased RAG contract and typed observation shell.
- Maps to AC-03, AC-04, AC-11, AC-17, AC-18, AC-19, AC-22 and AC-30.
- Supplies E1 integration evidence that can later be harvested into the English
  submission package.
- Does **not** claim M1-M5 product completion, a complete-product Baseline,
  optimization, or a new W7900 run.

## Reproduction results

| Gate | Result |
|---|---|
| Repository static/contract gate | PASS |
| Public QA | PASS — 31/31 |
| Backend contracts / Ruff / pytest | PASS — 46/46 tests |
| Frontend contract provenance | PASS — 15/15 |
| Frontend typecheck / lint / build | PASS |
| Frontend Vitest | PASS — 89/89 |
| Mock Playwright | PASS — 15; one live case skipped by design |
| Current-main FastAPI + live Playwright | PASS — 16/16 |
| Production dependency audit | PASS — 0 vulnerabilities |

The live service bound to `127.0.0.1:8080` and used an ephemeral local database.
Its health response truthfully reported `status=ok`, `database=ok`,
`inference_mode=local_only` and `gpu_viability=NOT_VERIFIED`. The service was
stopped and the temporary database removed after the run.

`npm ci` reported 10 findings in development tooling (3 moderate, 6 high and 1
critical). `npm audit --omit=dev` reported zero production vulnerabilities. No
potentially breaking force update was attempted inside this status-only gate.

## Inherited evidence and exact boundary

The combined local run did not load a model or use a GPU. It references:

- `evidence/milestones/e1-a3-real-w7900/20260725T121500Z/` for the
  quality-reviewed exact-commit W7900/ROCm/Qwen2.5-14B BF16 and Runtime gate;
- `evidence/milestones/E1-B/e1-b-final-contract-20260726T092032Z/` for the
  quality-reviewed exact-contract React/status and browser gate.

The merge from final E1-A commit
`431e1a54040efbe4ccf04daf51b96e3642d233da` to current `main` changes only
E1-B web/evidence paths, not the Agent/vLLM Runtime. This is why the existing
GPU evidence is inherited instead of falsely relabelled. The quality owner may
still require a bounded exact-merge-commit W7900 regression before T06
promotion.

## Decision

- **Result:** `PASS_REVIEW_PENDING`.
- **Promotion authority:** `kinnyuww` / quality owner.
- **Next gate if accepted:** create the bounded E2-A and E2-B Issues for the M1
  Experience Brief vertical slice.
- **Still unverified:** GitHub CI for this follow-up, exact-merge-commit W7900
  rerun, OOM/model-service recovery, performance Baseline/Candidate, and all
  E2+ product behavior.
