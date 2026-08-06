# E-Sentinel — Private AI Quality Assurance Agent on AMD Radeon/ROCm

> AMD AI DevMaster Hackathon · Track 2: Development & Local Deployment of Private AI Agents
> One-line identity: **An AI quality auditor that explains decisions, admits uncertainty, and turns human corrections into governed improvements.**

---

## 0. Judging-Criteria Mapping

> Every claim is labelled with its scoring bucket (**Functional-60** or **AMD/ROCm-40**) and verification state: `measured` means recorded data, `verified` means the path was exercised, and `present` means the implementation is in this repository. Every number links to reproducible evidence in this repository.

### Functional value (60)

| Claim | Bucket | State | Evidence |
|---|---|---|---|
| Customer-service QA agent: full-conversation coverage with per-finding evidence | F | verified | Complete flow in `src/app/api/qa/evaluate/route.ts` |
| **Human-gold evaluation set: 105 double-blind cases with human arbitration** (κ=0.805, checksum) | F | measured | `evals/configs/gold-set-human-v1.json` + `validate-dataset.mjs` |
| **Paired ablation: evidence-driven agent recovers semantic misses** (cloud 35B recall 0.603→0.635; local 8B 0.508→0.921) | F | measured | `evals/results/paired-recomputed-*.json` |
| **Stability: agent × 3 independent runs, 92.9% severe-decision consistency** (deterministic architecture preserves the safety outcome) | F | measured | `evals/results/ablation-1785835668348.json` |
| **C4 three-way retrieval and cross-tenant isolation: 0/50 leaks** (agent with retrieval vs tool-free dual comparison; tested configurations have similar end-to-end results) | F | measured | `docs/C4-RETRIEVAL-ABLATION-EN.md` |
| **Five-layer monotonic safety architecture** (agent has no risk-write authority; fail-closed) | F | verified | `evaluate-core.ts`, `resolveFinalRisk`, and eight architecture-invariant tests |
| ReAct agent with three tools (`scan_compliance` / `retrieve_knowledge` / `check_corrections`) | F | verified | `src/lib/agent/` plus recorded Hermes tool-call evidence |
| Human correction → few-shot improvement loop | F | verified | `few-shot.ts` + `check_corrections` |
| Passing Jest suite and clean TypeScript check | F | measured | `npm test` and `npm run typecheck` |

### AMD / ROCm optimization (40)

| Claim | Bucket | State | Evidence |
|---|---|---|---|
| **End-to-end local deployment**: vLLM 0.26.0+rocm723 serves Qwen3-8B on gfx1100 (Radeon PRO W7900D, ROCm 7.2.1) | R | verified | Evidence package in `benchmarks/amd/` |
| **Measured inference optimization**: TTFT 73 ms / interactive P50 4.2 s / batch 170 tok/s / 7.63× throughput from concurrency 1→8 | R | measured | `benchmarks/amd/summary.json` + `concurrency-*.json` |
| **Controlled experiments**: thinking on/off gives 2–3× end-to-end change; prefix caching reduces shared-prefix latency | R | measured | §4.3 optimization table + AMD control data |
| Hermes tool calling (local 8B agent calls `retrieve_knowledge`) | R | verified | `benchmarks/amd/tool-call-trace.json` + local ablation with `agent tools=retrieve_knowledge` |
| AMD cloud 35B paired ablation with zero failed predictions | R | measured | `paired-recomputed-1785820763232.json` |

---

## 1. Application Scenario

Enterprise customer-service quality inspection (QA) is expensive and error-prone:

- **Manual spot-checking covers only ~20%** of conversations, missing severe violations.
- **Sensitive customer data** (bank cards, identity, purchase history) cannot be sent to third-party SaaS for full-coverage review.
- **LLM-only judges hallucinate** without source grounding; keyword-only rules miss semantic risk.

**E-Sentinel solves this**: a **fully private, evidence-grounded QA agent** running locally on AMD Radeon GPU. It inspects **100% of customer-service conversations**, detects violations with cited evidence, escalates to human review when uncertain, and **learns from human corrections** — all without data leaving the enterprise.

### Guided walkthrough (3-5 min)
1. Obvious abuse → value is instantly legible.
2. An implicit overpromise ("today guaranteed") → shows why keyword rules miss semantic risk.
3. Keyword vs full-system comparison → AI contribution is inspectable.
4. A privacy leak → safety enforcement is demonstrated.
5. A good reply → proves the system does not over-block.
6. Insufficient context → uncertainty is routed to human review.

---

## 2. Agent Architecture

```
Customer conversation
        │
        ▼
┌─────────────────────────────────────────────────────┐
│  E-Sentinel Quality Agent (Next.js + TypeScript)      │
│                                                       │
│  ┌─────────────┐   ┌──────────────┐   ┌───────────┐  │
│  │ Rule Engine │   │  LLM Judge   │   │ ReAct Loop│  │
│  │ (determin.) │──▶│ (AMD Qwen)   │◀──│ + Tools   │  │
│  └──────┬──────┘   └──────┬───────┘   └─────┬─────┘  │
│         │                 │                 │        │
│         │   scan_compliance  │   retrieve_knowledge  │
│         │                 │   check_corrections      │
│         ▼                 ▼                 ▼        │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Risk Decision: block / review / warn / pass    │ │
│  │  + evidence (source quotes, cited knowledge)    │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │                            │
│  Human correction ──────▶ learning loop (few-shot)   │
└─────────────────────────┼────────────────────────────┘
                          ▼
              Feishu alert / work order / audit log
```

**Key design decisions — a 5-layer monotonic safety architecture (ADR-0003):**
```
finalRisk = max( hard-rule floor, semantic baseline, validated agent escalation )
```
1. **Hard rules (deterministic, cannot be downgraded)**: ad-law absolutes (full text) + privacy-extortion/threat/abuse red lines (agent lines only) → risk floor `critical`.
2. **Semantic baseline (LLM judge)**: 5-dimension quality scoring, JSON verdict with cited quotes — the **single risk authority**.
3. **Soft signals (customer-side keywords)**: refund/12315/defect/logistics flags produce context + human-review hints, **never** directly set high/critical (fixes keyword-trap false positives).
4. **Agent investigator (tools)**: ReAct loop collects evidence (compliance scan / RAG retrieval / correction precedents). The agent has **no `finalRisk` write authority** — it can only propose an escalation backed by verbatim agent-side violation quotes; no source → no escalation → human review (fail-closed).
5. **Deterministic resolver**: takes the max of the three, pure function, same input → same output.

The paired ablation (shared baseline snapshot) proves the agent adds **auditability and evidence completeness, not detection recall** — the baseline already catches all severe violations; the agent's value is *explainable, cited* decisions.
- **Evidence grounding**: every violation cites the original conversation quote; knowledge-based findings cite retrieved sources; no source → no judgment → human review (fail-closed).

### Tools (function calling, via Hermes parser on Qwen)
| Tool | Purpose |
|---|---|
| `scan_compliance` | Deterministic compliance scan (ad-law red lines, banned words, risk level) |
| `retrieve_knowledge` | Retrieves enterprise policy/product knowledge (RAG retrieval) with cited sources |
| `check_corrections` | Retrieves past human-corrected cases as precedent (few-shot learning) |

---

## 3. Core Capabilities

| Capability | Status | Evidence |
|---|---|---|
| LLM-as-a-Judge (5-dimension, JSON, cited) | Prod | human-gold 105-case paired ablation, dual-track |
| Rule vs LLM dual gate | Prod | keyword elevation "only-up" |
| ReAct agent with tool calling | Prod | `src/lib/agent/` + Hermes tool-calling verified on AMD Qwen |
| RAG policy retrieval (RAG) | Prod | `retrieve_knowledge` tool + Recall@5 0.733 retrieval ablation |
| Few-shot human-correction loop | Prod | `check_corrections` + prompt injection |
| Risk grading (low→critical) + escalation | Prod | block/review/warn/pass + Feishu |
| Auto work-order + audit trail | Prod | `quality_reports` / evidence events |
| Multi-platform adapters | Prod | Feishu / Tmall / JD-ready |

---

## 4. Model & Local Deployment on AMD Radeon

### 4.1 Runtime (validated on AMD Radeon GPU Cloud)

E-Sentinel's `callLLM` (unified provider) runs quality inference on **Qwen3.6-35B-A3B** served by the **AMD Radeon GPU Cloud** (gfx1100, ROCm 7.2.1), OpenAI-compatible.

Verified end-to-end: `amd-provider.integration.test.ts` + 20-case ablation produced real risk verdicts.

### 4.2 vLLM local deployment (complete on AMD instance)

| Model | Total params | FP16 VRAM | gfx1100 48GB |
|---|---|---|---|
| Qwen3-8B | 8B | ~16GB | ✅ fits |
| Qwen3-14B | 14B | ~28GB | ✅ fits |
| Qwen3.6-35B-A3B | 35B | ~70GB | ❌ (use cloud API) |

```bash
# ROCm vLLM (⚠️ NOT plain `pip install vllm`, which resolves the CUDA build)
python3 -m venv /opt/vllm-env
UV_HTTP_TIMEOUT=600 uv pip install "vllm==0.26.0+rocm723" \
  --extra-index-url https://wheels.vllm.ai/rocm/

vllm serve /workspace/Qwen3-8B \
  --host 0.0.0.0 --port 8000 --dtype float16 \
  --max-model-len 8192 --gpu-memory-utilization 0.88 \
  --max-num-seqs 8 --enable-prefix-caching \
  --enable-auto-tool-choice --tool-call-parser hermes
```

Then point `AMD_API_URL` to the local endpoint (OpenAI-compatible, no code change).

Status (2026-08-04): **complete** — vLLM 0.26.0+rocm723 installed, `/workspace/Qwen3-8B` served on AMD gfx1100 (Radeon PRO W7900D, ROCm 7.2.1, VRAM 87%), and Hermes tool calling verified. Benchmarks: TTFT ~73 ms, interactive E2E P50 ~4.2 s, batch ~170 tok/s — see `benchmarks/amd/summary.json` and `docs/AMD-ROCM-DEPLOYMENT-EN.md`.

### 4.3 Inference-speed optimizations (with on/off control experiments)

> Every optimization has an on/off controlled measurement using the same prompt and hardware. See `benchmarks/amd/ablation-control.json` for the raw data.

| Optimization | Problem | Solution | Measured gain |
|---|---|---|---|
| Disable thinking chain | cloud API returns content in `reasoning`, doubling tokens | `enable_thinking=false` | **3.20×** E2E (P50 5.01s→1.57s, token 200→22, −91%) |
| Prefix caching | multi-turn recompute | `--enable-prefix-caching` | **1.49×** (cold 3.14s → hot 2.11s on shared prefix) |
| Quantization/model choice | 35B doesn't fit 48GB | GPTQ W4A16 (Qwen3-8B) | **weights 16GB→5.7GB (−64%), tok/s +62~79%, single-request E2E −60%** (method caveats in `training/QUANTIZATION-EN.md`) |
| Concurrency tuning | low aggregate throughput | concurrency 1→8 (max-num-seqs 8) | ~170 tok/s aggregate, 0 failures |
| Context length | 262K wastes KV cache | use 8192 | more VRAM for concurrency |

---

## 5. Evaluation: Ablation Study (Gold Set)

**Gold Set**: 105 conversations (40 human-annotated + 65 synthetic-near-real, stratified matrix over 13 scenario types), double-blind annotated by two independent channels (ann-a anti-miss / ann-b anti-FP) + human arbitration on disagreements (2.5% on base 40; 13.3% on synthetic borderline cases). Labels frozen via `finalize-gold-set.mjs` + `validate-dataset.mjs` (Cohen's κ = 0.805, Wilson CI, checksums).

**Paired ablation (shared baseline snapshot)** — Dual and Agent reuse the same `runJudge` baseline output, so any difference is attributable to the tool layer (evidence retrieval + verbatim-quote escalation), not LLM sampling. Severe = `risk_level ∈ {high, critical}` (matches gold annotation). 0 failed predictions.

**AMD cloud Qwen3.6-35B-A3B** (`evals/results/paired-recomputed-1785820763232.json`):

| Variant | Severe Recall | Precision | F1 | FPR | Macro-F1(risk) | Cohen's κ |
|---|---|---|---|---|---|---|
| rule_only (pure keywords, offline) | 0.270 | 0.486 | 0.347 | 0.429 | 0.183 | 0.012 |
| dual (LLM, single-shot) | 0.603 | 0.974 | 0.745 | 0.024 | 0.481 | 0.332 |
| **agent (ReAct+tools)** | **0.635** | 0.952 | **0.762** | 0.048 | **0.502** | **0.350** |

**What this proves (honest, human-gold):**
- **rule_only (pure keywords) is weak: recall 0.270 (misses 73% of severe violations) and FPR 0.429** — keyword rules cannot detect semantic risk (implicit overpromises, attitude, un-resolved complaints).
- **dual (single-shot LLM judge) reaches recall 0.603 with precision 0.974 (FPR 0.024)** — semantic judgment rarely false-alarms but under-recalls subtle violations.
- **agent recovers real semantic misses via verbatim-quote evidence (recall 0.603→0.635, κ 0.350, FPR stays low 0.048)** — escalates 2 violations the plain judge missed (case-030 dismissive close; case-050 refused verification), each backed by a verbatim agent-side quote and routed to human review on `knowledge=insufficient` (fail-closed).

**AMD local `/workspace/Qwen3-8B` (vLLM, ROCm 7.2.1), reported separately** (`paired-recomputed-1785820763279.json`):

| Variant | Severe Recall | Precision | F1 | FPR | Cohen's κ |
|---|---|---|---|---|---|
| dual (LLM, single-shot) | 0.508 | 0.941 | 0.660 | 0.048 | 0.407 |
| **agent (ReAct+tools)** | **0.921** | 0.744 | **0.823** | 0.476 | **0.457** |

- Local 8B single-shot recall 0.508 — the 8B model under-recognizes subtle semantic violations;
- **Local 8B agent recovers 26 misses (recall 0.508→0.921) via evidence, at the cost of FPR 0.476** (the 8B agent over-escalates 18 non-severe cases);
- Recovered cases pass `escalationEvidence` verbatim-quote verification (e.g. case-001 dismissive phrasing, case-009 refused verification), and `knowledge=insufficient` correctly triggers human review (fail-closed).
- **Consistent across models**: agent recovers misses and raises κ in both; the difference is FPR — cloud 35B is precise (0.048), local 8B is aggressive (0.476). Reported separately, never merged.

**RAG retrieval ablation (RAG, C4):** Recall@5 = **0.733**, MRR = **0.733**, P50/P95 latency = **538/1575 ms**; policy queries → **100% no-source** → routed to human review (fail-closed). Full report: `evals/results/retrieval-ablation-*.json`.

**Stability (agent × 3 no-cache repeats, AMD cloud 35B, 2026-08-04)** — `evals/results/ablation-1785835668348.json`:
- Severe Recall min/max/avg = **0.644 / 0.667 / 0.655**; Severe F1 = 0.776 / 0.785 / 0.782
- exact-risk consistency **87.8%** · severe on/off **92.9%** · tool-path consistency **90.8%**
- **Conclusion**: the agent's exploration (tool path) may vary, but the safety verdict stays stable because the deterministic architecture (hard rules + monotonic resolver) is the final authority — an empirical property of the 5-layer design.

**C4 three-way retrieval + cross-tenant isolation (2026-08-04)** — `evals/results/retrieval-ablation-3way-*.json` + `docs/C4-RETRIEVAL-ABLATION-EN.md`:

| Path | Recall@5 | MRR | no-source rate | P50 | Cross-tenant leaks |
|---|---|---|---|---|---|
| pgvector (Supabase, vector_only) | 0.4 | 0.4 | 0 | 504ms | **0 / 50** |
| RAG (/api/eval/retrieve) | 0.5 | 0.5 | 0.4 | 545ms | — |
| no-RAG baseline | N/A | N/A | 1.0 | — | N/A |

End-to-end on human-gold (local stock 8B): no-RAG (dual) Recall 0.508/FPR 0.048 → RAG agent 0.921/0.476 → pgvector agent 0.905/0.429/κ 0.495. **Caveat: the no-RAG row used the tool-less dual variant while retrieval rows used the ReAct agent, so this is not an isolated causal claim about retrieval.** Within this 105-case end-to-end run, the two tested corpora/backends (pgvector Recall@5 0.4, 21 docs vs RAG 0.5, 335 docs) yield close Agent metrics (F1 0.826 vs 0.823, κ 0.495 vs 0.457) — evidence that these tested configurations are relatively insensitive to retrieval quality, not a general proof about retrievers.

**LoRA fine-tuning — two experiments rejected by the quality gate (2026-08-04)** — full record `training/FAILED-TUNED-LOG-EN.md`:
- **v1** (504 template samples, lr 5e-5/2 epochs): human-gold regression (agent Recall 0.921→0.714, FPR 0.476→0.738) → **REJECTED**.
- **B1** (798 samples w/ tool-context + rehearsal + counterfactual + hard-negatives + stock-error repair, lr 2e-5/1 epoch): independent dev agent FPR 0.836 vs stock 0.623 on the same 266-dev → **REJECTED**.
- **Human-gold integrity**: the 105-case gold set was never used as training examples or generation seeds; B1 checkpoint selection used the independent 266-case dev set. The v1 aggregate result did inform the decision to run B1, so the set was not an untouched model-selection holdout after v1 — recorded honestly in `training/FAILED-TUNED-LOG-EN.md`.
- **Production retains stock Qwen3-8B.** We report both negative results rather than cherry-picking — the gate exists to reject worse models, and we respect it.

**Reproduce (one command):**
```bash
node scripts/retrieval-ablation.mjs                     # RAG retrieval metrics
node scripts/evaluate-goldset.mjs --goldsets evals/configs/gold-set-human-v1.json --variants rule_only,dual,agent --paired --base-url <amd-server> --api-key <key>   # human-gold paired ablation (AMD)
```

---

## 6. Submission Artifacts

| Artifact | Path |
|---|---|
| Specification | `SPECIFICATION.md` (this file) |
| AMD deployment plan | `docs/AMD-ROCM-DEPLOYMENT-EN.md` |
| Source code | `src/lib/agent/`, `src/lib/qa/`, `src/lib/rag-client.ts` |
| Gold Set + ablation script | `evals/configs/`, `scripts/evaluate-goldset.mjs` |
| Guided walkthrough | `CONTEST.md`, `VIDEO-SCRIPT.md` |
| Tests | 274 passing (Jest), incl. AMD integration |

## 7. Honest Boundaries
- Gold Set is **human-annotated + human-arbitrated** (40 base + 65 synthetic-near-real). Synthetic cases are honestly labeled `synthetic-near-real` in provenance; they are not real production conversations.
- AMD **free API validated** (Qwen3.6-35B-A3B) **and vLLM local deployment complete** on the shared AMD instance (`/workspace/Qwen3-8B`, ROCm 7.2.1). Local 8B results are reported separately from the cloud 35B; the paired-ablation table below is produced on the AMD cloud 35B endpoint.
- Local Qwen3-8B results, once available, are **reported separately from cloud 35B** — we do not merge them into one "model score".
- Human feedback drives auditable case memory and prompt improvement; we do **not** claim online model training.
- **LoRA fine-tuning attempted twice and rejected** by the frozen quality gate (see §5) — production keeps the stock model; the negative results are disclosed as a reproducible record, proving the gate rejects worse models and we do not cherry-pick.
- **Quantization is treated as a validation experiment, not an assumed win**: we report correctness and performance gates before claiming any benefit. Claims are limited to model-weight size (−64%) and output throughput (tok/s +62~79%); peak VRAM was not separately measured, and the latency figure is single-request end-to-end (not first-token latency) — see §4.3 / `training/QUANTIZATION-EN.md`.
