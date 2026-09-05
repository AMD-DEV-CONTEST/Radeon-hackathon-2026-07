# W7900 Serving Benchmark — Engineering Plan

## Status and authority

- Work package: `PERF-SERVING-SCREEN-V1`
- Requirement status: `APPROVED`
- Engineering status: `DESIGN HARDENED / IMPLEMENTATION NOT STARTED`
- Approved: 2026-08-03 AEST
- Parent requirement: [`CURRENT_ITERATION.md`](CURRENT_ITERATION.md)
- Public metric contract: [`../team-alignment/BENCHMARK_PLAN.md`](../team-alignment/BENCHMARK_PLAN.md)
- Evidence policy: [`../../spec/EVIDENCE_RETENTION.md`](../../spec/EVIDENCE_RETENTION.md)
- Track 2 relevance: direct. This work produces reproducible W7900/ROCm/vLLM
  optimization evidence for the technical report, comparison charts, and demo.
- Submission impact: exact environment, model, workload, latency, throughput,
  VRAM, quality, stability, failure, and rollback evidence are retained instead
  of reconstructing optimization claims at submission time.

This plan authorizes implementation of the benchmark harness and execution of
the Stage 1 service screen. It does not authorize changing the product model,
promoting a profile into the application, calling a remote judge with private
data, exposing a Pod service publicly, or rewriting historical evidence.

## 1. Decision

Performance selection uses two independent baselines:

1. `S0 Serving Baseline` freezes the known-good Qwen2.5-14B-Instruct BF16
   service on one Radeon PRO W7900. Stage 1 compares serving profiles without
   requiring the complete product.
2. `A0 Application Baseline` freezes the first accepted complete Agent on the
   selected code commit and business fixture set. Stage 2 compares the three
   Stage 1 finalists inside the same application.

`S0` answers which profiles are viable and efficient. It cannot establish that
a profile is the best product choice. Only Stage 2 may recommend the submitted
application profile. If no Candidate produces a useful, quality-safe gain, the
known-good baseline remains the correct result.

The workload preference is:

- concurrency 1: primary single-user interactive path;
- concurrency 2: secondary background/concurrent path; and
- concurrency 4: diagnostic stress and safe-degradation evidence, not a reason
  to trade away interactive quality.

## 2. Frozen identities

Before any score is viewed, the implementation must materialize and hash:

- `benchmark_contract_version = serving-screen-v1`;
- exact Git commit of the harness;
- model source, immutable revision, license, file hashes and tokenizer;
- Pod/container, GPU, CPU/RAM quota, driver, ROCm, PyTorch and vLLM identity;
- complete vLLM and generation arguments;
- every profile definition;
- workload JSONL and expected deterministic checks;
- warm-up, sample count, concurrency, timeout, seed and ordering method;
- scorer source/version and external-judge rubric/prompt hash, when used; and
- output/evidence directory and rollback command.

The initial `S0` identity is the accepted repository profile:

| Field | Frozen value |
|---|---|
| Model | `Qwen/Qwen2.5-14B-Instruct` |
| Model revision | `3957bf39753cf01f98f6560295c4811c2b5df001` |
| Dtype / quantization | BF16 / none |
| Max model length | 8192 |
| GPU memory utilization | 0.82 |
| Max sequences | 4 |
| Tool parser | Hermes, automatic tool choice enabled |
| Bind address | `127.0.0.1` |
| Hardware | one AMD Radeon PRO W7900, ROCm path |

The implementation must read these values from versioned profiles rather than
duplicating them as hidden runner defaults. An unavailable or changed field is
a new contract version, not an in-place correction.

## 3. Stage 1 scope

### 3.1 Frozen service workloads

Only public, synthetic, or explicitly de-identified material is allowed. Four
business-shaped service workloads represent the model calls that this product
actually makes:

| ID | Purpose | Input budget | Output budget | Required output |
|---|---|---:|---:|---|
| `W1-interactive` | concise clarification and next-step proposal | 1K–2K | 128–256 | useful, grounded short response |
| `W2-extraction` | structured critical-moment/evidence extraction | 3K–4K | 256–512 | schema-valid JSON or tool proposal |
| `W3-knowledge-card` | experience synthesis with uncertainty/boundaries | 5K–6K | 640–1024 | complete structured Knowledge Card draft |
| `W4-long-context` | near-capacity context handling | 7K–8K | 256–512 | no truncation, OOM, or source drift |

Workload weights for aggregated Stage 1 metrics are `35/30/25/10` respectively.
Max model length remains 8192 for every Candidate; reducing product capacity is
not a service optimization. Context trimming is evaluated later as an
application/runtime optimization.

Each workload is materialized in two lanes. This is mandatory because natural
business answers do not have identical output lengths, so comparing their raw
latency or token throughput directly would confound serving performance with
answer length.

1. **Controlled performance lane:** fixed tokenizer-derived input/output token
   lengths for TTFT, TPOT, ITL, end-to-end latency, output throughput, goodput,
   and VRAM. It does not receive a semantic quality score.
2. **Business-quality lane:** frozen public/synthetic product prompts with
   natural stopping for schema, Tool Call, factual, boundary, and usefulness
   evaluation. Its latency is retained as diagnostic evidence but is not used
   for cross-profile speed scoring unless actual input/output token counts are
   equal.

Each business-quality workload must include deterministic assertions for
parseability, required fields, tool-call shape, source/uncertainty handling,
and material unsupported facts. Expected prose is not frozen word-for-word.

### 3.2 Candidate matrix

The first implementation freezes exactly eight factor-isolated ranked
profiles. They use the already-cached BF16 model, so the main screen does not
depend on a new model download:

| ID | Difference from `S0` | Purpose |
|---|---|---|
| `S0` | none | known-good control |
| `P1-prefix-cache` | enable prefix caching | repeated system/schema prefix reuse |
| `P2-seqs-2` | `max_num_seqs=2` | interactive latency/resource trade-off |
| `P3-memory-088` | GPU memory utilization `0.88` | safe cache/headroom trade-off |
| `P4-mbt-8192` | `max_num_batched_tokens=8192` | latency-sensitive prefill/decode balance |
| `P5-mbt-16384` | `max_num_batched_tokens=16384` | upper low-TTFT ROCm recommendation |
| `P6-rocm-attn` | `ROCM_ATTN` backend, if supported | preferred Radeon-native backend probe |
| `P7-triton-attn` | `TRITON_ATTN` backend, if supported | Radeon fallback/backend comparison |

Every profile is a prospective declaration with exact arguments, intended
metric, expected trade-off, compatibility evidence, and rollback. The Builder
must capture `vllm serve --help` and startup logs from the installed
`0.23.1rc1` ROCm wheel before emitting commands; current online documentation
cannot be assumed to match that development wheel. `P4` and `P5` require
chunked prefill or another documented configuration in which the cap is valid;
`8192` must never be lower than the frozen maximum model length. `P6` and `P7`
fail closed when unsupported. A failed compatibility probe is retained as
useful evidence and does not block `S0`.

Quantization is an **optional, separately time-boxed compatibility probe**, not
a prerequisite for the ranked v1 screen. Current vLLM hardware tables do not
list AWQ/GPTQ as generally supported on AMD GPUs, while Radeon-specific recipes
and development wheels can differ. Therefore `Q1-awq` and `Q2-gptq` are removed
from the ranked deadline path. One `Q0-gguf` exact-lineage probe may be added as
`serving-screen-v1q` only when all of the following are true: the snapshot and
license are frozen, the installed wheel advertises the path, no model conversion
is needed, and download/load/smoke can finish within a three-hour total timebox.
Failure or expiry records evidence and returns to the BF16 screen; it cannot
delay Stage 1, Stage 2, report work, or submission. Quark calibration/conversion,
custom quantization, AWQ/GPTQ forcing, and a second model are deferred.

A composite may be proposed later only as a new versioned experiment after the
factor screen is frozen. To prevent an open-ended post-hoc search, v1 permits
at most one `C1-composite` under `serving-composite-v1`, selected mechanically:

- at least two factor Candidates must have passed confirmation, preserved both
  quality and reliability at index 100 or higher, and improved their declared
  primary metric by at least 5% versus `S0`;
- choose at most one highest-Stage1Score factor from each orthogonal group:
  cache/capacity (`P1`/`P3`), scheduler/prefill (`P2`/`P4`/`P5`), and attention
  backend (`P6`/`P7`);
- freeze the resulting arguments and hash before running it; never silently
  replace an incompatible argument; and
- run the complete confirmation schedule and all hard gates. If fewer than two
  factors qualify, the exact installed wheel rejects the combination, or the
  Stage 1 cutoff arrives, record `NOT_RUN_NO_SAFE_FACTORS`,
  `FAILED_COMPATIBILITY`, or `DEFERRED_TIMEBOX` respectively.

`C1` may enter the final Stage 1 Top 3 only through its own complete evidence
and score. The factor observations remain immutable and separate. No second
composite or iterative search is allowed in v1.

This work explicitly excludes 70B/80B models, fine-tuning, distillation, LoRA,
custom kernel rewriting, and unverified CUDA/FA2 or Instinct-only recipes.

### 3.3 Execution schedule

To preserve rigor under the contest deadline, measurement has two passes:

**Compatibility and quick screen — all profiles**

- cold load and health check;
- one controlled restart and reload;
- controlled performance W1–W4: 1 warm-up plus 3 measured observations at
  concurrency 1;
- W1 and W2: one 3-request batch at concurrency 2;
- concurrency 4: one diagnostic W1 batch;
- business-quality W1–W4: one unique frozen case per workload after
  deterministic checks; no external LLM judge at this pass; and
- retain all timeouts, OOMs, parse failures, crashes, restarts and warnings.

These samples eliminate unsafe or clearly inferior profiles. They are not used
as final contest performance claims.

**Confirmation — quick-screen survivors**

- controlled performance W1–W4: 3 warm-ups plus 10 measured observations at
  concurrency 1;
- controlled performance W1–W4: 5 measured observations at concurrency 2;
- W1 and W2: 5 measured observations at concurrency 4 stress;
- business-quality W1–W4: two unique cases per workload, evaluated once at
  temperature zero; quality is not multiplied by repeated identical generations;
- deterministic ordering is generated from a recorded seed;
- report count, failures, median and p95; disclose that the sample is bounded
  and do not claim broad population statistics.

At most four factor-screen hard-gate passers enter confirmation, ordered by the
preliminary score; `S0` is always included as the control. The optional single
`C1` then follows the frozen rule above. Exactly three profiles among the fully
confirmed factor and composite set advance to Stage 2 when at least three pass.
If fewer than three pass, all passing profiles advance with `S0`; the benchmark
must not lower a gate to manufacture three finalists.

The runner uses closed-loop concurrency for this single-user product, resets
service state between profiles, and records cache state. `P1-prefix-cache` must
report cold-cache and warm-prefix results separately; a warm cached Candidate
may not be compared only against a cold `S0`. The official `vllm bench serve`
JSON output is preferred for controlled metrics when the installed wheel
supports the required arguments. A repository runner remains required for
business-quality cases, manifests, VRAM sampling, and a version-gated fallback.
Every profile boundary is resumable and append-only.

## 4. Stage 1 gates and score

### 4.1 Hard gates

A profile is ineligible for ranking when any of the following is true:

- core inference is not proven local on W7900/ROCm;
- it cannot load, respond, restart, and return to the known-good profile;
- any required workload produces an OOM, crash, silent truncation, concealed
  terminal failure, or missing record;
- startup plus warm-up fails to converge within 20 minutes; convergence means
  the last three W1 probe values for TTFT and output TPS remain within a 10%
  band after at least one full W1–W4 warm-up cycle (maximum five cycles);
- W4 cannot complete under the frozen 8192-token service capability;
- schema/tool-call success falls by more than 2 percentage points from `S0`;
- semantic quality is below 95% of `S0` on the frozen rubric;
- any material unsupported fact, privacy/permission bypass, or unsafe tool
  proposal appears;
- peak VRAM leaves less than 2 GiB measured headroom on the assigned W7900; or
- manifest, raw observations, failure evidence, or rollback evidence is incomplete.

Hard gates override the numeric score. A faster failing profile cannot advance.

### 4.2 Quality rubric

Each output receives 0–4 on five public dimensions:

1. source/factual fidelity;
2. structured contract or tool-proposal validity;
3. task completeness;
4. uncertainty and applicability boundaries; and
5. instruction adherence without needless verbosity.

The scale is fixed: `0` is unusable, contradictory, fabricated, or materially
invalid; `1` has a major error/omission that prevents reuse; `2` is partially
useful but needs substantial correction; `3` is correct and reusable with only
minor repair; `4` is complete, grounded, precise and directly reusable. The
quality value is the arithmetic mean across all dimensions and outputs after
deterministic gates. Outputs are never silently dropped.

Deterministic assertions run first and may veto a semantic score. The quick
screen uses deterministic quality checks only. For confirmation outputs that
are public, synthetic, or de-identified, a fixed strong external model may act
as a second judge. Its provider/model/version, rubric, temperature, prompt hash,
input hash and raw response must be recorded. Candidate identities are blinded,
pair order is swapped, and judge disagreement or a deterministic failure goes
to human review. Order-swapped scores are averaged; an order delta greater than
1 point on any dimension, a one-point-or-greater disagreement with human spot
review, or any pass/fail disagreement requires adjudication. External judging
is evaluation-only and never enters the core product path.

### 4.3 Reproducible score

For every metric, `S0` has index 100. For lower-is-better metrics:

```text
index = 100 * S0_value / candidate_value
```

For higher-is-better metrics:

```text
index = 100 * candidate_value / S0_value
```

Each index is capped at 150 so one extreme result cannot dominate. Workload
aggregation uses the fixed `35/30/25/10` weights. Concurrency aggregation uses
70% concurrency 1 and 30% concurrency 2; concurrency 4 is a hard stress record
and does not improve the ranking score.

```text
Stage1Score =
    0.30 * QualityPreservationIndex
  + 0.20 * P95TTFTIndex
  + 0.10 * P95TPOTIndex
  + 0.10 * MedianEndToEndLatencyIndex
  + 0.10 * OutputThroughputIndex
  + 0.10 * PeakVRAMIndex
  + 0.10 * ReliabilityAndGoodputIndex
```

`S0` therefore scores 100 by definition. Missing required metrics fail the
profile rather than being imputed. Ranking uses the confirmation pass only and
must show each component, not just the total. Ties are resolved by quality
index, then p95 TTFT index, then peak-VRAM index, then lexical profile ID; the
tie rule is applied mechanically and does not authorize a product promotion.

Goodput is the fraction of requests that pass correctness gates and meet all
three `S0`-derived SLOs for TTFT, TPOT, and end-to-end latency. SLO values are
frozen after the independent `S0` run and before any Candidate score is viewed;
the default threshold for each is `1.10 * S0 p95`. Startup duration, warm-up
cycles, ITL distribution, cache state, and preemption/warning counts are
reported but do not receive a separate weight in v1.

## 5. Stage 2 application evaluation

Stage 2 starts only after the complete Agent commit and `A0 Application
Baseline` are frozen. The three Stage 1 finalists are plugged into the same
application commit, prompts, fixtures, runtime, database seed, tool policy and
generation settings. No application code may be tuned per finalist.

### 5.1 Frozen profile and fixture matrix

`A0` is the complete Agent using `S0`. Each unique Stage 1 finalist other than
`S0` becomes `A1` through `A3` in descending Stage 1 rank. If `S0` is itself a
finalist, it is represented only by `A0`; it is never duplicated to increase
its sample count. Stage 2 therefore evaluates three or four unique application
profiles, always including `A0`.

The public matrix uses all seven versioned Experience Asset fixtures:

| Fixture | Weight | Expected product outcome |
|---|---:|---|
| `chair_public_complete` | 30% | complete M1–M5 asset and eligible routes |
| `chair_incomplete` | 10% | visible request for evidence or bounded degraded result |
| `chair_conflicting` | 10% | conflict surfaced for user resolution; no invented merge |
| `chair_privacy_risk` | 10% | share/export blocked pending explicit review/approval |
| `chair_route_ineligible` | 10% | ineligible route and reason, without fabricated content |
| `chair_correction` | 15% | affected artifacts invalidated and correctly regenerated |
| `chair_resume` | 15% | durable pause/restart/resume without confirmed-state loss |

Before any measured run, freeze and hash the exact application commit, model
profile map, all prompts, fixture inputs/expected terminal states, clean SQLite
seed, Runtime/tool policy, retrieval index, renderer version, generation
settings, runner, deterministic scorer, semantic rubric, seed, and evidence
directory. Each measured run receives a clean copy of the database seed, a
unique run/artifact directory, and an empty transient cache. Product data may
not leak from one profile or repetition into another.

### 5.2 Execution schedule

Stage 2 also uses a bounded funnel:

**Eligibility pass — every unique application profile**

- load the complete Agent and selected loopback vLLM profile;
- run one unscored `chair_public_complete` warm-up and verify locality;
- run each of the seven fixtures once in a recorded seed-derived order;
- run all deterministic business, RAG-phase, permission, privacy, terminal,
  persistence, correction, resume, and export checks; and
- stop that profile before confirmation when any hard gate fails, while
  retaining its complete failure packet.

**Reliability confirmation — eligibility passers only**

- run two additional clean repetitions of `chair_public_complete`,
  `chair_correction`, and `chair_resume`;
- this produces 13 measured full flows per passing profile: seven eligibility
  flows plus six confirmation flows;
- deterministic checks score every flow; semantic judging scores one canonical
  artifact per fixture/profile rather than repeatedly judging byte-identical
  temperature-zero outputs; and
- report count, numerator/denominator, median, range and all failures. Do not
  report a p95 from this bounded business sample.

Profile block order and fixture order are generated from recorded seeds. `A0`
runs first and a final unscored `chair_public_complete` bookend checks drift. If
its TTFA or end-to-end latency changes by more than 10%, or its deterministic
outcome changes, invalidate timing comparisons and investigate before scoring;
quality/safety failures remain recorded. One transient infrastructure retry is
allowed, labeled separately. Product errors are not retried away.

### 5.3 Hard gates

- M1–M5 flow, correction, pause/resume, persistence and final rendering work;
- cross-asset RAG remains forbidden before post-M4 readiness and detailed
  historical retrieval still requires user confirmation;
- Runtime validates every tool name, permission and argument; model output is
  only a proposal;
- incomplete, contradictory, privacy-risk and ineligible-route cases stop or
  ask visibly instead of fabricating facts;
- no unsupported material fact, lost confirmed state, hidden failure or remote
  core inference occurs; and
- every run reaches its fixture's expected valid terminal state with complete
  local evidence;
- deterministic permission, privacy, RAG-phase, unsupported-fact and export
  checks pass on 100% of measured flows;
- semantic Experience Asset quality is at least 95% of `A0`, and structured
  contract/terminal success is no more than 2 percentage points below `A0`;
  and
- the application, prompt, Runtime, database seed, fixture, renderer, and
  generation identities are identical across application profiles.

Any hard-gate failure makes the profile ineligible regardless of speed or
resource savings. `needs_input`, `safe_stop`, or `route_ineligible` is a success
when it is the fixture's frozen expected terminal outcome.

### 5.4 Component definitions and score

The public 0–4 Experience Asset rubric scores source fidelity, critical-moment
and decision/evidence completeness, fact-versus-inference separation,
uncertainty/applicability boundaries, and audience-route usefulness. It uses
the fixed fixture weights above. Deterministic checks run first and can veto a
semantic score. The external judge follows the same blinded/swapped-order,
public-data-only, provenance, disagreement, and human-adjudication rules as
Stage 1.

The remaining raw components are fixed as follows:

- `CompletionAndRecovery`: 60% expected-terminal-state correctness plus 40%
  declared tool/failure recovery correctness, both measured as pass rates;
- `FirstArtifactAndQuestionBurden`: 60% time-to-first-useful-artifact index plus
  40% prioritized-question-burden index; question burden counts total questions,
  rounds, and any avoidable repeat after confirmed state;
- `EndToEndLatency`: fixture-weighted mean of each fixture's median measured
  wall time from accepted input to expected terminal outcome;
- `CorrectionPauseResume`: 50% correction invalidation/regeneration pass rate,
  25% pause/restart/resume pass rate, and 25% canonical-version/history
  preservation pass rate; and
- `VRAMAndModelCallEfficiency`: 50% peak-VRAM index and 50% successful-flow
  model-call-count index.

All lower/higher-is-better values use the same `A0=100` index formulas and the
150 cap from Stage 1. Ratios with a zero baseline fail validation rather than
being imputed. Every component table exposes its raw numerator, denominator,
units, fixture values, index, and weight.

The same baseline-index formula applies with `A0 = 100`:

```text
Stage2Score =
    0.35 * ExperienceAssetQualityIndex
  + 0.20 * CompletionAndRecoveryIndex
  + 0.15 * FirstArtifactAndQuestionBurdenIndex
  + 0.15 * EndToEndLatencyIndex
  + 0.10 * CorrectionPauseResumeIndex
  + 0.05 * VRAMAndModelCallEfficiencyIndex
```

The final recommendation ranks only profiles that pass all hard gates. It
reports both Stage 1 and Stage 2 results; Stage 1 is not averaged into Stage 2
because product fitness is the final decision boundary. Ties resolve by
Experience Asset quality, Completion/Recovery, first-artifact/question burden,
end-to-end latency, and lexical application-profile ID in that order.

### 5.5 Stage 2 evidence and decision

Each Stage 2 run group must contain:

```text
application-contract.json
profile-map.json
fixture-manifest.json
observations.jsonl
trace-index.json
deterministic-results.json
judge-results.json
gate-report.json
score-components.json
recommendation.md
hashes.sha256
```

The recommendation names one selected application profile or explicitly keeps
`A0`. It includes raw and indexed components, all exclusions, judge/human
disagreements, the A0 drift bookend, failed/retried runs, full launch/rollback
commands, and a sanitized report/demo table. Selection requires quality-owner
sign-off; a Scorer Codex may calculate but cannot promote the product itself.

## 6. Deadline budget and stop rules

The official deadline is 2026-08-06 23:59 UTC+8 and the repository's internal
submission cutoff is 2026-08-06 12:00 UTC+8. At the design-hardening timestamp,
about 66 hours remain before the internal cutoff. The accepted W7900 serving
reference measured 27.354 output tokens/s for a 434-token prompt and
169–185-token outputs; one E3 business-shaped model call took about 33 seconds.
Those are planning observations, not Stage 1 measurements.

The benchmark receives the following wall-clock budget:

| Work | Maximum | Target finish (UTC+8) | Stop rule |
|---|---:|---|---|
| SB1–SB3 implementation, tests, dry-run and `S0` smoke | 6 h | Aug 3 23:59 | cut optional adapters; do not reduce evidence/gates |
| Eight-profile compatibility and quick screen | 4 h | Aug 4 04:00 | one transient-infrastructure retry only |
| Four factor profiles plus optional one composite, scoring and review | 6 h | Aug 4 10:00 | composite expires first; retain partial packet; never cherry-pick |
| Optional `Q0-gguf` compatibility probe | 3 h inside parallel slack | Aug 4 10:00 | expiry means `DEFERRED_TIMEBOX`, never a blocker |
| Stage 2 A0 plus finalists after application freeze | 6 h | Aug 5 14:00 | no per-profile application tuning; preserve BF16 fallback |
| Sanitized summaries, plots and evidence backup | 4 h | Aug 5 20:00 | raw data remains backed up; no rerun for prettier numbers |

Expected Stage 1 execution is 6–10 hours after SB1–SB3, including repeated
server starts and the known longer Radeon warm-up risk in this vLLM version.
Stage 2 is expected to take 3–6 hours once the application is frozen. End to
end, implementation plus both evaluation stages should consume 16–24 hours of
Pod/Agent time. That fits the current window only if it runs in parallel with
product completion and does not wait for report writing to begin.

Absolute control points:

- by Aug 4 10:00 UTC+8, freeze the Stage 1 evidence and ranking;
- by Aug 5 06:00 UTC+8, freeze the application commit and `A0` inputs;
- by Aug 5 14:00 UTC+8, finish Stage 2 or record exactly why it is incomplete;
- after Aug 5 20:00 UTC+8, no unmeasured serving/model swap enters the product;
- Aug 6 is for submission verification and failure buffer, not new optimization.

If Stage 2 cannot start by its cutoff, retain `S0` as the submitted service,
report Stage 1 as service-layer evidence only, and run the complete Agent once
with the known-good profile for locality/correctness evidence. An unfinished
Top-3 product comparison must not be described as a final product ranking.

## 7. Best-practice review and deliberate limits

The 2026-08-03 review made these prospective changes before measurement:

- [vLLM `bench serve`](https://docs.vllm.ai/en/latest/cli/bench/serve/) is the
  preferred controlled-metric source because it can retain detailed JSON and
  TTFT/TPOT/ITL/E2EL percentiles; the installed development wheel is checked
  before use.
- [vLLM parameter sweeps](https://docs.vllm.ai/en/latest/benchmarking/sweeps/)
  support resumable, prospective `max_num_seqs` and
  `max_num_batched_tokens` exploration. The implementation may use that CLI
  only when its on-Pod version exposes the required commands; otherwise it
  reproduces the same frozen Cartesian profile list in the repository runner.
- [AMD's ROCm vLLM optimization guide](https://rocm.docs.amd.com/en/docs-7.2.4/how-to/rocm-for-ai/inference-optimization/vllm-optimization.html)
  recommends fixing ISL/OSL, varying one factor, measuring TTFT/ITL/TPS
  together, testing 8K–16K batched-token caps for latency-sensitive use, and
  comparing `ROCM_ATTN` with the Triton fallback on Radeon. These become the
  ranked candidates.
- [vLLM's quantization support table](https://docs.vllm.ai/en/stable/features/quantization/)
  does not provide a safe general Radeon assumption for AWQ/GPTQ. Those paths
  are therefore not deadline-critical ranked Candidates. A GGUF probe is
  optional and time-boxed; Quark conversion/calibration is deferred because it
  adds a separate model-production pipeline.
- Model-judge position bias is controlled through blinded swapped-order pairs,
  deterministic checks first, and human adjudication. External evaluation
  receives only public/synthetic/de-identified content.

The plan deliberately excludes GEMM auto-tuning, custom kernels, speculative
decoding, graph-mode sweeps, fine-tuning, a second base model, and application
prompt tuning from Stage 1. They may be valid later work, but each expands the
matrix and makes causal attribution and deadline recovery worse.

## 8. Builder, evidence freeze, and scorer separation

The recommended Codex workflow is:

1. **Contract freeze:** quality owner freezes this document, profile files,
   workload hashes, expected deterministic checks and scorer version.
2. **Builder Codex:** implements profiles, runners, manifest validation,
   workload execution and evidence export. It may run unit/smoke tests but does
   not change weights or gates after seeing measurements.
3. **Evidence run:** Pod Codex runs every declared profile and writes an
   append-only evidence pack. Failed profiles remain in the pack.
4. **Evidence freeze:** record commit, manifest hashes, raw-record hashes,
   scorer version and run-completion timestamp. The pack becomes read-only for
   scoring purposes.
5. **Scorer Codex:** reads the frozen pack, validates admissibility, computes
   the public score and produces the ranking. It must not edit profiles,
   workloads, runner output or implementation.
6. **Quality review:** a human resolves deterministic/judge disagreement,
   checks the top three evidence packets and signs the promotion decision.

If the same Codex conversation performs implementation and scoring, start a
new scoring conversation with only this contract and the frozen evidence pack.
This is not a security boundary, but it reduces accidental target fitting.
Hidden blind fixtures, gold answers and private aggregation remain outside the
shared repository and shared Pod.

## 9. Required evidence layout

Large/raw data is stored persistently under:

```text
/workspace/amd-track2-agent/benchmarks/serving-screen-v1/
├── contract/
├── profiles/
├── workloads/
├── runs/<run_group_id>/
│   ├── manifest.json
│   ├── observations.jsonl
│   ├── vllm.log
│   ├── amd-smi.csv
│   ├── deterministic-results.json
│   ├── judge-results.json
│   └── hashes.sha256
├── scores/
└── reports/
```

The integration checkout keeps small sanitized definitions and summaries in:

```text
benchmarks/profiles/
benchmarks/workloads/service-v1/
evidence/performance/serving-screen-v1/
```

For every profile retain candidate declaration, exact model and environment,
full launch command, load/restart/rollback result, every observation, TTFT,
latency, throughput, token counts, VRAM samples, quality checks, failures,
score components, screenshots/log references, `amd-smi`/ROCm local proof, and a
`PASS`, `FAIL`, or `ROLLBACK` disposition. Raw evidence is copied to approved
backup before a Pod rebuild; `/workspace` persistence alone is not a backup.

## 10. Implementation work packages

| Package | Outcome | Acceptance evidence |
|---|---|---|
| `SB1-contract` | versioned profiles, workloads, schemas and frozen hashes | validation test plus reviewed hash manifest |
| `SB2-runner` | one command runs a profile, samples VRAM and emits all records | local fake-server tests and Pod smoke packet |
| `SB3-quality` | deterministic checks and optional blinded external-judge adapter | fixture tests; secret scan; no private payload |
| `SB4-screen` | all declared profiles run through the two-lane quick screen | append-only packets including failures/rollback |
| `SB5-confirm` | at most four factor profiles plus optional `C1` complete confirmation | comparable manifests and raw records |
| `SB6-score` | read-only scorer validates and ranks admissible profiles | component table, hard-gate report and hashes |
| `SB7-stage2` | A0 plus unique Top-3 profiles run across the frozen 7+6 flow matrix | A0-relative report, drift bookend and signed recommendation |

`SB1` through `SB3` are implemented before any measurement used for ranking.
`SB4` and `SB5` never modify the contract. `SB6` refuses incomplete or changed
evidence. `SB7` is deliberately deferred until the complete product exists.

## 11. Definition of done for Stage 1 readiness

Stage 1 may start on the user's Pod only when:

- SB1–SB3 behavior is implemented and tested;
- the repository's required checks pass;
- a clean checkout reproduces the runner command;
- the known-good `S0` loads on W7900 and the rollback command is verified;
- `/workspace` and external-backup destinations exist without secrets in Git;
- all profiles and workloads have immutable hashes;
- controlled performance and natural-output business-quality lanes cannot be
  accidentally aggregated into one latency score;
- resume from a completed profile boundary and cache-reset behavior are tested;
- scoring code reproduces a synthetic reference result; and
- the quality owner records `STAGE1_READY`.

The current status is design-complete but not Stage 1 ready. The next task is
to implement SB1–SB3; running profiles manually before that may help debug but
cannot enter the ranked evidence set.
