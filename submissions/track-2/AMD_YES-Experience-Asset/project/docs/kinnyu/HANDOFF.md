# HANDOFF — W7900 Serving Benchmark Builder

## Metadata

- Updated: 2026-08-03 19:40 AEST / 17:40 UTC+8
- Mode: CONTINUE
- Work package: `PERF-SERVING-SCREEN-V1`
- Route: FEATURE
- Requirement: APPROVED
- Engineering design: HARDENED / IMPLEMENTATION NOT STARTED
- Local worktree: `/private/tmp/amd-serving-benchmark-design`
- Branch: `codex/serving-benchmark-design`
- Base: the `origin/main` snapshot used to create that worktree
- Pod integration checkout: `/workspace/amd-track2-agent/repo`
- Official deadline: 2026-08-06 23:59 UTC+8
- Internal submission cutoff: 2026-08-06 12:00 UTC+8
- Git authority: no commit, push, PR, merge, rebase, or GitHub-setting change
  is authorized by this handoff.

## Goal

Implement a reproducible two-lane Stage 1 benchmark on one Radeon PRO W7900:

1. a controlled fixed-token performance lane for TTFT, TPOT, ITL, E2EL,
   output throughput, goodput, and peak VRAM; and
2. a natural-output business-quality lane for schema/Tool Call validity,
   factual grounding, boundaries, completeness, and usability.

The benchmark screens serving configurations before the complete application
exists. It does not choose the submitted product profile; that requires Stage
2 against the frozen complete Agent (`A0`). Track 2 relevance is direct:
local W7900/ROCm/vLLM optimization, quality preservation, and reproducible
evidence for the technical report, charts, and demo.

## Authoritative sources

Read these completely before proposing or changing code:

1. `AGENTS.md`
2. `spec/README.md`
3. `spec/AGENT_ALIGNMENT.md`
4. `README.md`
5. `docs/kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md`
6. `docs/team-alignment/BENCHMARK_PLAN.md`
7. `spec/EVIDENCE_RETENTION.md`
8. `docs/DEVELOPMENT_ENVIRONMENT.md`
9. `docs/TEAM_GIT_WORKFLOW.md`
10. `docs/COMPETITION_AND_GROUP_SUMMARY.md`

The engineering plan is the exact Stage 1 authority. Product and safety
contracts still override a performance gain.

## Frozen decisions

- `S0`: exact Qwen2.5-14B-Instruct revision, BF16, max model length 8192,
  GPU memory utilization 0.82, max sequences 4, Hermes Tool parser,
  loopback-only vLLM, one W7900/ROCm.
- Ranked profiles: `S0`, prefix cache, max sequences 2, memory utilization
  0.88, MBT 8192, MBT 16384, ROCM_ATTN, TRITON_ATTN.
- W1–W4 shapes and weights: 35/30/25/10.
- Concurrency: c1 primary (70%), c2 secondary (30%), c4 stress only.
- Quick screen: all eight; confirmation: at most four factors including S0;
  one optional mechanically selected composite may be fully confirmed; Stage 2:
  at most three hard-gate passers.
- Stage 1 weights: quality 30, p95 TTFT 20, p95 TPOT 10, median E2EL 10,
  output throughput 10, peak VRAM 10, reliability/goodput 10.
- Hard gates always override score.
- External LLM judge is confirmation-only, blinded/swapped-order, and may see
  only public/synthetic/de-identified data. Deterministic and human review can
  veto it.
- AWQ/GPTQ are not in ranked v1. Optional exact-lineage GGUF is a separately
  versioned three-hour compatibility probe and may not block the BF16 screen.
- Do not add a second model, fine-tune, convert with Quark, write kernels, or
  expose the service publicly.

## Existing measured planning evidence

- W7900: gfx1100, 48 GiB profile, ROCm/HIP 7.2 path.
- Installed evidence wheel:
  `vllm 0.23.1rc1.dev1327+gf25953cc5.rocm723`.
- Existing service reference:
  `evidence/milestones/e2-m1-w7900/20260801T094735Z/artifacts/serving-reference-s1.json`.
- That reference observed 27.354 output tokens/s and 6.568 s mean latency for
  a 434-token prompt and 169–185-token outputs. It is planning evidence only,
  not a Stage 1 score.
- E3 recorded one business-shaped semantic call of about 33 seconds.

## Best-practice constraints to preserve

- Capture the installed `vllm serve --help`, `vllm bench --help`, and startup
  backend logs. Do not copy commands from latest online docs blindly.
- Prefer detailed JSON from `vllm bench serve` for the controlled lane when
  the installed wheel supports it. Implement a repository runner for manifests,
  business cases, VRAM sampling, and version-gated fallback.
- Fixed ISL/OSL measurements and natural business responses are separate.
  Never score their latency as one homogeneous sample.
- Reset service/cache state between profiles. Prefix-cache has separate cold
  and warm-prefix observations.
- Closed-loop max concurrency is used for c1/c2/c4.
- Every profile boundary checkpoints append-only state and can resume.
- Minimum one W1–W4 warm-up cycle; continue until the last three W1 TTFT/TPS
  probes fit within a 10% band, maximum five cycles/20 minutes.
- Freeze S0-derived TTFT/TPOT/E2EL goodput SLOs before viewing Candidate scores.
- Record all failures and one transient-infrastructure retry at most.

## Time budget

| Work | Max wall time |
|---|---:|
| SB1–SB3 implementation, tests, dry-run, S0 smoke | 6 h |
| Eight-profile quick screen | 4 h |
| Four factors plus optional one composite, scoring, review | 6 h |
| Optional GGUF probe | 3 h and never blocking |
| Stage 2 after application freeze | 6 h |
| Sanitized summaries, plots, backup | 4 h |

Control points in UTC+8: Stage 1 frozen by Aug 4 10:00; application frozen by
Aug 5 06:00; Stage 2 done by Aug 5 14:00; evidence/plots frozen by Aug 5 20:00.
After that point no unmeasured service/model swap enters the product.

Stage 2 always includes `A0 = complete Agent + S0` and each unique Top-3
finalist once. It runs the seven public fixtures once for eligibility, then two
additional clean runs each for complete/correction/resume (13 flows per passing
profile), with isolated database/artifact state and an A0 drift bookend. Exact
component definitions, hard gates, fixture weights, evidence filenames and tie
rules are frozen in Section 5 of the engineering plan.

## First implementation slice (SB1–SB3 only)

Create the smallest coherent files needed for:

- versioned profile declarations under `benchmarks/profiles/`;
- versioned controlled and business workloads under
  `benchmarks/workloads/service-v1/`;
- JSON Schemas for manifest, observation, gate, and score records;
- a runner that supports `--dry-run`, one profile, append-only output,
  profile-boundary resume, timeouts, token accounting, streaming metrics,
  VRAM sampling, cache-state labels, and rollback;
- deterministic business-quality checks;
- a scorer that reads frozen evidence and refuses incomplete/hash-mismatched
  packets; and
- unit/fake-server tests that do not require the Pod.

Do not start ranked measurements until the Stage 1 readiness checklist in the
engineering plan passes and `STAGE1_READY` is explicitly recorded.

## Acceptance and evidence

- A clean checkout can reproduce the dry-run and fake-server tests.
- Profile/workload/scorer identities are hashable and immutable per run group.
- Controlled and quality records have distinct schemas/lane labels.
- Runner resumes without repeating or overwriting completed observations.
- Failed load/request/restart/rollback paths are retained and scored fail-closed.
- Synthetic scorer reference reproduces an expected component table.
- No credentials, private data, model cache, raw private prompt/response, or
  large raw evidence enters Git.
- Pod packets go under
  `/workspace/amd-track2-agent/benchmarks/serving-screen-v1/`; sanitized small
  summaries later go under `evidence/performance/serving-screen-v1/`.

Required repository checks:

```bash
bash -n scripts/*.sh
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s qa/tests -v
bash qa/gates/pr_gate.sh --mode contract
git diff --check
```

Before a real Pod run also execute:

```bash
bash scripts/verify_remote_dev.sh
bash scripts/verify_rocm_env.sh
source /workspace/amd-track2-agent/venvs/agent/bin/activate
pytest
ruff check .
```

## Exact next action for a fresh Codex session

1. Open `/private/tmp/amd-serving-benchmark-design`.
2. Read the ten authoritative files above and return the six-heading report
   required by `spec/AGENT_ALIGNMENT.md`.
3. Inspect the current vLLM scripts/tests and propose the exact SB1–SB3 file
   list and one-command interface. Treat the approved engineering plan as
   authority; ask only about a genuine conflict.
4. Implement SB1–SB3, run repository checks, and stop at `STAGE1_READY` review.
5. Do not commit/push or run the ranked Pod matrix without fresh authority in
   that conversation.

Suggested new-session instruction:

```text
Work in /private/tmp/amd-serving-benchmark-design. Read AGENTS.md,
spec/README.md, spec/AGENT_ALIGNMENT.md, README.md,
docs/kinnyu/SERVING_BENCHMARK_ENGINEERING_PLAN.md,
docs/team-alignment/BENCHMARK_PLAN.md, spec/EVIDENCE_RETENTION.md,
docs/DEVELOPMENT_ENVIRONMENT.md, docs/TEAM_GIT_WORKFLOW.md and
docs/COMPETITION_AND_GROUP_SUMMARY.md. Return the mandatory six-heading
alignment report, then implement only SB1–SB3 from the approved benchmark plan.
Run all repository checks and prepare a STAGE1_READY review packet. Preserve
both benchmark lanes, append-only/resumable evidence, timeboxes and the BF16
fallback. Do not commit, push, publish, expose services or start ranked Pod
measurements without my explicit approval.
```

After the Pod evidence pack is frozen, use a separate scoring conversation:

```text
Act only as the read-only Scorer for serving-screen-v1. Read the approved
engineering plan and the frozen evidence pack named by its run_group_id.
Verify contract/profile/workload/scorer hashes, completeness, lane separation,
cache labels, sample counts, failure retention and hard gates before computing
any score. Recompute every S0-relative component mechanically, refuse missing
or changed evidence, show exclusions and ties, and produce the component table,
gate report and ranking. Do not edit profiles, prompts, workloads, raw records,
runner code, weights or gates. Do not hide failed runs or promote a service
profile into the application; output only the Stage 1 Top-3 recommendation for
Stage 2 review.
```

## Unverified items

- No SB1–SB3 code exists yet.
- No official Stage 1 S0 freeze, quick screen, confirmation, score, or ranking
  has run.
- Current-wheel availability of the latest `vllm bench`/sweep flags is unknown
  until inspected on the Pod.
- Peak VRAM and streaming TTFT/TPOT/ITL are not present in the old S1 reference.
- Complete Agent `A0` and Stage 2 remain dependent on product freeze.
- Optional GGUF support/snapshot is intentionally unresolved and non-blocking.
