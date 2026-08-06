# Case Log: Complete production RAG retrieval layers

## Intent
Goal: Implement FTS5 persistence, parent-child context retrieval, optional local cross-encoder reranking, and scanned PDF OCR without breaking existing local privacy and memory guarantees.

Success criteria:
- FTS5, parent-child retrieval, optional reranking, and OCR remain available.
- Sensitive Chinese requests route to the redacted scanner and raw secrets do not reach model/UI/export output.
- Real workspaces reject deterministic fallback; only the synthetic demo can use it.
- Malformed local-model JSON and parser/OCR failures are visible and do not create false verdicts.
- Existing retrieval and championship corpus checks remain green.

Risk: medium (user-facing behavior, data handling, local model integration)

## Context
Files read:
- docs/PRD.md
- docs/product.md
- docs/system.md
- AGENTS.md
- core.py
- app.py
- tests/test_core.py

SSOT used:
- docs/PRD.md
- docs/product.md
- docs/system.md

## Gates
First-principles check:
- A private workspace must fail closed: no public model endpoint, no raw secret output, no unrelated fallback verdict.

Assumptions:
- Optional OCR and cross-encoder packages may be absent; their disabled state must be visible.

Adversarial findings:
- Chinese credential wording, duplicate filenames, public endpoints, malformed JSON, OCR failure, and partial re-indexing were tested.

Edge cases:
- Empty OCR pages, same-name files in different folders, broken reranker, and missing live judge.

Rejected options:
- Keeping a generic fallback enabled for arbitrary private claims.

## Explore Card
Mode: explore
Why: Implement FTS5 persistence, parent-child context retrieval, optional local cross-encoder reranking, and scanned PDF OCR without breaking existing local privacy and memory guarantees.
Acceptance:
- {"criterion": "Prototype can be exercised locally", "evidence": "Local smoke check or direct manual exercise", "prohibited": "Do not present a prototype or fixture as production-ready"}
Boundary:
- No production release or irreversible data change


## Changes
- tests/test_core.py
- core.py
- app.py
- README.md
- requirements.txt
- docs/system.md
- scripts/championship_check.py

## Verification
Required evidence level: 1
Achieved evidence level: 1

Commands:
- python -m unittest discover -s tests -v
- python -m py_compile core.py app.py scripts/championship_check.py tests/test_core.py
- python scripts/championship_check.py --output championship_results_local.json

Results:
- python -m unittest discover -s tests -v
- python -m py_compile core.py app.py tests/test_core.py
- python -m unittest discover -s tests -v
- python -m py_compile core.py app.py scripts/championship_check.py tests/test_core.py
- python scripts/championship_check.py: 23 corpus files, 30 chunks, sensitive locator redacted, final PPT ranked first, FTS5 active.

## Surprises
- The local Windows environment does not have Streamlit installed, so the UI import was not executable locally; syntax checks passed and the Radeon environment remains the required UI verification target.

## Reusable Lessons
- Durable FTS5 works best as a rebuildable acceleration layer beside the JSON evidence ledger; parent-child context and optional local-only quality models preserve graceful degradation and privacy.

## Follow-ups
- Run the live vLLM/embedding/OCR/reranker path on Radeon Cloud before recording the final video.
