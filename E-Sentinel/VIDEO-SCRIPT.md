# E-Sentinel — Track 2 Video Script (English, ~4:45)

> AMD AI DevMaster Hackathon · Track 2: Private AI Agents
> Goal: show the **full product** (27-panel operations console) + AMD Radeon inference + ReAct agent tool-calling + ablation evidence.
> Setup: `npm run dev` (localhost:3001), AMD_API_KEY configured, 1920×1080.

---

## 0:00–0:25 · Problem & Privacy (voice-over)

> "Enterprise customer-service QA is expensive and unsafe: manual spot-checking misses severe violations, and sending conversations to third-party SaaS risks sensitive data. What if the quality inspector ran entirely on your own AMD GPU?"

**Screen**: terminal showing
- `rocminfo` → AMD gfx1100
- `cat /opt/rocm/.info/version` → ROCm 7.2.1
- `rocm-smi` → GPU status

---

## 0:25–1:30 · QA Hub — Full Quality Case

**Screen**: `/dashboard` → QA hub.

1. **Risk overview**: show the 7-day risk summary and a critical record.
2. **Evidence-first review**: open the record and show the violated rules, source quotes, and conversation bubbles.
3. **Manual QA run**: open “Start QA”, submit the prefilled conversation, and show the score, risk level, and violations.
4. **Governed action**: confirm the risk and show the resulting work-order action.

> "The quality hub combines deterministic rules, retrieval-backed evidence, and model judgment in one governed workflow. Every finding cites the original quote, and every critical result can be reviewed and assigned."

---

## 1:30–2:25 · Operations Console — the Full Product (27 panels)

**Screen**: `/dashboard`, sign in with the seeded administrator account created during setup.

*(One-time setup shown earlier or cut: `supabase/init-seed.sql` in the SQL Editor + `npm run setup:seed-db` — full steps in README → Setup.)*

1. Scroll the **4-group sidebar**: Core Ops / Data Monitoring / Resource Mgmt / System Ops — 27 panels (QA hub, work orders, knowledge base, compliance review, LLM metrics, system audit, cost-savings board, …).
2. **QA hub**: 7-day risk overview (refresh, start a QA run).
3. **Work orders**: open an auto-escalated QA red-line ticket — it carries the complete audit report (score, risk_level, every violation with verbatim quotes, SLA, priority, assignee). This is the **QA → work-order loop**: a detection becomes a governed, assignable action item.

> "E-Sentinel is a full quality-ops platform: 27 panels covering detection, monitoring, knowledge, compliance, and audit. What changes is what's governed: a detected violation becomes a tracked, SLA'd work order, not a one-off report."

---

## 2:25–3:05 · Agent + 5-Layer Safety Architecture

**Screen**: agent tool trace visible:

```
scan_compliance → retrieve_knowledge (RAG retrieval) → check_corrections
  → agent evidence summary → deterministic resolver
```

Show the 5-layer monotonic decision (`finalRisk = max(hardRules, semanticBaseline, validatedAgentEscalation)`):
1. Hard red lines (privacy-extortion / threat / ad-law absolutes) → risk floor `critical`, never downgraded.
2. Semantic LLM judge → the single risk authority (scored, cited JSON).
3. Soft customer signals (refund / 12315 / defect) → context + human-review hints only, never auto-lock high/critical (kills keyword-trap false positives).
4. Agent investigator collects evidence via tools — it has **no risk-write authority**, only escalation proposals backed by verbatim agent-side quotes.
5. Deterministic resolver takes the max — same input, same output.

Then show a human reviewer: who corrected the verdict, timestamp, old → new, feedback version.

> "The agent plans, calls tools, and judges only with evidence. When evidence conflicts or retrieval finds no source, it escalates to a human instead of guessing — fail-closed. Corrections feed back into few-shot memory, so the next similar case judges better."

---

## 3:05–3:50 · Hard Metrics (Ablation, paired)

**Screen**: `evals/results/paired-*.json` + human-gold table

| Variant | Severe Recall | Precision | F1 | FPR | Macro-F1 | Cohen's κ |
|---|---|---|---|---|---|---|
| rule_only (pure keywords) | 0.270 | 0.486 | 0.347 | 0.429 | 0.183 | 0.012 |
| dual (LLM, AMD 35B) | 0.603 | 0.974 | 0.745 | 0.024 | 0.481 | 0.332 |
| **agent (ReAct+tools, AMD 35B)** | **0.635** | 0.952 | **0.762** | 0.048 | **0.502** | **0.350** |

> "On our human-gold set, pure keywords miss 73% of severe violations — semantic risk (implicit overpromises, attitude, un-resolved complaints) simply has no keyword. The single-shot LLM judge reaches recall 0.603 with precision 0.974 (FPR 0.024). **The agent recovers the remaining misses by escalating with verbatim agent-side quotes — it lifts recall to 0.635 with the highest agreement and FPR staying low (0.048).** Evidence, not just judgment, is what restores semantic recall."

*(human-gold 105 cases, Cohen's κ 0.805, severe = high/critical, AMD cloud Qwen3.6-35B-A3B, 0 failed predictions. Local `/workspace/Qwen3-8B` reported separately: dual recall 0.508 → agent 0.921, FPR 0.476, fail-closed.)*

---

## 3:50–4:20 · AMD Optimization & Business Value

**Screen**: local vLLM serving `/workspace/Qwen3-8B` on the AMD instance, `rocm-smi` during a live request, then the real benchmark output (`benchmarks/amd/summary.json`).

> "On AMD Radeon, quality inference runs locally through vLLM with configurable throughput — disable the thinking chain, tune concurrency, use prefix caching. Measured on this instance: interactive P95 ≈ 6.3 seconds, batch throughput ≈ 170 tokens per second at concurrency 8, TTFT ≈ 73 milliseconds, zero request failures. All sensitive content stays on-premise."

**Honest note**: AMD cloud API validated; vLLM local deployment **complete** on the AMD instance (Qwen3-8B, ROCm 7.2.1) — see `docs/AMD-ROCM-DEPLOYMENT-EN.md` for commands and benchmark.

---

## 4:20–4:45 · Boundaries & Reproduce

**Screen**: commands
```bash
npm run eval:goldset:rule-only
npm run eval:goldset -- --variants dual,agent
```

> "Reproduce with one command. The Gold Set is **105 cases** — 40 human-annotated plus 65 synthetic-near-real, double-blind annotated by two independent annotators, human-arbitrated, Cohen's κ 0.805. Local Qwen3-8B results are reported separately from the cloud 35B — we do not merge them into one number. Trustworthy AI admits its limits."

---

## Recording Checklist
- [ ] 1920×1080, browser zoom 100%
- [ ] Terminal shows `rocminfo` (gfx1100) + ROCm version at start
- [ ] Live model mode on AMD (real inference, not fixture)
- [ ] Agent tool trace visible (scan_compliance / retrieve_knowledge)
- [ ] **Dashboard sign-in (preview account) + 4-group sidebar visible**
- [ ] **Work-order panel: QA red-line ticket with full audit report**
- [ ] Ablation table readable
- [ ] No sensitive data in screen captures
