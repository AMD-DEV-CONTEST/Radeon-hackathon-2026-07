# Case Log: Fuzzy intent compiler

## Intent

Move ClaimCourt's core value from generic local RAG to a measurable compiler that turns incomplete human recollections into a safe, structured search plan.

## Changes

- Extended `IntentPlan` with causal/temporal relations, episodic-memory signals, clarification state, and compiler provenance.
- Added a local query-only Qwen/LoRA compiler with strict JSON validation and deterministic fallback.
- Prevented the learned router from broadening ordinary document queries into sensitive-secret scans.
- Added semantic expansions for operating systems, migrations, runbooks, signed addenda, support exceptions, and Chinese paraphrases.
- Added explicit signed-vs-draft version selection inside file families.
- Added 64 synthetic intent SFT examples and a dedicated `claimcourt_intent_sft.jsonl` dataset with no private text or raw secrets.
- Added `scripts/fuzzy_retrieval_check.py` with an eight-query hard-negative benchmark and raw BM25 comparison.

## Verification

- 45 unit tests passed.
- Fuzzy benchmark: intent-aware Top-1 `1.0`, Recall@3 `1.0`; raw BM25 Top-1 `0.625`, Recall@3 `0.75`.
- Championship gate: 23 files, 30 chunks, FTS5 active, sensitive output redacted, fuzzy gate passed.
- Streamlit AppTest: zero page exceptions; local judge failure retained eight retrieved evidence items.
- Intent SFT: 64 rows, schema-valid, no `ghp_` or `password=` values.

## Limits

- The benchmark is synthetic and small; it demonstrates a regression gate, not universal language understanding.
- The LoRA adapter must still be trained/served on Radeon Cloud and evaluated with `--router-endpoint` before the video claims learned routing.
