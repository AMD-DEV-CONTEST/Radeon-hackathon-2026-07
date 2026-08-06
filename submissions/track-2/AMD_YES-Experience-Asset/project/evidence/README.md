# Public Engineering Evidence Index

This directory is the future Git index for small, sanitized, reproducible
milestone and contest evidence. Follow
[`spec/EVIDENCE_RETENTION.md`](../spec/EVIDENCE_RETENTION.md) before adding any
packet.

Expected layout during implementation:

```text
evidence/
├── README.md
├── templates/
│   ├── manifest.example.json
│   └── summary.template.md
└── milestones/
    └── <checkpoint>/
        └── <run_id>/
            ├── manifest.json
            ├── summary.md
            └── artifacts/
```

Do not put private user data, product databases, raw private prompts/responses,
model weights, credentials, hidden QA, or unrestricted raw logs here. Large raw
working records belong under `/workspace/amd-track2-agent/evidence`; final media
may use approved external storage with a stable reference and checksum recorded
in a sanitized packet.

Copy the files under `templates/` into the named checkpoint/run directory and
replace placeholders. Keep `manifest.json` valid JSON; explain non-applicable
fields in the packet summary rather than deleting reproducibility conditions.

## Prepared execution handoffs

- [`E3_M2_W7900_HANDOFF.md`](../docs/E3_M2_W7900_HANDOFF.md) supplies the
  exact-commit runner, fixed public scenario, pass/fail checks, raw/PVC
  boundary and automatic sanitized packet candidate. Its existence is not
  W7900 evidence; the real run remains `NOT_RUN_DELEGATED` until observed.

## Current packets

- [`performance/stage2-minimal/20260806T124938Z`](performance/stage2-minimal/20260806T124938Z/summary.md)
  — deadline-minimal one-case A0/S0 versus A1/P1 W7900 integration check. Both
  passed; P1 is selected with S0 rollback. The packet explicitly avoids a
  statistical application-performance claim and retains missing peak VRAM as
  `NOT_MEASURED`.

- [`e8-a0-w7900/20260806T122806Z`](milestones/e8-a0-w7900/20260806T122806Z/summary.md)
  — exact-commit integrated A0 functional `PASS` on the W7900 with local
  Qwen3.5-9B: repository/backend/frontend gates, the real M1-M4 browser loop,
  correction-driven invalidation/regeneration, five-route M5 review and private
  HTML/Markdown/JSON delivery passed. It is deliberately not the immutable E8
  performance Baseline or Stage 2 comparison.

- [`e1-risk-hardening/20260724T084655Z`](milestones/e1-risk-hardening/20260724T084655Z/summary.md)
  — PR #9 contract/QA evidence. At that checkpoint repository checks passed,
  while remote SSH, W7900, model, Tool Call, product runtime, and performance
  claims were `NOT VERIFIED`; the later packet below updates only the
  access/device sub-gate.
- [`e1-a3-remote-environment/20260724T093311Z`](milestones/e1-a3-remote-environment/20260724T093311Z/summary.md)
  — sanitized current-pod access/device evidence. Public-key SSH, GPU identity
  and ROCm pass; project restore, PyTorch/vLLM, model, Tool Call, Agent Runtime
  and performance remain `NOT VERIFIED`.
- [`e1-a3-real-w7900/20260725T121500Z`](milestones/e1-a3-real-w7900/20260725T121500Z/summary.md)
  — exact-commit W7900 pass for the frozen 14B BF16 snapshot, localhost vLLM
  structured proposal, Runtime allow/deny/effect, durable failure, terminal and
  restart paths. It retains earlier failed attempts and was accepted during
  PR #7 review; the append-only packet preserves its original review-pending
  decision.
- [`E1-B/e1-b-final-contract-20260726T092032Z`](milestones/E1-B/e1-b-final-contract-20260726T092032Z/summary.md)
  — exact final-contract React/status shell, phased-RAG states and mock/live
  browser evidence accepted during PR #8 review.
- [`e1-combined/20260726T220422Z`](milestones/e1-combined/20260726T220422Z/summary.md)
  — merged-main repository/backend/frontend/live-loopback gate. Local checks
  passed, but quality review later marked T06 `FAIL` because model-failure
  paths could remain non-terminal. The packet is retained as the failed
  observation and is not overwritten.
- [`e1-combined/20260727T050325Z`](milestones/e1-combined/20260727T050325Z/summary.md)
  — retained PR #12 correction packet. Four injected model-failure classes
  now persist explicit terminal results across repository restart; the full
  combined local gate passes. It was the previous
  `FIX_READY_REVIEW_PENDING` candidate and is not overwritten by the current
  GPU rerun.
- [`e1-combined/20260727T055758Z`](milestones/e1-combined/20260727T055758Z/summary.md)
  — accepted PR #12 exact-commit packet. The exact clean `de72a6c` commit
  passes
  frozen-model full SHA-256, W7900/ROCm/vLLM Tool Call and Runtime
  allow/deny/effect/terminal/restart gates, 58 backend tests and Ruff. The
  quality owner accepted the correction and promoted T06 to `PASS`; the
  append-only packet retains its original manifest/summary decision text as
  historical evidence. This run makes no performance claim and is not the E8
  complete-product Baseline.
- [`e2-m1-langgraph-local/20260728T102918Z`](milestones/e2-m1-langgraph-local/20260728T102918Z/summary.md)
  — dirty-tree, non-W7900 E2/M1 checkpoint-2 candidate for the real eight-node
  production LangGraph. Backend, frontend, live browser, public artifact,
  restart/idempotency, runtime-identity and sanitized Trace checks pass. It is
  explicitly not exact-head acceptance evidence; W7900 Serving Reference S1
  and promotion remain assigned to `kinnyuww`.
- [`e2-m1-langgraph-local/20260728T110552Z`](milestones/e2-m1-langgraph-local/20260728T110552Z/summary.md)
  — commit-bound successor for implementation commit `0a30641`. All non-W7900
  repository, backend, frontend, live browser, public artifact, resume,
  idempotency, permission and sanitized Trace checks pass; independent review
  and the `kinnyuww`-owned W7900/S1 checkpoint remain pending.
- [`e3-m2/20260729T103358Z`](milestones/e3-m2/20260729T103358Z/summary.md)
  — exact implementation-commit closure for the PR #20 role-extraction and
  automatic M1-version handoff blockers. Repository, browser/API and sanitized
  E3 evidence pass; the prepared W7900 runner remains `NOT_RUN_DELEGATED`.
- [`e2-m1-w7900/20260801T094735Z`](milestones/e2-m1-w7900/20260801T094735Z/summary.md)
  — independent-review `PASS` on exact clean `main@60503eb`: the W7900/ROCm/
  vLLM 14B serving reference passed 3/3 measured calls, while the real M1 Agent
  slice proved edit/autosave, pause, restart, resume, an inert model Tool Call,
  Runtime allow/execute/verify, current-source retrieval, terminal completion
  and a second restart. It is not an E8 performance Baseline.
- [`e3-m2-w7900/20260801T093210Z`](milestones/e3-m2-w7900/20260801T093210Z/summary.md)
  — independent-review `PASS` on the same exact clean commit and local 14B
  stack: full model hash, native Tool Call, Runtime closure, source-linked M2
  semantic extraction, and correction-driven invalidation/regeneration passed.
  It is compatibility/functional evidence and makes no optimization claim.
