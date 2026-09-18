# Radeon Sentinel — Project Specification

**Track 2 · Development & Local Deployment of Private AI Agents**
AMD AI DevMaster Hackathon · 2026-07

Radeon Sentinel is a privacy-first, locally deployed incident-response agent.
Its core inference runs on an AMD Radeon GPU through ROCm, and it helps an
on-call operator investigate a service incident by retrieving relevant
runbooks, planning a response, calling allow-listed read-only diagnostic
tools, remembering case context, and requiring explicit human approval before
any state-changing action.

> This specification is the English submission document required by Track 2.

---

## 1. Application Scenario and Target Users

### Problem

When production breaks at 3 AM, the on-call engineer's first 15 minutes
decide everything. They repeat the same steps: find the right runbook, read
the right logs, decide if a restart is safe. Today they either do this
manually — slow and error-prone — or paste sensitive logs into a cloud
chatbot, exposing infrastructure secrets to a third party.

Radeon Sentinel is a third option: a **private SRE co-pilot**. It runs the
investigation **entirely on a local AMD Radeon GPU** via ROCm. Core inference
never calls a remote API. **Logs never leave the laptop.**

### Target users

- **On-call operator** — receives an alert, needs a cited diagnosis and a
  safe next action within minutes.
- **Platform / SRE lead** — wants a reproducible audit trail showing which
  evidence supported a remediation and who approved it.
- **Compliance reviewer** — needs proof that no unapproved state-changing
  action was executed and that no data left the local environment.

### Why local inference matters here

Incident logs, service metadata, and runbooks often contain sensitive
infrastructure details. Radeon Sentinel keeps core inference on a local AMD
Radeon GPU via ROCm so that evidence and prompts never leave the operator's
environment. This is the central privacy claim and the reason Track 2 is the
correct fit.

### Three demo scenarios (synthetic)

All data is synthetic and ships in `demo_data/`:

| Scenario | Incident | Demonstrates |
|---|---|---|
| `api_latency` | API saturation / request timeouts | Retrieval + read-only diagnostics → diagnosis |
| `config_drift` | Configuration drift after a deploy | Cited evidence + multi-step plan |
| `dependency_failure` | Upstream dependency failure | Diagnosis + the **approval-gated** remediation path |

`config_drift` is the canonical permission demo: the simulated restart is
**denied by default** and only proceeds when `--approve-remediation` is set.

---

## 2. Architecture

```text
Gradio UI / CLI
   |
Policy Gate ────── Approval checkpoint (state-changing actions)
   |
Agent Orchestrator (RadeonSentinel.investigate)
   |──── Local RAG (LocalRetriever) ── runbooks / logs / service metadata
   |──── Tool Broker (ToolBroker) ───── allow-listed diagnostics + simulated remediation
   |──── Case Memory (CaseMemory) ───── SQLite, per-case isolated, append-only audit
   |
Local Model Server ── open-source model on AMD Radeon GPU + ROCm (vLLM, OpenAI-compatible)
   |
Metrics Collector ── TTFT / tokens per second / VRAM / task success / approval-block rate
```

### Module responsibilities

| Module | File | Role |
|---|---|---|
| Orchestrator | `agent.py` | Runs the investigation workflow: retrieve → diagnose tools → synthesize → plan |
| Retrieval | `retrieval.py` | Local BM25-style runbook search returning cited evidence |
| Tools | `tools.py` | Allow-listed `inspect_service_health`, `search_logs`, `restart_service`; default-deny |
| Memory | `memory.py` | SQLite case memory + append-only audit log, isolated per `case_id` |
| Model | `model.py` | Deterministic offline `MockModelClient` + `OpenAICompatibleModelClient` for the Radeon endpoint |
| Runtime | `runtime.py` | Wiring: constructs the agent from configuration |
| Schemas | `schemas.py` | `AgentResponse`, `Evidence`, `PlanStep`, `ToolResult` dataclasses |
| Interfaces | `cli.py`, `app.py` | CLI entry and optional Gradio UI |

### Design principles

1. **Core inference is local and offline.** No external API is on the scored
   path; the OpenAI-compatible adapter points at a local vLLM server on the
   Radeon GPU.
2. **Tool I/O is structured and auditable.** Every tool call is recorded with
   its arguments, status, and output.
3. **Evidence and inference are recorded separately** so that diagnosis
   correctness can be checked against retrieved sources.
4. **Optimization is backed by A/B data** — "supports ROCm" is never
   substituted for a measured performance result.

---

## 3. Core Capabilities

Track 2 lists five agent capabilities. Each maps to reproducible evidence:

| Capability | Implementation | Evidence |
|---|---|---|
| **Local knowledge retrieval (RAG)** | `LocalRetriever` ranks runbooks and returns `[source] excerpt` citations | `tests/test_retrieval.py`; citations visible in CLI/UI output |
| **Allow-listed tool invocation** | `ToolBroker` exposes exactly three tools; unknown tools are denied | `tests/test_tools.py`; default-deny assertions |
| **Multi-step task planning** | `_build_plan` emits ordered `PlanStep`s with per-step status | plan printed per run; status reflects tool outcomes |
| **Local multi-turn memory** | `CaseMemory` (SQLite) records messages + events, keyed by `case_id` | `tests/test_memory.py`; session resume by `case_id` |
| **Explicit permission & privacy controls** | `restart_service` requires `approved=True`; without it status is `approval_required` and **no simulated action runs** | permission-denied path in `config_drift`; `SECURITY.md` |

### Safety behavior (enforced, not advisory)

- Only `inspect_service_health`, `search_logs`, and `restart_service` are
  allow-listed; anything else is denied.
- The first two tools are **read-only** and operate only on synthetic fixtures.
- `restart_service` requires explicit approval and records only a **simulated**
  action — it never reaches a real service.
- Case memory and the audit log are local SQLite data.
- API keys are read from environment variables and are never placed in model
  prompts or audit output.

---

## 4. Model and Local Deployment

### Serving stack

Core inference is served by **vLLM** (OpenAI-compatible `/chat/completions`)
running on an AMD Radeon GPU through **ROCm**, reached via the
`OpenAICompatibleModelClient`. The deterministic `MockModelClient` is used for
tests and offline development so the workflow is fully reproducible without
credentials.

**Selected model:** `Qwen/Qwen2.5-7B-Instruct` — an open-source model
well-supported on ROCm, leaving headroom for the quantization optimization
bonus. The instance uses **Persistent (PVC) storage** so evidence and model
cache survive instance restarts. Per Track 2 rules, core inference runs on a
**dedicated** Radeon Cloud GPU instance (remote shared APIs are not used for
core functions).

The validated GPU, ROCm, PyTorch, vLLM, model-revision, precision, context
length, serving-command, and reproduction details are recorded in Section 5
and the linked evidence files.

### Configuration

The adapter is configured from environment variables (see `.env.example`):

```bash
export SENTINEL_MODEL_MODE=openai
export MODEL_BASE_URL="http://<radeon-host>:<port>/v1"
export MODEL_API_KEY="<local-key-or-empty>"
export MODEL_NAME="<model-id>"
```

When `SENTINEL_MODEL_MODE` is unset, the agent falls back to the mock model so
that `pytest` and the CLI run anywhere with no credentials.

### Reproduction (offline)

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m pytest                       # 11 tests, offline mock
python -m radeon_sentinel --incident api_latency
python -m radeon_sentinel --incident config_drift --approve-remediation
```

---

## 5. Radeon GPU / ROCm Inference Optimization

This section covers the 40-point Radeon/ROCm rubric item and the optional
20-point optimization bonus. Every value below was measured on the designated
Radeon Cloud environment and is backed by the evidence files in
`docs/evidence/`.

### Environment capture (measured on Radeon Cloud, 2026-08-03)

- **Radeon GPU**: gfx1100 (Navi 31, device id 0x744b) · VRAM **48 GB** (51,522,830,336 B)
- **ROCm**: 7.2.1 · ROCk module 6.16.13 · HSA Runtime 1.18
- **PyTorch** (ROCm build): 2.9.1+gitff65f5b · `torch.cuda.is_available() = True`
- **vLLM**: 0.16.1.dev0+g89a77b108 (V1 engine, Triton Attention backend)
- **Model**: Qwen2.5-7B-Instruct (rev `a09a354`), float16, context length 8192
- **Host**: AMD EPYC 9334 32-Core · 503 GiB RAM

### Baseline metrics (measured, 20 requests, max_tokens=128)

| Metric | Baseline (float16) | Optimized (GPTQ-Int4) |
|---|---|---|
| p50 request latency | 3.45 s | **1.01 s (↓ 70%)** |
| p95 request latency | 3.70 s | **1.21 s (↓ 67%)** |
| Decode throughput | 29.2 tokens/s | **95.6 tokens/s (↑ 227%)** |
| Model size in VRAM | 14.37 GiB | **5.44 GiB (↓ 62%)** |
| Available KV cache | 26.87 GiB / 503,120 tok | **35.84 GiB / 671,152 tok (↑ 33%)** |
| Peak VRAM | 47.3 GB (91%) | 47.6 GB (92%) |
| Diagnostic root-cause hit rate (20 runs) | **100%** | **100%** |
| Diagnostic structure conformance | **100%** | **100%** |
| Completion-token stability (std) | 3.1 | 5.2 |
| Lexical consistency (top-prefix ratio) | 100% | 65% |
| Unapproved state-changing action count | **0** | **0** |

Full A/B report: `docs/optimization-report.md`. Quality evaluation is fully
reproducible offline via `python scripts/quality_eval.py`
(evidence: `docs/evidence/quality-eval.json`).

### Quality trade-off analysis (Int4 vs float16)

To verify that GPTQ-Int4 quantization did not regress diagnostic correctness,
both variants were evaluated on the same 20-run benchmark capture using four
offline quality signals computed over the recorded model outputs.

| Quality metric | float16 | GPTQ-Int4 | Delta |
|---|---:|---:|---:|
| Root-cause hit rate | 100% | 100% | 0 pp |
| Structure conformance (Diagnosis heading) | 100% | 100% | 0 pp |
| Completion tokens (mean) | 102.0 | 98.4 | -3.6 |
| Completion tokens (std) | 3.1 | 5.2 | +2.1 |
| Lexical consistency (top-prefix ratio) | 100% | 65% | -35 pp |

**Interpretation.** Root-cause hit rate and structure conformance are
identical at 100%: every Int4 run still names a valid root-cause family and
preserves the mandated `Diagnosis` heading, so quantization caused **no
semantic regression** on the benchmark incident. The only observable
difference is lexical: float16 repeats near-identical wording on every run
(std 3.1 tokens, single dominant prefix), while Int4 varies the surface
phrasing of the diagnosis ("performance issues" vs "bottlenecks or increased
load") while pointing at the same root cause. In an operational co-pilot this
variation is acceptable — the human reviewer still receives the correct
diagnosis and the same approval gate, and throughput rises 227% (29 -> 96
tokens/s) with no correctness loss.

### Serving command (reproducible)

```bash
# On the Radeon Cloud instance (gfx1100 / ROCm 7.2.1):
export PATH=/opt/venv/bin:$PATH
export HF_ENDPOINT=https://hf-mirror.com   # HuggingFace blocked; use mirror

# The bundled flash_attn is CUDA-only and breaks on ROCm — remove it first:
pip uninstall -y flash-attn

python -m vllm.entrypoints.openai.api_server \
  --model <local-path-to-Qwen2.5-7B-Instruct> \
  --served-model-name Qwen2.5-7B-Instruct \
  --host 0.0.0.0 --port 8000 \
  --gpu-memory-utilization 0.90 \
  --max-model-len 8192 \
  --dtype float16
```

> Evidence: `docs/evidence/rocm-baseline.json` (full 20-run capture) and
> `docs/evidence/vllm-startup.log` (GPU loading, KV cache, CUDA graph capture).

---

## 6. Team and Contribution Statement

- **Participant:** Yichun Deng (solo participant). No team name was set on the
  Luma registration, so the real name is used for the PR title and all
  submission materials, per the official repository instructions.
- **Contributions:**
  - Agent architecture and workflow implementation (RAG, tool broker, case
    memory, permission gate, multi-turn context injection)
  - ROCm deployment on Radeon Cloud (gfx1100), vLLM serving, GPTQ-Int4
    quantization benchmarking and optimization
  - English specification, demo production, poster, and submission materials
- **AMD Developer Program:** member confirmed. Global program site used.
- **License:** project code is Apache-2.0; the Qwen2.5 float16 and official
  GPTQ-Int4 model repositories are also Apache-2.0.

---

## 7. Submission Artifacts

The public Track 2 submission contains:

- complete source code, tests, synthetic fixtures, and reproduction steps;
- this English project specification;
- raw Radeon/ROCm environment and benchmark evidence;
- the float16 versus GPTQ-Int4 optimization report and reproducible quality
  evaluation;
- the 4:45
  [public demo video](https://app.notion.com/p/linguistwantstech/radeon-sentinel-demo-3b234433b7e280db9777d470ba4cfed1?source=copy_link),
  showing live Radeon execution, the full agent workflow, approval gating, and
  bilingual subtitles;
- the English submission poster; and
- the Apache-2.0 project license and security boundary.

The solo participant is **Yichun Deng**. Because no team name was registered,
the legal name is used in the official PR title:
`Track 2, Yichun Deng, Radeon Sentinel`.

---

## Official references

- [Event page](https://luma.com/amd-4dhi)
- [Official contest repository](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07)
- [Radeon Cloud guide](https://github.com/AMD-DEV-CONTEST/Radeon-hackathon-2026-07/tree/main/Radeon-Cloud-User%20Guide)
- [Rules and Conditions](https://docs.google.com/document/d/1TwgwBNUAv8fRNQbkcTZmcRR0__Oi4WMsBfkW38ALZp4/edit?tab=t.0)
