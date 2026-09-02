# C4 Three-Way Retrieval Comparison + Cross-Tenant Isolation Report

> Date: 2026-08-04 · Submission: AMD DevMaster Track 2 · Purpose: to record the end-to-end comparison of the Agent+retrieval path vs. the no-tools Dual baseline, the three-way comparison at the retrieval layer, and the cross-tenant isolation test (causal conclusions in Section 3 boundaries)
> Raw data: `evals/results/retrieval-ablation-3way-1785847621641.json` (retrieval layer) · `evals/results/ablation-1785850202551.md` (pgvector end-to-end) · paired-recomputed (RAG end-to-end) · ablation (dual end-to-end)

## 1. Three-Way Comparison at the Retrieval Layer (unified set of 10 queries)

| Path | Recall@5 | MRR | No-source rate | P50 latency | Cross-tenant leakage |
|---|---|---|---|---|---|
| **pgvector** (Supabase vector_only) | 0.4 | 0.4 | 0 | 504ms | **0 / 50 rows** |
| **RAG** (/api/eval/retrieve) | 0.5 | 0.5 | 0.4 | 545ms | — |
| **No RAG** (no-retrieval baseline) | N/A | N/A | 1.0 | — | N/A |

> Note: The two corpora differ (Supabase: 21 policy/camera entries; RAG: Gemini 335 camera parameters). Recall@5 reflects the corpus-coverage difference and is reported as-is.
> **Fix log**: The original embeddings in Supabase `knowledge_entries` were all null (no vectors were generated at ingestion) → regenerated (trigram-hash, 1536-dim) and inserted tenant-b isolation test data.

## 2. End-to-End QA Comparison (frozen human-gold, 105 cases, local stock Qwen3-8B)

| Path | Severe Recall | Precision | F1 | FPR | Cohen's κ |
|---|---|---|---|---|---|
| **No RAG** (dual, no tools) | 0.508 | 0.941 | 0.660 | 0.048 | 0.407 |
| **RAG** (agent) | 0.921 | 0.744 | 0.823 | 0.476 | 0.457 |
| **pgvector** (agent) | 0.905 | 0.760 | 0.826 | 0.429 | 0.495 |

## 3. Conclusions (honest, causal boundaries)

1. **The Agent+retrieval path markedly improves severe-violation recall relative to the no-tools Dual baseline**: No RAG (Dual) 0.508 → Agent+retrieval 0.90+, at the cost of FPR rising from 0.048 to 0.43–0.48 — improving recall introduces false positives; this is not a free lunch. **However, the experiment simultaneously changed both the Agent architecture and the retrieval conditions** (the no-RAG path runs a single-shot Dual; the retrieval paths run a ReAct Agent with tool calls and a different prompt), so this improvement **cannot be attributed to "retrieval augmentation" alone** — it is an observed result of the combination of Agent architecture and retrieval.
2. **The end-to-end results are relatively insensitive to these two tested configurations**: pgvector (Recall@5 0.4, 21-entry corpus) and RAG (Recall@5 0.5, 335-entry corpus) **differ in both corpus and retrieval backend, so the two retrieval algorithms cannot be compared in merit on this basis**; in this 105-case end-to-end evaluation, the Agent metrics for the two configurations are close (F1 0.826 vs 0.823, κ 0.495 vs 0.457).
3. **Cross-tenant isolation (scoped statement)**: **0 cross-tenant leakage** cases were observed in the 50 returned-row isolation test in this run (pgvector tenant isolation, with tenant-b data as a control). This is an observation under this test configuration and is not elevated to "enterprise security proven" in a general sense.

## 4. Reproduction

```bash
# Three-way comparison at the retrieval layer
node --env-file=.env.local scripts/retrieval-ablation-3way.mjs
# pgvector end-to-end (after starting the QA service with QA_RETRIEVAL_PROVIDER=pgvector)
node scripts/evaluate-goldset.mjs --goldsets evals/configs/gold-set-human-v1.json --variants rule_only,agent --base-url http://localhost:3004
```
