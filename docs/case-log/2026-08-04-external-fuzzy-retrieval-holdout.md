# Case Log: external-fuzzy-retrieval-holdout

## Intent
Goal: Evaluate ClaimCourt against public out-of-distribution retrieval corpora and issue an evidence-backed project-level verdict

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
- None

Assumptions:
- None

Adversarial findings:
- None

Edge cases:
- None

Rejected options:
- None

## Explore Card
Mode: explore
Why: Evaluate ClaimCourt against public out-of-distribution retrieval corpora and issue an evidence-backed project-level verdict
Acceptance:
- {"criterion": "Prototype can be exercised locally", "evidence": "Local smoke check or direct manual exercise", "prohibited": "Do not present a prototype or fixture as production-ready"}
Boundary:
- No production release or irreversible data change


## Changes
- .gitignore
- .research/20260804-fuzzy-retrieval-holdout-a7c1/run_benchmark.py
- .research/20260804-fuzzy-retrieval-holdout-a7c1/final_report.md

## Verification
Required evidence level: 0
Achieved evidence level: 0

Commands:
- python -m py_compile .research/20260804-fuzzy-retrieval-holdout-a7c1/run_benchmark.py
- run_benchmark.py --datasets scifact
- run_benchmark.py --datasets bright
- run_benchmark.py --datasets t2

Results:
- SciFact hybrid Top1 0.5533 vs BM25 0.5333; BRIGHT hybrid Top1 0.0971 vs 0.0874; T2 hybrid Top1 0.5960 vs 0.5859.

## Surprises
- None

## Reusable Lessons
- Synthetic intent benchmarks can overstate semantic understanding; external holdouts must separate hybrid retrieval gains from actual intent compilation.

## Follow-ups
- Enable local Radeon embedding and intent router, then rerun identical holdout protocol.
- Build 200-500 query private-file-style blind evaluation set.
